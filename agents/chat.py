"""Agent: Chat Interface — agentic LLM with function calling and reasoning."""

import os
import json
import io
import sys
import threading

import httpx
import google.generativeai as genai

from agents.llm import gemini_lock
from db import init_db, get_connection
from agents.collect import collect
from agents.classify import classify
from agents.analyze import analyze
from scraper.web_search import search_news, search_web, search_reddit, search_youtube, format_search_results
from scraper.reddit_rss import search_reddit_rss
from scraper.hackernews import search_hackernews
from scraper.youtube import get_video_transcript, fetch_transcripts_from_search_results, format_transcripts_for_prompt
from agents.seo import seo_audit
from agents.financial import financial_analysis
from agents.techstack import techstack_analysis
from agents.patents import patent_analysis
from agents.pricing import pricing_analysis
from agents.competitors import competitor_analysis
from agents.sentiment import sentiment_analysis
from agents.profile import company_profile
from agents.compare import compare_companies, landscape_analysis
from prompts.chat import SYSTEM_PROMPT, TOOL_SCHEMAS

MAX_HISTORY = 20
MAX_TOOL_RESULT_CHARS = 4000  # Keep small — history compression handles the rest

# Lock for sys.stdout swap — prevents concurrent tool executions from clobbering each other
_stdout_lock = threading.Lock()


class _ProgressWriter(io.TextIOBase):
    """Stdout replacement that forwards complete lines to a callback."""

    def __init__(self, callback):
        self.callback = callback
        self._buf = ""

    def write(self, s):
        self._buf += s
        while '\n' in self._buf:
            line, self._buf = self._buf.split('\n', 1)
            line = line.strip()
            if line:
                self.callback(line)
        return len(s)

    def flush(self):
        if self._buf.strip():
            self.callback(self._buf.strip())
            self._buf = ""


# --- Gemini tool-calling conversion helpers ---

def _openai_tools_to_gemini(tools):
    """Convert OpenAI tool schemas to Gemini function declarations."""
    declarations = []
    for tool in tools:
        fn = tool["function"]
        params = fn.get("parameters", {})
        # Gemini doesn't support top-level 'required' in the same way;
        # pass properties as-is, it handles them fine
        declarations.append(genai.protos.FunctionDeclaration(
            name=fn["name"],
            description=fn.get("description", ""),
            parameters=_convert_schema(params) if params.get("properties") else None,
        ))
    return declarations


def _convert_schema(schema):
    """Convert an OpenAI JSON Schema to Gemini Schema proto."""
    type_map = {
        "string": genai.protos.Type.STRING,
        "integer": genai.protos.Type.INTEGER,
        "number": genai.protos.Type.NUMBER,
        "boolean": genai.protos.Type.BOOLEAN,
        "array": genai.protos.Type.ARRAY,
        "object": genai.protos.Type.OBJECT,
    }

    properties = {}
    for prop_name, prop_schema in schema.get("properties", {}).items():
        prop_type = prop_schema.get("type", "string")
        prop_kwargs = {
            "type_": type_map.get(prop_type, genai.protos.Type.STRING),
            "description": prop_schema.get("description", ""),
        }
        # Handle array items
        if prop_type == "array" and "items" in prop_schema:
            item_type = prop_schema["items"].get("type", "string")
            prop_kwargs["items"] = genai.protos.Schema(
                type_=type_map.get(item_type, genai.protos.Type.STRING)
            )
        # Handle enum
        if "enum" in prop_schema:
            prop_kwargs["enum"] = prop_schema["enum"]

        properties[prop_name] = genai.protos.Schema(**prop_kwargs)

    return genai.protos.Schema(
        type_=genai.protos.Type.OBJECT,
        properties=properties,
        required=schema.get("required", []),
    )


def _openai_messages_to_gemini(messages):
    """Convert OpenAI message history to Gemini Content objects.

    Returns (system_instruction, contents) where system_instruction is a string
    (or None) and contents is a list of Gemini Content objects.
    """
    system_instruction = None
    contents = []
    # Map tool_call_id → function name for tool response messages
    tc_id_to_name = {}

    for msg in messages:
        role = msg.get("role", "user")
        if role == "system":
            system_instruction = msg["content"]
        elif role == "user":
            contents.append(genai.protos.Content(
                role="user",
                parts=[genai.protos.Part(text=msg["content"])],
            ))
        elif role == "assistant":
            parts = []
            content_text = msg.get("content", "")
            if content_text:
                parts.append(genai.protos.Part(text=content_text))
            # Handle tool calls in assistant messages
            for tc in msg.get("tool_calls", []):
                fn = tc["function"]
                fn_args = json.loads(fn["arguments"]) if isinstance(fn["arguments"], str) else fn["arguments"]
                tc_id_to_name[tc["id"]] = fn["name"]
                parts.append(genai.protos.Part(
                    function_call=genai.protos.FunctionCall(
                        name=fn["name"],
                        args=fn_args,
                    )
                ))
            if parts:
                contents.append(genai.protos.Content(role="model", parts=parts))
        elif role == "tool":
            fn_name = msg.get("name") or tc_id_to_name.get(msg.get("tool_call_id"), "unknown")
            contents.append(genai.protos.Content(
                role="user",
                parts=[genai.protos.Part(
                    function_response=genai.protos.FunctionResponse(
                        name=fn_name,
                        response={"result": msg["content"]},
                    )
                )],
            ))
    return system_instruction, contents


def _gemini_response_to_openai(response):
    """Convert Gemini response to OpenAI-compatible format."""
    result = {"role": "assistant", "content": None}
    tool_calls = []

    for part in response.candidates[0].content.parts:
        if hasattr(part, "function_call") and part.function_call.name:
            fc = part.function_call
            tool_calls.append({
                "id": f"call_{fc.name}_{len(tool_calls)}",
                "type": "function",
                "function": {
                    "name": fc.name,
                    "arguments": json.dumps(dict(fc.args)),
                },
            })
        elif hasattr(part, "text") and part.text:
            result["content"] = (result["content"] or "") + part.text

    if tool_calls:
        result["tool_calls"] = tool_calls

    return result


# --- Chat LLM with multi-provider support ---

CHAT_PROVIDERS = [
    # --- Gemini (primary — best quality, native function calling) ---
    {"name": "gemini", "env_key": "GEMINI_API_KEYS", "url": None, "model": "gemini-2.5-flash"},
    {"name": "gemini", "env_key": "GEMINI_API_KEYS", "url": None, "model": "gemini-3-flash-preview"},
    {"name": "gemini", "env_key": "GEMINI_API_KEYS", "url": None, "model": "gemini-2.5-pro"},
    {"name": "gemini", "env_key": "GEMINI_API_KEYS", "url": None, "model": "gemini-3.1-pro-preview"},
    {"name": "gemini", "env_key": "GEMINI_API_KEYS", "url": None, "model": "gemini-2.5-flash-lite"},
    # --- Groq (fast inference, OpenAI-compatible) ---
    {"name": "groq", "env_key": "GROQ_API_KEY", "url": "https://api.groq.com/openai/v1/chat/completions", "model": "llama-3.3-70b-versatile"},
    {"name": "groq", "env_key": "GROQ_API_KEY", "url": "https://api.groq.com/openai/v1/chat/completions", "model": "meta-llama/llama-4-scout-17b-16e-instruct"},
    {"name": "groq", "env_key": "GROQ_API_KEY", "url": "https://api.groq.com/openai/v1/chat/completions", "model": "qwen/qwen3-32b"},
    {"name": "groq", "env_key": "GROQ_API_KEY", "url": "https://api.groq.com/openai/v1/chat/completions", "model": "compound-beta"},
    # --- Cerebras (fast inference) ---
    {"name": "cerebras", "env_key": "CEREBRAS_API_KEY", "url": "https://api.cerebras.ai/v1/chat/completions", "model": "llama-3.3-70b"},
    # --- Mistral (direct API, free tier) ---
    {"name": "mistral", "env_key": "MISTRAL_API_KEY", "url": "https://api.mistral.ai/v1/chat/completions", "model": "mistral-small-latest"},
    # --- OpenRouter (free models) ---
    {"name": "openrouter", "env_key": "OPENROUTER_API_KEY", "url": "https://openrouter.ai/api/v1/chat/completions", "model": "nousresearch/hermes-3-llama-3.1-405b:free"},
    {"name": "openrouter", "env_key": "OPENROUTER_API_KEY", "url": "https://openrouter.ai/api/v1/chat/completions", "model": "meta-llama/llama-3.3-70b-instruct:free"},
    {"name": "openrouter", "env_key": "OPENROUTER_API_KEY", "url": "https://openrouter.ai/api/v1/chat/completions", "model": "qwen/qwen3-next-80b-a3b-instruct:free"},
    {"name": "openrouter", "env_key": "OPENROUTER_API_KEY", "url": "https://openrouter.ai/api/v1/chat/completions", "model": "mistralai/mistral-small-3.1-24b-instruct:free"},
    {"name": "openrouter", "env_key": "OPENROUTER_API_KEY", "url": "https://openrouter.ai/api/v1/chat/completions", "model": "stepfun/step-3.5-flash:free"},
    {"name": "openrouter", "env_key": "OPENROUTER_API_KEY", "url": "https://openrouter.ai/api/v1/chat/completions", "model": "google/gemma-3-27b-it:free"},
    {"name": "openrouter", "env_key": "OPENROUTER_API_KEY", "url": "https://openrouter.ai/api/v1/chat/completions", "model": "nvidia/nemotron-3-nano-30b-a3b:free"},
]


class ChatLLM:
    """Multi-provider chat completions with tool/function calling support."""

    def __init__(self):
        self.http = httpx.Client(timeout=60, follow_redirects=True)
        self.providers = []
        for p in CHAT_PROVIDERS:
            raw_key = os.environ.get(p["env_key"], "").strip()
            if not raw_key:
                continue
            # Gemini supports multiple comma-separated keys — rotate through them
            if p["name"] == "gemini" and "," in raw_key:
                for k in raw_key.split(","):
                    k = k.strip()
                    if k:
                        self.providers.append({**p, "key": k})
            else:
                self.providers.append({**p, "key": raw_key})
        if not self.providers:
            raise RuntimeError("No API keys found for chat (need at least one of: GEMINI_API_KEYS, GROQ_API_KEY, CEREBRAS_API_KEY, MISTRAL_API_KEY, OPENROUTER_API_KEY)")

    def chat(self, messages, tools=None, force_tools=False):
        """Send chat completion request. Returns the assistant message dict.

        Args:
            force_tools: If True and tools are provided, force the model to call
                at least one tool (tool_choice='required'). Use on round 0 to
                ensure the model reasons with tools instead of answering from
                general knowledge.
        """
        errors = []
        for p in self.providers:
            try:
                print(f"[chat] Trying {p['name']}/{p['model']}...")
                if p["name"] == "gemini":
                    result = self._chat_gemini(p, messages, tools, force_tools=force_tools)
                else:
                    result = self._chat_openai(p, messages, tools, force_tools=force_tools)
                tc_count = len(result.get("tool_calls") or [])
                print(f"[chat] OK {p['name']}/{p['model']}"
                      + (f" → {tc_count} tool call(s)" if tc_count else " → text response"))
                return result
            except Exception as e:
                error_str = str(e)
                error_lower = error_str.lower()
                errors.append(f"{p['name']}/{p['model']}: {error_str[:120]}")
                print(f"[chat] FAIL {p['name']}/{p['model']}: {error_str[:120]}")

                # Rate limit detection (check FIRST — TPM/RPM errors contain
                # "token" and "limit" which would false-match context overflow)
                is_rate = ("429" in error_str
                           or "rate limit" in error_lower
                           or "tokens per minute" in error_lower
                           or "requests per minute" in error_lower
                           or "tpm" in error_lower
                           or "rpm" in error_lower
                           or "resource_exhausted" in error_lower
                           or "413" in error_str)
                if is_rate:
                    continue

                # Context overflow — propagate so caller can trim
                if any(kw in error_lower for kw in ["context", "length", "too long", "maximum"]):
                    raise

                continue

        raise RuntimeError("All chat providers failed:\n  " + "\n  ".join(errors))

    def _chat_openai(self, provider, messages, tools=None, force_tools=False):
        """OpenAI-compatible chat completion (Groq, Mistral)."""
        body = {
            "model": provider["model"],
            "messages": messages,
            "temperature": 0.3,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "required" if force_tools else "auto"

        headers = {
            "Authorization": f"Bearer {provider['key']}",
            "Content-Type": "application/json",
        }
        resp = self.http.post(provider["url"], json=body, headers=headers)

        if resp.status_code in (429, 413):
            raise RuntimeError(f"rate limited ({resp.status_code})")
        if resp.status_code != 200:
            try:
                err_detail = resp.json().get("error", {}).get("message", resp.text[:200])
            except Exception:
                err_detail = resp.text[:200]
            raise RuntimeError(f"{resp.status_code} — {err_detail}")

        return resp.json()["choices"][0]["message"]

    def _chat_gemini(self, provider, messages, tools=None, force_tools=False):
        """Gemini native chat completion with function calling."""
        with gemini_lock:
            genai.configure(api_key=provider["key"])

            # Build tool config
            gemini_tools = None
            gemini_tool_config = None
            if tools:
                declarations = _openai_tools_to_gemini(tools)
                gemini_tools = [genai.protos.Tool(function_declarations=declarations)]
                if force_tools:
                    # Force the model to call at least one tool (prevents
                    # answering from general knowledge on the first round)
                    gemini_tool_config = genai.protos.ToolConfig(
                        function_calling_config=genai.protos.FunctionCallingConfig(
                            mode=genai.protos.FunctionCallingConfig.Mode.ANY
                        )
                    )

            # Convert messages
            system_instruction, contents = _openai_messages_to_gemini(messages)

            model = genai.GenerativeModel(
                provider["model"],
                system_instruction=system_instruction,
                generation_config=genai.GenerationConfig(temperature=0.3),
            )

            response = model.generate_content(
                contents,
                tools=gemini_tools,
                tool_config=gemini_tool_config,
            )

        # Convert back to OpenAI format (no lock needed for pure data conversion)
        return _gemini_response_to_openai(response)

    def close(self):
        self.http.close()


def _safe_query_db(sql, db_path):
    """Execute a read-only SQL query. Returns formatted string result."""
    normalized = sql.strip().upper()
    if not normalized.startswith("SELECT"):
        return "Error: Only SELECT queries are allowed."

    for keyword in ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE"]:
        if keyword in normalized.split("SELECT", 1)[0]:
            return f"Error: {keyword} is not allowed."

    try:
        conn = get_connection(db_path)
        cursor = conn.execute(sql)
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        conn.close()

        if not rows:
            return "No results found."

        lines = [" | ".join(columns)]
        lines.append("-" * len(lines[0]))
        for row in rows[:50]:
            lines.append(" | ".join(str(v) for v in row))

        result = "\n".join(lines)
        if len(rows) > 50:
            result += f"\n... ({len(rows)} total rows, showing first 50)"
        return result

    except Exception as e:
        return f"SQL error: {e}"


def _get_dossier_summary(company, db_path):
    """Build a text summary of a company's dossier for the LLM."""
    from db import (get_connection, get_dossier_by_company, get_dossier_staleness,
                    get_latest_key_facts, get_recent_changes)
    from datetime import datetime, timezone

    conn = get_connection(db_path)
    dossier = get_dossier_by_company(conn, company)

    if not dossier:
        conn.close()
        return f"No dossier exists for '{company}'. This is a new company — no prior analyses or knowledge."

    lines = [f"## Dossier: {dossier['company_name']}"]
    if dossier.get("sector"):
        lines.append(f"**Sector:** {dossier['sector']}")
    if dossier.get("description"):
        lines.append(f"**Description:** {dossier['description']}")
    lines.append(f"**Created:** {dossier['created_at']} | **Last updated:** {dossier['updated_at']}")
    lines.append("")

    # Staleness per analysis type
    staleness = get_dossier_staleness(conn, dossier["id"])
    if staleness:
        lines.append("### Analysis History (staleness)")
        now = datetime.now(timezone.utc)
        for atype, last_run in sorted(staleness.items()):
            try:
                last_dt = datetime.fromisoformat(last_run.replace("Z", "+00:00"))
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                days = (now - last_dt).days
                freshness = "fresh" if days < 7 else "recent" if days < 30 else "stale" if days < 90 else "very stale"
                lines.append(f"- **{atype}**: last run {last_run} ({days}d ago — {freshness})")
            except (ValueError, TypeError):
                lines.append(f"- **{atype}**: last run {last_run}")
        lines.append("")

    # Key facts
    facts = get_latest_key_facts(conn, dossier["id"])
    if facts:
        lines.append("### Key Facts (latest per analysis type)")
        for atype, info in facts.items():
            lines.append(f"\n**From {atype}** (as of {info['as_of']}):")
            for k, v in info["data"].items():
                if isinstance(v, list):
                    lines.append(f"  - {k}: {', '.join(str(x) for x in v[:5])}")
                else:
                    lines.append(f"  - {k}: {v}")
        lines.append("")

    # Recent changes detected between scans
    recent_changes = get_recent_changes(conn, dossier["id"], limit=15)
    if recent_changes:
        lines.append(f"### Recent Changes ({len(recent_changes)} detected)")
        for ch in recent_changes:
            date_str = f" [{ch['event_date']}]" if ch.get("event_date") else ""
            desc = ch.get("description", "")
            # Extract source analysis type from description
            source = ""
            if desc and "during" in desc:
                source = f" **[{desc.split('during ')[-1].replace(' analysis', '')}]**"
            lines.append(f"-{source} {ch['title']}{date_str}")
        lines.append("")

    # Other timeline events (non-change events)
    non_change_events = [e for e in dossier.get("events", []) if e.get("event_type") != "change_detected"]
    if non_change_events:
        lines.append(f"### Timeline Events ({len(non_change_events)} total)")
        for evt in non_change_events[:10]:
            date_str = f" ({evt['event_date']})" if evt.get("event_date") else ""
            lines.append(f"- **[{evt['event_type']}]{date_str}** {evt['title']}")
            if evt.get("description"):
                lines.append(f"  {evt['description'][:150]}")
        lines.append("")

    conn.close()
    return "\n".join(lines)


def _save_dossier_event(args, db_path):
    """Save a strategic event to a company's dossier timeline."""
    from db import get_connection, get_or_create_dossier, add_dossier_event

    conn = get_connection(db_path)
    dossier_id = get_or_create_dossier(conn, args["company"])
    add_dossier_event(
        conn, dossier_id,
        event_type=args["event_type"],
        title=args["title"],
        description=args.get("description"),
        event_date=args.get("event_date"),
        source_url=args.get("source_url"),
    )
    conn.close()
    return f"Event saved to {args['company']} dossier: [{args['event_type']}] {args['title']}"


def _execute_tool(name, args, db_path, progress_callback=None):
    """Execute a tool call and return a concise result string for the LLM."""
    # Serialize stdout capture — prevents concurrent tool calls from clobbering each other
    _stdout_lock.acquire()
    old_stdout = sys.stdout
    if progress_callback:
        capture = _ProgressWriter(progress_callback)
    else:
        capture = io.StringIO()
    sys.stdout = capture

    try:
        # --- Reasoning ---
        if name == "think":
            return f"Thinking noted: {args.get('reasoning', '')}"

        # --- Raw Data Tools ---
        elif name == "search_sec_edgar":
            from scraper.sec_edgar import lookup_cik, get_company_facts, extract_financials, format_financials_for_prompt, get_recent_filings
            from scraper.stock_data import get_stock_data, format_stock_data_for_prompt
            company = args["company"]
            cik_result = lookup_cik(company)
            if not cik_result:
                return (
                    f"No SEC EDGAR data found for '{company}'. "
                    f"This likely means the company is private, foreign-listed, or files under a different entity name. "
                    f"Try searching the web for financial information, or check if the company trades under a different name."
                )
            if isinstance(cik_result, list):
                names = ", ".join(f"{c['company_name']} ({c.get('ticker', 'N/A')})" for c in cik_result[:5])
                return f"Multiple matches found in SEC EDGAR: {names}. Try a more specific name or ticker."
            cik = cik_result["cik"]
            ticker = cik_result.get("ticker", "N/A")
            company_name = cik_result.get("company_name", company)
            facts = get_company_facts(cik)
            if not facts:
                return f"Found {company_name} (CIK: {cik}, ticker: {ticker}) but could not fetch financial data from EDGAR."
            financials = extract_financials(facts)
            filings = get_recent_filings(cik)
            text = format_financials_for_prompt(financials, filings)
            # Append live market data
            stock_data = get_stock_data(ticker)
            if stock_data:
                text += "\n" + format_stock_data_for_prompt(stock_data)
            return f"SEC EDGAR data for {company_name} (ticker: {ticker}, CIK: {cik}):\n\n{text}"

        elif name == "search_patents_raw":
            from scraper.patents import search_patents, format_patents_for_prompt
            company = args["company"]
            max_results = args.get("max_results", 15)
            patents, total, source = search_patents(company, max_results)
            if not patents:
                return f"No patents found for '{company}' in USPTO or Google Patents. The company may file under a different legal entity name, or may not hold US patents."
            text = format_patents_for_prompt(patents, total)
            return f"Patent data via {source} ({total} total):\n\n{text}"

        elif name == "search_financial_news":
            sys.stdout = old_stdout
            old_stdout = None
            query = args["query"]
            news = search_news(f"{query} earnings revenue funding site:reuters.com OR site:bloomberg.com OR site:ft.com OR site:wsj.com OR site:seekingalpha.com", max_results=8)
            web = search_web(f"{query} financials earnings revenue", max_results=5)
            all_results = news + web
            if not all_results:
                return f"No financial news found for '{query}'. Try broadening the search or checking if the company name is correct."
            return format_search_results(all_results)

        # --- Job Intelligence ---
        elif name == "collect":
            new, skipped = collect(args["company"], args.get("url"), db_path)
            return f"Collected {new} new jobs, {skipped} duplicates skipped."

        elif name == "classify":
            count = classify(args["company"], db_path,
                            seniority_framework=args.get("seniority_framework"),
                            custom_seniority_rules=args.get("custom_seniority_rules"),
                            mode=args.get("mode", "comprehensive"))
            mode_label = args.get("mode", "comprehensive")
            return f"Classified {count} jobs ({mode_label} mode)."

        elif name == "reclassify":
            from db import get_connection, get_company_id, clear_classifications
            conn = get_connection(db_path)
            cid = get_company_id(conn, args["company"])
            if not cid:
                conn.close()
                return f"Company '{args['company']}' not found."
            clear_classifications(conn, cid)
            conn.close()
            count = classify(args["company"], db_path,
                            seniority_framework=args.get("seniority_framework"))
            path = analyze(args["company"], db_path)
            summary = f"Reclassified {count} jobs with updated subcategories."
            if path:
                summary += f" Report saved to: {path}"
            return summary

        elif name == "analyze":
            path = analyze(args["company"], db_path)
            if path:
                return f"Strategic intelligence report saved to: {path}"
            return "Analysis failed — no data available. Make sure jobs have been collected and classified first."

        elif name == "hiring_pipeline":
            new, skipped = collect(args["company"], args.get("url"), db_path)
            if new == 0 and skipped == 0:
                return "Pipeline stopped: no jobs collected. Check the company name or provide a direct URL."

            cls_mode = args.get("classification_mode", "comprehensive")
            count = classify(args["company"], db_path,
                            seniority_framework=args.get("seniority_framework"),
                            custom_seniority_rules=args.get("custom_seniority_rules"),
                            mode=cls_mode)
            path = analyze(args["company"], db_path)
            summary = f"Pipeline complete: {new} new jobs collected, {count} classified ({cls_mode} mode)."
            if path:
                summary += f" Report saved to: {path}"
            else:
                summary += " Warning: hiring report generation failed — no classified jobs found or analysis error."
            return summary

        # --- Analysis Reports ---
        elif name == "financial_analysis":
            path = financial_analysis(args["company"])
            if path:
                return f"Financial analysis saved to: {path}"
            return "Financial analysis failed — no data found."

        elif name == "patent_analysis":
            path = patent_analysis(args["company"])
            if path:
                return f"Patent analysis saved to: {path}"
            return "Patent analysis failed — no patent data found."

        elif name == "competitor_analysis":
            path = competitor_analysis(args["company"])
            if path:
                return f"Competitor analysis saved to: {path}"
            return "Competitor analysis failed — no data found."

        elif name == "sentiment_analysis":
            path = sentiment_analysis(args["company"])
            if path:
                return f"Sentiment analysis saved to: {path}"
            return "Sentiment analysis failed — no data found."

        elif name == "seo_audit":
            path = seo_audit(args["url"], args.get("max_pages", 10), company_name=args.get("company_name"))
            if path:
                return f"SEO/AEO audit saved to: {path}"
            return "SEO audit failed — could not crawl the site."

        elif name == "techstack_analysis":
            path = techstack_analysis(args["url"], args.get("max_pages", 5), company_name=args.get("company_name"))
            if path:
                return f"Tech stack analysis saved to: {path}"
            return "Tech stack analysis failed — could not crawl the site."

        elif name == "pricing_analysis":
            path = pricing_analysis(args["url"], company_name=args.get("company_name"))
            if path:
                return f"Pricing analysis saved to: {path}"
            return "Pricing analysis failed — could not crawl the site."

        # --- Multi-Company ---
        elif name == "full_analysis":
            path = company_profile(args["company"], args.get("url"), db_path)
            if path:
                return f"Full analysis saved to: {path}"
            return "Full analysis failed — no analyses completed."

        elif name == "compare_companies":
            path = compare_companies(args["company_a"], args["company_b"])
            if path:
                return f"Comparison report saved to: {path}"
            return "Comparison failed — not enough data."

        elif name == "landscape_analysis":
            path = landscape_analysis(args["company"], args.get("top_n", 3))
            if path:
                return f"Landscape analysis saved to: {path}"
            return "Landscape analysis failed — could not identify competitors."

        # --- Search ---
        elif name == "web_search":
            sys.stdout = old_stdout
            old_stdout = None
            query = args["query"]
            news = search_news(query, max_results=5)
            web = search_web(query, max_results=5)
            all_results = news + web
            return format_search_results(all_results) if all_results else "No results found."

        elif name == "reddit_search":
            sys.stdout = old_stdout
            old_stdout = None
            results = search_reddit(args["query"], max_results=args.get("max_results", 5))
            return format_search_results(results) if results else "No Reddit results found."

        elif name == "reddit_deep_search":
            sys.stdout = old_stdout
            old_stdout = None
            results = search_reddit_rss(
                args["query"],
                max_results=args.get("max_results", 10),
                subreddits=args.get("subreddits"),
                fetch_comments_top_n=3 if args.get("fetch_comments") else 0,
            )
            return format_search_results(results) if results else "No Reddit results found."

        elif name == "hn_search":
            sys.stdout = old_stdout
            old_stdout = None
            results = search_hackernews(
                args["query"],
                max_results=args.get("max_results", 10),
                sort=args.get("sort", "relevance"),
                fetch_comments_top_n=3 if args.get("fetch_comments") else 0,
            )
            return format_search_results(results) if results else "No Hacker News results found."

        elif name == "youtube_search":
            sys.stdout = old_stdout
            old_stdout = None
            results = search_youtube(args["query"], max_results=5)
            if not results:
                return "No YouTube results found."
            output = format_search_results(results)
            if args.get("fetch_transcripts"):
                transcripts = fetch_transcripts_from_search_results(results, max_videos=2)
                if transcripts:
                    output += "\n\n--- TRANSCRIPTS ---\n\n" + format_transcripts_for_prompt(transcripts)
            return output

        elif name == "youtube_transcript":
            sys.stdout = old_stdout
            old_stdout = None
            text, video_id = get_video_transcript(args["url"], max_chars=args.get("max_chars", 6000))
            if text:
                return f"Transcript for video {video_id}:\n\n{text}"
            return f"Could not fetch transcript for {args['url']}. The video may not have captions."

        # --- Database ---
        elif name == "query_db":
            sys.stdout = old_stdout
            old_stdout = None
            return _safe_query_db(args["sql"], db_path)

        # --- Company Dossiers ---
        elif name == "get_dossier":
            sys.stdout = old_stdout
            old_stdout = None
            return _get_dossier_summary(args["company"], db_path)

        elif name == "save_dossier_event":
            sys.stdout = old_stdout
            old_stdout = None
            return _save_dossier_event(args, db_path)

        elif name == "refresh_key_facts":
            from agents.llm import reextract_all_key_facts
            return reextract_all_key_facts(args["company"], db_path)

        elif name == "get_current_datetime":
            from datetime import datetime
            now = datetime.now()
            return now.strftime("Current date and time: %A, %B %d, %Y at %I:%M %p")

        elif name == "generate_briefing":
            from agents.briefing import generate_briefing
            briefing = generate_briefing(args["company"], db_path)
            if briefing:
                dm = briefing.get("digital_maturity", {})
                opps = briefing.get("engagement_opportunities", [])
                summary = f"Intelligence briefing generated for {args['company']}.\n\n"
                summary += f"**Digital Maturity Score:** {dm.get('overall_score', 'N/A')}/100 ({dm.get('overall_label', '')})\n"
                subs = dm.get("sub_scores", {})
                for key, lbl in [("tech_modernity", "Tech Modernity"), ("data_analytics", "Data & Analytics"), ("ai_readiness", "AI Readiness"), ("organizational_readiness", "Org Readiness")]:
                    sub = subs.get(key, {})
                    summary += f"- {lbl}: {sub.get('score', '?')}/100\n"
                summary += f"\n**Engagement Opportunities ({len(opps)}):**\n"
                for opp in opps:
                    summary += f"- [{opp.get('priority', '?').upper()}] {opp.get('service', '?')} — {opp.get('estimated_scope', '?')}\n"
                budget = briefing.get("budget_signals", {})
                if budget:
                    summary += f"\n**Budget Confidence:** {budget.get('confidence', '?')}"
                summary += "\n\nThe briefing is now available in the Dossiers tab."
                return summary
            return "Briefing generation failed — ensure the company has a dossier with at least 2 analyses."

        elif name == "batch_company_analysis":
            # Restore stdout so worker threads don't fight over it
            sys.stdout = old_stdout
            old_stdout = None

            from concurrent.futures import ThreadPoolExecutor, as_completed

            companies = args["companies"][:5]  # Hard cap at 5
            framework = args.get("seniority_framework", "tech")
            depth = args.get("depth", "standard")

            if progress_callback:
                progress_callback(f"Batch analysis ({depth}): {', '.join(companies)}")

            results = {}

            def _run_company(company_name):
                """Run pipeline for a single company in a worker thread."""
                try:
                    result = {}

                    if depth == "full":
                        path = company_profile(company_name, None, db_path)
                        result["profile_report"] = path
                    else:
                        # Hiring pipeline
                        new, skipped = collect(company_name, None, db_path)
                        if new == 0 and skipped == 0:
                            return company_name, {"error": "No jobs found — check company name or provide ATS URL"}
                        # standard depth → fast (heuristic) classification, deep → comprehensive (LLM)
                        cls_mode = "fast" if depth == "standard" else "comprehensive"
                        count = classify(company_name, db_path, seniority_framework=framework, mode=cls_mode)
                        path = analyze(company_name, db_path)
                        result.update({"jobs_new": new, "classified": count, "report": path,
                                       "classification_mode": cls_mode})

                        if depth == "standard":
                            comp_path = competitor_analysis(company_name)
                            result["competitor_report"] = comp_path

                    # Try briefing (needs 2+ analyses)
                    try:
                        from agents.briefing import generate_briefing as _gen_briefing
                        briefing = _gen_briefing(company_name, db_path)
                        dm = briefing.get("digital_maturity", {})
                        result["dm_score"] = dm.get("overall_score", "N/A")
                        result["dm_label"] = dm.get("overall_label", "")
                        subs = dm.get("sub_scores", {})
                        result["sub_scores"] = {k: v.get("score", "?") for k, v in subs.items()}
                    except Exception as e:
                        result["briefing_error"] = str(e)[:120]

                    return company_name, result
                except Exception as e:
                    return company_name, {"error": str(e)[:200]}

            # max_workers=2 to limit SQLite write contention and API rate limits
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = {executor.submit(_run_company, c): c for c in companies}
                for future in as_completed(futures):
                    company_name, result = future.result()
                    results[company_name] = result
                    if progress_callback:
                        if isinstance(result, dict) and isinstance(result.get("dm_score"), (int, float)):
                            progress_callback(f"Done: {company_name} — DM Score {result['dm_score']}/100 ({result['dm_label']})")
                        elif isinstance(result, dict) and result.get("error"):
                            progress_callback(f"Failed: {company_name} — {result['error'][:80]}")
                        else:
                            progress_callback(f"Done: {company_name}")

            # Format summary — sorted by DM score (worst first for "who's behind" queries)
            lines = [f"## Batch Analysis: {len(companies)} Companies ({depth} depth)\n"]

            scored = [(c, r) for c, r in results.items()
                      if isinstance(r, dict) and isinstance(r.get("dm_score"), (int, float))]
            scored.sort(key=lambda x: x[1]["dm_score"])  # ascending = worst first
            unscored = [(c, r) for c, r in results.items() if c not in dict(scored)]

            for company_name, r in scored + unscored:
                if isinstance(r, dict):
                    if isinstance(r.get("dm_score"), (int, float)):
                        lines.append(f"**{company_name}** — {r['dm_score']}/100 ({r['dm_label']})")
                        if r.get("sub_scores"):
                            for k, v in r["sub_scores"].items():
                                lines.append(f"  - {k.replace('_', ' ').title()}: {v}/100")
                    elif r.get("error"):
                        lines.append(f"**{company_name}** — ERROR: {r['error']}")
                    else:
                        lines.append(f"**{company_name}** — Analysis complete")

                    if r.get("jobs_new"):
                        lines.append(f"  Jobs: {r['jobs_new']} collected, {r.get('classified', 0)} classified")
                    if r.get("briefing_error"):
                        lines.append(f"  Briefing: {r['briefing_error']}")
                    reports = [v for k, v in r.items() if (k.endswith("_report") or k == "report") and v]
                    if reports:
                        lines.append(f"  Reports: {', '.join(str(p) for p in reports)}")
                else:
                    lines.append(f"**{company_name}** — {r}")
                lines.append("")

            return "\n".join(lines)

        else:
            return f"Unknown tool: {name}"

    except Exception as e:
        return f"Tool error: {e}"

    finally:
        if old_stdout is not None:
            sys.stdout = old_stdout
        _stdout_lock.release()
        if progress_callback:
            capture.flush()
        else:
            progress = capture.getvalue()
            if progress:
                print(progress, end="")


def chat_repl(db_path="intel.db"):
    """Interactive chat loop with tool-calling support."""
    init_db(db_path)

    print("=" * 60)
    print("  Signal Vault Chat")
    print("  Type a question or command. 'exit' to quit.")
    print("=" * 60)
    print()

    llm = ChatLLM()
    history = [{"role": "system", "content": SYSTEM_PROMPT}]

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit", "q"):
            print("Goodbye!")
            break

        history.append({"role": "user", "content": user_input})

        # Tool-calling loop: LLM may request multiple rounds of tool calls
        while True:
            try:
                response = llm.chat(history, tools=TOOL_SCHEMAS)
            except RuntimeError as e:
                error_msg = str(e).lower()
                if any(kw in error_msg for kw in ["token", "context", "length", "too long", "too large", "maximum", "reduce"]):
                    history = [history[0]] + history[-4:]
                    try:
                        response = llm.chat(history, tools=TOOL_SCHEMAS)
                    except RuntimeError:
                        print("\nAssistant: Sorry, I hit a temporary issue. Please try again.\n")
                        break
                elif "rate limit" in error_msg or "429" in error_msg:
                    print("\nAssistant: I'm being rate limited right now. Please wait a moment and try again.\n")
                    break
                else:
                    print("\nAssistant: Sorry, I hit a temporary issue. Please try again.\n")
                    break

            tool_calls = response.get("tool_calls")

            if tool_calls:
                # Stream thinking content if the LLM included reasoning alongside tool calls
                thinking_text = response.get("content", "")
                if thinking_text and thinking_text.strip():
                    print(f"\n[thinking] {thinking_text}")

                history.append(response)

                for tc in tool_calls:
                    fn_name = tc["function"]["name"]
                    fn_args = json.loads(tc["function"]["arguments"]) if isinstance(tc["function"]["arguments"], str) else tc["function"]["arguments"]

                    if fn_name == "think":
                        print(f"\n[thinking] {fn_args.get('reasoning', '')}")
                        history.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": "Thinking noted.",
                        })
                        continue

                    print(f"\n[calling {fn_name}({', '.join(f'{k}={v!r}' for k, v in fn_args.items())})]")

                    result = _execute_tool(fn_name, fn_args, db_path)

                    if len(result) > MAX_TOOL_RESULT_CHARS:
                        result = result[:MAX_TOOL_RESULT_CHARS] + f"\n\n... (truncated — {len(result)} chars total)"

                    history.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result,
                    })

                continue

            else:
                text = response.get("content", "")
                print(f"\nAssistant: {text}\n")
                history.append({"role": "assistant", "content": text})
                break

        # Trim history to avoid context overflow
        if len(history) > MAX_HISTORY + 1:
            history = [history[0]] + history[-(MAX_HISTORY):]
