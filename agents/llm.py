"""Shared LLM provider rotation for report generation agents."""

import os
import json
import time
import threading
from collections import OrderedDict
from pathlib import Path

import httpx
import google.generativeai as genai

import re
from datetime import datetime, timezone

# Lock for genai.configure() which sets global state — prevents races between threads
gemini_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Key health tracking — skip keys that are rate-limited or quota-exhausted
# ---------------------------------------------------------------------------
_key_health = {}          # (provider, key_hint) -> expiry (time.monotonic)
_health_lock = threading.Lock()

_COOLDOWN_QUOTA = 3600    # 60 min — daily quota exhaustion
_COOLDOWN_RATE = 60       # 60 sec — per-minute rate limits
_COOLDOWN_ERROR = 120     # 2 min  — generic server errors


def _key_hint(key):
    """Last 4 chars of key for health tracking and logging."""
    return key[-4:] if len(key) >= 4 else "****"


def mark_key_unhealthy(provider, key, error_str):
    """Record a key failure with appropriate cooldown duration."""
    hint = _key_hint(key)
    err_lower = error_str.lower()

    if "quota" in err_lower or "exceeded" in err_lower or "resource_exhausted" in err_lower:
        cooldown = _COOLDOWN_QUOTA
        reason = "quota"
    elif "429" in error_str or "rate limit" in err_lower or "rate_limit" in err_lower:
        cooldown = _COOLDOWN_RATE
        reason = "rate"
    else:
        cooldown = _COOLDOWN_ERROR
        reason = "error"

    expiry = time.monotonic() + cooldown
    with _health_lock:
        _key_health[(provider, hint)] = expiry
    print(f"[health] {provider} key ...{hint} cooled down {cooldown}s ({reason})")


def is_key_healthy(provider, key):
    """Check if a key is currently healthy (not in cooldown)."""
    hint = _key_hint(key)
    with _health_lock:
        expiry = _key_health.get((provider, hint))
    if expiry is None:
        return True
    if time.monotonic() >= expiry:
        with _health_lock:
            _key_health.pop((provider, hint), None)
        return True
    return False


def get_health_status():
    """Return current health dict for diagnostics."""
    now = time.monotonic()
    with _health_lock:
        return {
            f"{p}...{h}": {"remaining_s": round(exp - now)}
            for (p, h), exp in _key_health.items()
            if exp > now
        }

from db import (get_connection, get_or_create_dossier, add_dossier_analysis,
                add_dossier_event, get_previous_key_facts, log_llm_call)


# Provider definitions — models and endpoints per provider (ordered by capability)
PROVIDER_DEFS = OrderedDict([
    ("groq", {
        "env_key": "GROQ_API_KEY",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "models": [
            "openai/gpt-oss-120b",
            "llama-3.3-70b-versatile",
            "meta-llama/llama-4-scout-17b-16e-instruct",
            "qwen/qwen3-32b",
            "openai/gpt-oss-20b",
            "moonshotai/kimi-k2-instruct-0905",
            "llama-3.1-8b-instant",
            "compound-beta",
            "compound-beta-mini",
        ],
    }),
    ("cerebras", {
        "env_key": "CEREBRAS_API_KEY",
        "url": "https://api.cerebras.ai/v1/chat/completions",
        "models": [
            "qwen-3-235b-a22b-instruct-2507",
            "gpt-oss-120b",
            "zai-glm-4.7",
            "llama3.1-8b",
        ],
    }),
    ("mistral", {
        "env_key": "MISTRAL_API_KEY",
        "url": "https://api.mistral.ai/v1/chat/completions",
        "models": [
            "mistral-large-latest",
            "mistral-medium-latest",
            "mistral-small-latest",
            "magistral-medium-latest",
            "magistral-small-latest",
            "ministral-14b-latest",
            "ministral-8b-latest",
            "open-mistral-nemo",
        ],
    }),
    ("gemini", {
        "env_key": "GEMINI_API_KEYS",
        "url": None,
        "models": [
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
            "gemini-3-flash-preview",
            "gemini-3.1-flash-lite-preview",
        ],
    }),
    ("openrouter", {
        "env_key": "OPENROUTER_API_KEY",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "models": [
            "nousresearch/hermes-3-llama-3.1-405b:free",
            "nvidia/nemotron-3-super-120b-a12b:free",
            "openai/gpt-oss-120b:free",
            "qwen/qwen3-next-80b-a3b-instruct:free",
            "meta-llama/llama-3.3-70b-instruct:free",
            "arcee-ai/trinity-large-preview:free",
            "nvidia/nemotron-3-nano-30b-a3b:free",
            "google/gemma-3-27b-it:free",
            "z-ai/glm-4.5-air:free",
            "mistralai/mistral-small-3.1-24b-instruct:free",
            "cognitivecomputations/dolphin-mistral-24b-venice-edition:free",
            "openai/gpt-oss-20b:free",
            "minimax/minimax-m2.5:free",
            "stepfun/step-3.5-flash:free",
            "arcee-ai/trinity-mini:free",
            "google/gemma-3-12b-it:free",
            "nvidia/nemotron-nano-9b-v2:free",
            "qwen/qwen3-coder:free",
        ],
    }),
])

# Provider rotation order for regular analyses (saves Gemini quota for briefings)
REPORT_CHAIN = ["groq", "cerebras", "mistral", "gemini", "openrouter"]

# Gemini-first for intelligence briefings (best structured JSON output)
BRIEFING_CHAIN = ["gemini", "groq", "cerebras", "mistral", "openrouter"]

# Lightweight chain for classification, extraction, summarization — small/fast models only
FAST_CHAIN = {
    "order": ["groq", "cerebras", "mistral", "gemini", "openrouter"],
    "models": {
        "groq": [
            "llama-3.1-8b-instant",
            "openai/gpt-oss-20b",
            "compound-beta-mini",
        ],
        "cerebras": [
            "llama3.1-8b",
        ],
        "mistral": [
            "ministral-8b-latest",
            "ministral-14b-latest",
            "open-mistral-nemo",
            "mistral-small-latest",
        ],
        "gemini": [
            "gemini-2.5-flash-lite",
            "gemini-3.1-flash-lite-preview",
        ],
        "openrouter": [
            "nvidia/nemotron-nano-9b-v2:free",
            "google/gemma-3-12b-it:free",
            "arcee-ai/trinity-mini:free",
            "qwen/qwen3-coder:free",
        ],
    },
}

# CHEAP_CHAIN: no Gemini — for low-value calls (labels, classification, summaries)
CHEAP_CHAIN = {
    "order": ["groq", "cerebras", "mistral", "openrouter"],
    "models": {
        "groq": ["llama-3.1-8b-instant"],
        "cerebras": ["llama3.1-8b"],
        "mistral": ["ministral-8b-latest"],
        "openrouter": [
            "nvidia/nemotron-nano-9b-v2:free",
            "google/gemma-3-12b-it:free",
        ],
    },
}


def _expand_chain(chain):
    """Expand a chain into a flat provider list with per-provider key exhaustion.

    For each provider in chain order, generates all (key, model) combinations
    before moving to the next provider.  Within a provider, keys are
    interleaved per model so a rate-limited key is skipped quickly:
        provider1/model0/key0, provider1/model0/key1, provider1/model1/key0, ...
        provider2/model0/key0, ...

    Accepts either:
        - list of provider names (uses all models from PROVIDER_DEFS)
        - dict with "order" (provider names) and "models" (per-provider model subset)
    """
    if isinstance(chain, dict):
        order = chain["order"]
        model_override = chain.get("models", {})
    else:
        order = chain
        model_override = {}

    expanded = []
    for name in order:
        defn = PROVIDER_DEFS.get(name)
        if not defn:
            continue
        raw = os.environ.get(defn["env_key"], "").strip()
        if not raw:
            continue
        keys = [k.strip() for k in raw.split(",") if k.strip()]
        if not keys:
            continue

        models = model_override.get(name, defn["models"])
        # For each model, try all keys before moving to next model
        for model in models:
            for key in keys:
                expanded.append({
                    "name": name,
                    "url": defn["url"],
                    "model": model,
                    "_key": key,
                })

    return expanded


def unique_report_path(reports_dir, base_name):
    """Return a unique report filepath, adding a sequence suffix if needed.

    E.g. huel_financial_2026-03-24.md → huel_financial_2026-03-24_2.md if the
    base already exists.
    """
    reports_dir = Path(reports_dir)
    candidate = reports_dir / base_name
    if not candidate.exists():
        return candidate
    stem = candidate.stem   # e.g. "huel_financial_2026-03-24"
    suffix = candidate.suffix  # ".md"
    seq = 2
    while True:
        candidate = reports_dir / f"{stem}_{seq}{suffix}"
        if not candidate.exists():
            return candidate
        seq += 1


def normalize_citations(text):
    """Fix malformed LLM citation formats into standard markdown links.

    Handles three classes of malformed citations:
    1. Fullwidth brackets: 【¹†url】 or 【¹ url】
    2. Dagger/space inside brackets: [¹†url] or [¹ url]
    3. Reference-style orphans: [¹] with a numbered Sources section at the
       bottom like "1. [Title](url)" — reconnects markers to their URLs.
    """
    # --- Class 1: fullwidth brackets ---
    text = re.sub(
        r'【([¹²³⁴⁵⁶⁷⁸⁹⁰\d]+)[†⁺+\s]+(https?://[^\s】]+?)】',
        r'[\1](\2)',
        text
    )
    # --- Class 2: dagger, plus, or space inside standard brackets ---
    text = re.sub(
        r'\[([¹²³⁴⁵⁶⁷⁸⁹⁰\d]+)[†⁺+\s]+(https?://[^\s\]]+?)\]',
        r'[\1](\2)',
        text
    )

    # --- Class 3: reference-style orphans ---
    # Parse the Sources/References section to build number → URL map.
    SUPER_DIGITS = {'¹': '1', '²': '2', '³': '3', '⁴': '4', '⁵': '5',
                    '⁶': '6', '⁷': '7', '⁸': '8', '⁹': '9', '⁰': '0'}
    DIGIT_SUPERS = {v: k for k, v in SUPER_DIGITS.items()}

    # Isolate the Sources section to safely scrape loose markdown URL formats
    sources_text = text
    lower_text = text.lower()
    for header in ["## sources", "## references", "# sources", "sources:", "sources\n"]:
        if header in lower_text:
            idx = lower_text.rfind(header)
            sources_text = text[idx:]
            break

    source_map = {}  # "1" → url
    # MATCH OPTIONS:
    # "1. [Title](url)"
    # "* 1. https://..."
    # "- [1] Title - https://..."
    for m in re.finditer(r'^[^\S\r\n]*(?:[-*]\s+)?(?:\[?(\d+)\]?\.?)\s+.*?(https?://[^\s)\]\'"<>]+)', sources_text, re.MULTILINE):
        source_map[m.group(1)] = m.group(2)

    if source_map:
        # Replaces orphan superscripts like [¹] OR naked superscripts like ¹
        # As long as they are not currently followed by a (url...
        def _replace_orphan(match):
            superscript = match.group(1)
            # Convert superscript to digit
            digit = ''.join(SUPER_DIGITS.get(c, c) for c in superscript)
            url = source_map.get(digit)
            if url:
                return f'[{superscript}]({url})'
            return match.group(0)  # leave unchanged if no source found

        # Match [¹] or just ¹ not followed by (
        text = re.sub(r'\[?([¹²³⁴⁵⁶⁷⁸⁹⁰]+)\]?(?!\()', _replace_orphan, text)

    return text


def generate_text(prompt, timeout=60, chain=None, caller=None, json_mode=False):
    """Try providers in order until one works. Returns (text, model_name).

    Per-provider key exhaustion: all keys × models per provider, then next provider.
    If json_mode=True, hints providers to return valid JSON
    (Gemini response_mime_type, OpenAI-compat response_format).
    """
    # Auto-detect caller from stack if not provided
    if not caller:
        import inspect
        frame = inspect.currentframe().f_back
        caller = f"{Path(frame.f_code.co_filename).stem}:{frame.f_code.co_name}" if frame else "unknown"

    import time as _time
    expanded = _expand_chain(chain or REPORT_CHAIN)
    http = httpx.Client(timeout=timeout, follow_redirects=True)

    skipped_unhealthy = 0
    skip_providers = set()  # [C] Skip entire provider after prompt-size errors (413)

    for p in expanded:
        key = p["_key"]
        provider = p["name"]
        model_id = f"{provider}/{p['model']}"
        key_hint = key[-4:] if len(key) >= 4 else '****'
        _t0 = _time.time()  # latency tracking

        # [C] Skip providers known to reject this prompt size
        if provider in skip_providers:
            continue

        # Skip keys in cooldown
        if not is_key_healthy(provider, key):
            skipped_unhealthy += 1
            continue

        try:
            if provider == "gemini":
                with gemini_lock:
                    genai.configure(api_key=key)
                    model = genai.GenerativeModel(p["model"])
                    gen_config = {"response_mime_type": "application/json"} if json_mode else None
                    response = model.generate_content(prompt, generation_config=gen_config)
                http.close()
                # Extract token counts from Gemini response
                in_tok = out_tok = None
                try:
                    um = response.usage_metadata
                    in_tok = um.prompt_token_count
                    out_tok = um.candidates_token_count
                except Exception:
                    pass
                _dur = int((_time.time() - _t0) * 1000)
                print(f"[llm] ✓ {model_id} (key …{key_hint}) {_dur}ms" + (f" [{in_tok}→{out_tok} tok]" if in_tok else ""))
                log_llm_call(provider, p["model"], key_hint, "success", caller=caller, input_tokens=in_tok, output_tokens=out_tok, duration_ms=_dur)
                result_text = response.text if not json_mode else response.text
                return (normalize_citations(result_text) if not json_mode else result_text), model_id
            else:
                headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
                body = {"model": p["model"], "messages": [{"role": "user", "content": prompt}], "temperature": 0.3}
                if json_mode:
                    body["response_format"] = {"type": "json_object"}
                resp = http.post(p["url"], json=body, headers=headers)
                if resp.status_code == 200:
                    resp_json = resp.json()
                    text = resp_json["choices"][0]["message"]["content"]
                    # Extract token counts from OpenAI-compatible response
                    in_tok = out_tok = None
                    usage = resp_json.get("usage")
                    if usage:
                        in_tok = usage.get("prompt_tokens")
                        out_tok = usage.get("completion_tokens")
                    http.close()
                    _dur = int((_time.time() - _t0) * 1000)
                    print(f"[llm] ✓ {model_id} (key …{key_hint}) {_dur}ms" + (f" [{in_tok}→{out_tok} tok]" if in_tok else ""))
                    log_llm_call(provider, p["model"], key_hint, "success", caller=caller, input_tokens=in_tok, output_tokens=out_tok, duration_ms=_dur)
                    return (normalize_citations(text) if not json_mode else text), model_id
                elif resp.status_code == 429:
                    _dur = int((_time.time() - _t0) * 1000)
                    print(f"[llm] {model_id} (key …{key_hint}) rate limited {_dur}ms — trying next key")
                    log_llm_call(provider, p["model"], key_hint, "rate_limited", error="429", caller=caller, duration_ms=_dur)
                    mark_key_unhealthy(provider, key, "429")
                    continue
                elif resp.status_code == 413:
                    # [C] Prompt too large for this provider — skip ALL remaining entries for it
                    print(f"[llm] {model_id} prompt too large (413) — skipping all {provider} models")
                    log_llm_call(provider, p["model"], key_hint, "error", error="413 prompt too large", caller=caller)
                    skip_providers.add(provider)
                    continue
                else:
                    err = f"HTTP {resp.status_code}"
                    print(f"[llm] {model_id} (key …{key_hint}) failed: {err}")
                    log_llm_call(provider, p["model"], key_hint, "error", error=err, caller=caller)
                    continue
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "quota" in err_str.lower() or "rate" in err_str.lower():
                print(f"[llm] {model_id} (key …{key_hint}) rate limited — trying next key")
                log_llm_call(provider, p["model"], key_hint, "rate_limited", error=err_str[:200], caller=caller)
                mark_key_unhealthy(provider, key, err_str)
            elif provider == "gemini" and ("400" in err_str or "schema" in err_str.lower() or "constraint" in err_str.lower() or "RepeatedComposite" in err_str or "thought_signature" in err_str):
                # [B] Gemini schema error in structured output mode — retry without json_mode
                print(f"[llm] {model_id} (key …{key_hint}) schema rejected — retrying as plain text")
                log_llm_call(provider, p["model"], key_hint, "error", error=f"schema_fallback: {err_str[:150]}", caller=caller)
                try:
                    with gemini_lock:
                        genai.configure(api_key=key)
                        model = genai.GenerativeModel(p["model"])
                        response = model.generate_content(prompt)
                    in_tok = out_tok = None
                    try:
                        um = response.usage_metadata
                        in_tok = um.prompt_token_count
                        out_tok = um.candidates_token_count
                    except Exception:
                        pass
                    _dur = int((_time.time() - _t0) * 1000)
                    print(f"[llm] ✓ {model_id} (key …{key_hint}) [schema fallback] {_dur}ms" + (f" [{in_tok}→{out_tok} tok]" if in_tok else ""))
                    log_llm_call(provider, p["model"], key_hint, "success", caller=caller, input_tokens=in_tok, output_tokens=out_tok, duration_ms=_dur)
                    return response.text, model_id
                except Exception as retry_e:
                    retry_err = str(retry_e)
                    if "429" in retry_err or "quota" in retry_err.lower():
                        log_llm_call(provider, p["model"], key_hint, "rate_limited", error=retry_err[:200], caller=caller)
                        mark_key_unhealthy(provider, key, retry_err)
                    else:
                        log_llm_call(provider, p["model"], key_hint, "error", error=f"schema_fallback_failed: {retry_err[:150]}", caller=caller)
            elif "413" in err_str or "too large" in err_str.lower() or "content length" in err_str.lower():
                # [C] Prompt too large via exception — skip provider
                print(f"[llm] {model_id} prompt too large — skipping all {provider} models")
                log_llm_call(provider, p["model"], key_hint, "error", error="413 prompt too large", caller=caller)
                skip_providers.add(provider)
            else:
                print(f"[llm] {model_id} (key …{key_hint}) failed: {e}")
                log_llm_call(provider, p["model"], key_hint, "error", error=err_str[:200], caller=caller)
            continue

    http.close()
    if skipped_unhealthy:
        print(f"[llm] Skipped {skipped_unhealthy} entries due to key cooldowns")
    if skip_providers:
        print(f"[llm] Skipped providers due to prompt size: {', '.join(skip_providers)}")
    raise RuntimeError("All LLM providers failed for text generation")


def _extract_json(text):
    """Extract JSON from LLM response, handling markdown fences and surrounding text.

    Returns parsed dict/list, or None if no valid JSON found.
    """
    text = text.strip()

    # Strip markdown code fences
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()
    if text.startswith("json"):
        text = text[4:].strip()

    # Try direct parse first (fast path)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Find the outermost JSON object {...} or array [...] in the response
    for start_char, end_char in (("{", "}"), ("[", "]")):
        start = text.find(start_char)
        if start == -1:
            continue
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            c = text[i]
            if escape:
                escape = False
                continue
            if c == "\\":
                escape = True
                continue
            if c == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if c == start_char:
                depth += 1
            elif c == end_char:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
    return None


def generate_json(prompt, timeout=60, chain=None):
    """Generate text and parse as JSON. Retries on parse failure.

    Returns parsed dict/list or None.
    """
    # Attempt 1: generation with json_mode hint
    try:
        text, model = generate_text(prompt, timeout=timeout, chain=chain, json_mode=True)
    except RuntimeError as e:
        print(f"[llm] JSON generation failed — all providers down: {e}")
        return None

    result = _extract_json(text)
    if result is not None:
        return result

    # Parse failed — log and retry with stricter instruction
    print(f"[llm] {model} returned non-JSON ({len(text)} chars), retrying with stricter prompt...")
    print(f"[llm] Response preview: {text[:150]}...")

    try:
        retry_prompt = prompt + "\n\nCRITICAL: Return ONLY valid JSON. No explanation, no markdown fences, no text before or after the JSON object."
        text2, model2 = generate_text(retry_prompt, timeout=timeout, chain=chain, json_mode=True)
    except RuntimeError:
        print(f"[llm] Retry also failed — all providers exhausted")
        return None

    result = _extract_json(text2)
    if result is not None:
        return result

    print(f"[llm] Retry from {model2} also non-JSON: {text2[:150]}...")
    return None


# --- Dossier integration ---

_KEY_FACTS_PROMPT = """Extract structured key facts from this competitive intelligence report about {company}.

Return a JSON object with ONLY the fields you can find evidence for. Do not guess or infer. Use null for missing values.

Fields to extract:
- "revenue": latest annual revenue as string (e.g. "$50B")
- "market_cap": market cap as string (e.g. "$2.8T")
- "headcount": approximate employee count as integer
- "founded": founding year as integer
- "hq_location": headquarters city/state/country
- "ceo": current CEO name
- "sector": industry sector
- "key_products": array of top 3-5 products/services
- "key_competitors": array of top 3-5 competitors
- "key_risks": array of top 3 business risks
- "patent_count": total patents as integer
- "top_patent_areas": array of top 3-5 patent technology areas
- "sentiment_score": employee sentiment (positive/mixed/negative)
- "hiring_trend": hiring trend (growing/stable/shrinking)
- "notable_events": array of max 3 recent strategic events (each: {{"title": "...", "date": "...", "type": "..."}})

Report:
{report_text}

Return ONLY valid JSON, no explanation."""

# Type-specific key facts prompts for richer structured data
_TECHSTACK_FACTS_PROMPT = """Extract structured tech stack facts from this report about {company}.

Return a JSON object with ONLY the fields you can find evidence for. Use null for missing values.

Fields to extract:
- "frontend_framework": primary frontend framework name (e.g. "React", "Next.js", "Vue.js") or null
- "css_framework": CSS framework name (e.g. "Tailwind", "Bootstrap") or null
- "analytics_tools": array of analytics/tracking tools detected (e.g. ["Google Analytics", "Segment", "Mixpanel"])
- "marketing_tools": array of marketing/CRM tools detected (e.g. ["HubSpot", "Marketo", "Intercom"])
- "cdn_hosting": array of CDN/hosting providers detected (e.g. ["Cloudflare", "AWS CloudFront", "Vercel"])
- "cms": CMS platform if any (e.g. "WordPress", "Contentful") or null
- "monitoring_tools": array of performance/error monitoring tools (e.g. ["Sentry", "Datadog", "New Relic"])
- "ab_testing_tools": array of A/B testing / experimentation tools (e.g. ["Optimizely", "LaunchDarkly"])
- "auth_provider": authentication provider if any (e.g. "Auth0", "Okta") or null
- "search_provider": search infrastructure if any (e.g. "Algolia") or null
- "payment_provider": payment processor if any (e.g. "Stripe", "PayPal") or null
- "infrastructure_provider": primary cloud/hosting (e.g. "AWS", "Google Cloud", "Vercel") or null
- "total_technologies_detected": integer count of all technologies found
- "tech_modernity_signals": array of 2-3 short observations about whether the stack is modern, legacy, or mixed
- "backend_languages": array of backend programming languages from hiring data (e.g. ["Python", "Go", "Java"]) or null
- "databases": array of database technologies from hiring data (e.g. ["PostgreSQL", "Redis", "MongoDB"]) or null
- "cloud_platform": primary cloud platform from hiring data (e.g. "AWS", "GCP", "Azure") or null
- "devops_tools": array of DevOps/infrastructure tools from hiring data (e.g. ["Kubernetes", "Terraform", "Docker"]) or null
- "data_stack": array of data engineering tools from hiring data (e.g. ["Spark", "Airflow", "Snowflake", "dbt"]) or null
- "ai_ml_frameworks": array of AI/ML frameworks from hiring data (e.g. ["PyTorch", "TensorFlow", "LangChain"]) or null
- "hiring_data_available": boolean — true if the report includes hiring-derived technology signals, false otherwise

Report:
{report_text}

Return ONLY valid JSON, no explanation."""

_SEO_FACTS_PROMPT = """Extract structured SEO/AEO facts from this audit report about {company}.

Return a JSON object with ONLY the fields you can find evidence for. Use null for missing values.

Fields to extract:
- "seo_title_optimization_pct": integer 0-100 (percentage of pages with properly optimized title tags)
- "seo_meta_desc_pct": integer 0-100 (percentage of pages with optimized meta descriptions)
- "seo_heading_hierarchy_pct": integer 0-100 (percentage of pages with proper heading hierarchy)
- "seo_schema_types": array of schema.org types found (e.g. ["Organization", "Product", "FAQPage"])
- "seo_has_faq_schema": boolean — true if FAQ schema markup was found
- "seo_has_article_schema": boolean — true if Article schema was found
- "aeo_readiness_signals": array of 2-3 short observations about AI answer engine readiness
- "seo_overall_assessment": "strong" or "moderate" or "weak"
- "pages_analyzed": integer count of pages audited

Report:
{report_text}

Return ONLY valid JSON, no explanation."""

_PRICING_FACTS_PROMPT = """Extract structured pricing facts from this analysis report about {company}.

Return a JSON object with ONLY the fields you can find evidence for. Use null for missing values.

Fields to extract:
- "pricing_model": one of "freemium", "subscription", "usage_based", "enterprise_only", "contact_sales", "hybrid", "unknown"
- "pricing_tiers": array of tier/plan names (e.g. ["Free", "Pro", "Enterprise"])
- "price_range": string describing visible price range (e.g. "$0-$500/mo", "Contact Sales", "$99-$999/mo")
- "has_public_pricing": boolean — true if specific prices are publicly listed
- "has_free_tier": boolean — true if a free plan or trial is offered
- "target_segment": one of "SMB", "Mid-Market", "Enterprise", "All Segments"

Report:
{report_text}

Return ONLY valid JSON, no explanation."""

_HIRING_FACTS_PROMPT = """Extract structured hiring intelligence from this competitive hiring analysis report about {company}.

Return a JSON object with ONLY the fields you can find evidence for. Use null for missing values.

Fields to extract:
- "total_open_roles": integer count of open positions analyzed
- "engineering_ratio": string percentage of roles in Engineering (e.g. "67%")
- "ai_ml_ratio": string percentage of engineering roles in AI/ML specifically (e.g. "12% of engineering")
- "top_departments": array of top 3-5 departments with counts (e.g. ["Engineering (67%)", "Data (19%)", "Product (10%)"])
- "top_subcategories": array of top 5-8 subcategories with counts (e.g. ["AI/ML (15)", "Platform/Infrastructure (8)"])
- "seniority_skew": string describing the distribution (e.g. "senior-heavy (43% Senior+)" or "mid-heavy (55% Mid-level)")
- "growth_signal": string percentage of likely new roles (e.g. "67% likely new roles")
- "top_strategic_tags": array of most common strategic tags (e.g. ["AI/ML Investment", "Platform Migration"])
- "hiring_trend": one of "growing", "stable", "shrinking"
- "notable_shifts": string describing any noteworthy patterns (e.g. "Heavy PhD-required AI roles suggest research expansion")
- "top_skills": array of top 10 most demanded skills/technologies
- "primary_locations": array of top 3-5 hiring locations

Report:
{report_text}

Return ONLY valid JSON, no explanation."""

_SENTIMENT_FACTS_PROMPT = """Extract structured employee sentiment facts from this analysis report about {company}.

Return a JSON object with ONLY the fields you can find evidence for. Use null for missing values.

Fields to extract:
- "overall_sentiment": one of "positive", "mixed", "negative"
- "glassdoor_rating": number (e.g. 4.2) or null
- "recommend_to_friend_pct": string percentage (e.g. "78%") or null
- "approve_of_ceo_pct": string percentage (e.g. "92%") or null
- "top_pros": array of top 3-5 employee pros/positives (short phrases)
- "top_cons": array of top 3-5 employee cons/negatives (short phrases)
- "culture_themes": array of 3-5 recurring culture themes (e.g. "mission-driven", "fast-paced", "work-life balance concerns")
- "notable_concerns": array of 2-3 notable employee concerns or red flags
- "sentiment_trend": one of "improving", "stable", "declining" or null

Report:
{report_text}

Return ONLY valid JSON, no explanation."""

_FINANCIAL_FACTS_PROMPT = """Extract structured financial facts from this analysis report about {company}.

Return a JSON object with ONLY the fields you can find evidence for. Use null for missing values.

Fields to extract:
- "revenue": latest annual revenue as string (e.g. "$50B")
- "revenue_growth": year-over-year revenue growth as string (e.g. "+23%") or null
- "market_cap": market cap as string (e.g. "$2.8T") or null
- "valuation": private valuation as string (e.g. "$380B") or null if public
- "headcount": approximate employee count as integer
- "profitability": one of "profitable", "near-breakeven", "unprofitable", "unknown"
- "cash_position": string describing cash/liquidity (e.g. "$12B cash on hand") or null
- "recent_funding": string describing latest funding round (e.g. "Series E, $4B at $380B valuation") or null
- "key_financial_risks": array of top 3 financial risks
- "financial_health": one of "strong", "moderate", "weak", "unknown"
- "aum": assets under management as string (e.g. "$1.5T") or null — for asset managers, PE firms, hedge funds, wealth managers
- "aum_growth": AUM growth as string (e.g. "+12%") or null
- "fee_structure": fee structure as string (e.g. "2% mgmt + 20% performance") or null
- "fund_strategy": investment strategy as string (e.g. "Multi-strategy hedge fund") or null
- "is_financial_services": true if the company is a bank, asset manager, insurer, PE/VC firm, hedge fund, or other financial services firm; false otherwise

Report:
{report_text}

Return ONLY valid JSON, no explanation."""

_COMPETITORS_FACTS_PROMPT = """Extract structured competitive landscape facts from this analysis report about {company}.

Return a JSON object with ONLY the fields you can find evidence for. Use null for missing values.

Fields to extract:
- "key_competitors": array of top 3-5 direct competitors
- "market_position": one of "leader", "challenger", "niche", "emerging"
- "competitive_advantages": array of 3-5 key competitive strengths
- "competitive_weaknesses": array of 2-3 key competitive vulnerabilities
- "market_share": string estimate if available (e.g. "~15% of enterprise AI market") or null
- "competitive_moat": string describing primary defensibility (e.g. "distribution + enterprise relationships") or null
- "threat_level": one of "high", "medium", "low" — how threatened is this company by competitors

Report:
{report_text}

Return ONLY valid JSON, no explanation."""

_PATENTS_FACTS_PROMPT = """Extract structured patent/IP facts from this analysis report about {company}.

Return a JSON object with ONLY the fields you can find evidence for. Use null for missing values.

Fields to extract:
- "total_patents": integer count of patents found
- "recent_patents": integer count of patents filed in last 2 years or null
- "top_patent_areas": array of top 3-5 technology areas with patent counts (e.g. ["Machine Learning (12)", "NLP (8)", "Computer Vision (5)"])
- "ai_ml_patents": integer count of AI/ML related patents or null
- "patent_trend": one of "accelerating", "steady", "declining" or null
- "notable_patents": array of 2-3 notable or strategically significant patents (short descriptions)
- "rd_intensity": one of "very high", "high", "moderate", "low" — overall R&D/innovation intensity

Report:
{report_text}

Return ONLY valid JSON, no explanation."""

_PROFILE_FACTS_PROMPT = """Extract structured company profile facts from this analysis report about {company}.

Return a JSON object with ONLY the fields you can find evidence for. Use null for missing values.

Fields to extract:
- "hq_location": headquarters city/state/country
- "ceo": current CEO name
- "founded": founding year as integer
- "sector": industry sector
- "headcount": approximate employee count as integer
- "revenue": latest annual revenue as string (e.g. "$50B")
- "market_cap": market cap as string (e.g. "$2.8T") or null
- "key_products": array of top 3-5 products/services
- "key_competitors": array of top 3-5 competitors
- "business_model": string describing how they make money (1 sentence)
- "key_risks": array of top 3 business risks

Report:
{report_text}

Return ONLY valid JSON, no explanation."""

_UA_FIT_FACTS_PROMPT = """Extract structured ICP fit scoring facts from this analysis report about {company}.

Return a JSON object with ONLY the fields you can find evidence for. Use null for missing values.

Fields to extract:
- "ua_fit_score": overall ICP fit score as integer (0-100)
- "ua_fit_label": one of "Prime Prospect", "Strong Candidate", "Possible Fit", "Weak Fit", "Not a Fit"
- "channel_saturation_score": integer (0-100)
- "growth_posture_score": integer (0-100)
- "creative_readiness_score": integer (0-100)
- "size_budget_fit_score": integer (0-100)
- "intent_signals_score": integer (0-100)
- "primary_ad_channels": array of advertising channels they use (e.g. ["Meta", "TikTok", "Google Ads"])
- "ecom_platform": ecommerce platform if detected (e.g. "Shopify", "BigCommerce") or null
- "recent_funding": string describing latest funding round or null
- "estimated_revenue": string estimate if mentioned (e.g. "$50M") or null
- "estimated_employees": string estimate if mentioned or null
- "recommended_angle": the recommended sales approach in 1 sentence
- "key_risk": the single biggest risk or objection for this prospect

Report:
{report_text}

Return ONLY valid JSON, no explanation."""

_BRAND_AD_FACTS_PROMPT = """Extract structured brand & advertising intelligence facts from this analysis report about {company}.

Return a JSON object with ONLY the fields you can find evidence for. Use null for missing values.

Fields to extract:
- "active_ad_channels": array of confirmed advertising channels (e.g. ["Meta/Instagram", "Google Ads", "CTV/Streaming", "Linear TV", "Podcast"])
- "recent_campaigns": array of 2-3 recent campaign names or descriptions
- "ctv_activity": one of "confirmed", "exploring", "no signal" — whether company is active on Connected TV / streaming platforms
- "ad_spend_signal": one of "growing", "stable", "contracting", "unknown" — directional marketing investment trend
- "agency_relationships": array of known agency partners or null
- "content_output": one of "high", "moderate", "low" — volume of brand content / creative output
- "influencer_activity": boolean — whether company uses influencer marketing
- "channel_expansion_signals": array of new channels the company is exploring or moving into
- "notable_signals": string summarizing the most important advertising pattern (1-2 sentences)

Report:
{report_text}

Return ONLY valid JSON, no explanation."""

_EXECUTIVE_SIGNALS_FACTS_PROMPT = """Extract structured executive hiring signal facts from this analysis report about {company}.

Return a JSON object with ONLY the fields you can find evidence for. Use null for missing values.

Fields to extract:
- "recent_executive_hires": array of objects [{{"name": "string", "title": "string", "date": "string", "previous_company": "string", "signal_domain": "string"}}] — each confirmed executive appointment
- "executive_departures": array of objects [{{"name": "string", "title": "string", "date": "string"}}] — each confirmed departure
- "open_executive_searches": array of strings — titles being actively recruited (e.g. ["VP Engineering", "Chief Data Officer"])
- "leadership_investment_domains": array of strings — strategic domains where leadership is investing (e.g. ["AI/ML", "Digital Transformation", "Product"])
- "organizational_commitment": one of "strong", "moderate", "weak", "unclear"
- "leadership_stability": one of "stable", "rebuilding", "transitioning", "churning"
- "notable_signals": string summarizing the single most important executive hiring pattern (1-2 sentences)

Report:
{report_text}

Return ONLY valid JSON, no explanation."""

_TYPE_KEY_FACTS_PROMPTS = {
    "techstack": _TECHSTACK_FACTS_PROMPT,
    "seo": _SEO_FACTS_PROMPT,
    "pricing": _PRICING_FACTS_PROMPT,
    "hiring": _HIRING_FACTS_PROMPT,
    "sentiment": _SENTIMENT_FACTS_PROMPT,
    "financial": _FINANCIAL_FACTS_PROMPT,
    "competitors": _COMPETITORS_FACTS_PROMPT,
    "patents": _PATENTS_FACTS_PROMPT,
    "profile": _PROFILE_FACTS_PROMPT,
    "ua_fit": _UA_FIT_FACTS_PROMPT,
    "executive_signals": _EXECUTIVE_SIGNALS_FACTS_PROMPT,
    "brand_ad": _BRAND_AD_FACTS_PROMPT,
}


def extract_key_facts(company, report_text, analysis_type=None):
    """Extract structured key facts from a report. Returns dict or None."""
    # Truncate very long reports to save tokens
    if len(report_text) > 8000:
        report_text = report_text[:8000] + "\n\n... (truncated)"

    prompt_template = _TYPE_KEY_FACTS_PROMPTS.get(analysis_type, _KEY_FACTS_PROMPT)
    prompt = prompt_template.format(company=company, report_text=report_text)
    facts = generate_json(prompt, timeout=30, chain=CHEAP_CHAIN)

    if isinstance(facts, dict):
        # Clean out null values
        return {k: v for k, v in facts.items() if v is not None}
    return None


def reextract_all_key_facts(company, db_path="intel.db"):
    """Re-extract key facts for all analyses of a company using type-specific prompts.

    Reads existing report files, re-runs extraction with the correct prompt,
    and updates the DB records in-place. Returns summary of what was updated.
    """
    from db import get_connection, get_dossier_by_company

    conn = get_connection(db_path)
    dossier = get_dossier_by_company(conn, company)
    if not dossier:
        conn.close()
        return f"No dossier found for '{company}'."

    updated = []
    skipped = []

    for analysis in dossier.get("analyses", []):
        atype = analysis["analysis_type"]
        report_file = analysis.get("report_file")
        analysis_id = analysis["id"]

        if not report_file:
            skipped.append(f"{atype}: no report file")
            continue

        report_path = Path(report_file)
        if not report_path.exists():
            skipped.append(f"{atype}: report file missing ({report_file})")
            continue

        try:
            report_text = report_path.read_text(encoding="utf-8")
            new_facts = extract_key_facts(company, report_text, analysis_type=atype)
            if new_facts:
                facts_json = json.dumps(new_facts)
                conn.execute(
                    "UPDATE dossier_analyses SET key_facts_json = ? WHERE id = ?",
                    (facts_json, analysis_id),
                )
                conn.commit()
                updated.append(f"{atype}: {len(new_facts)} facts extracted")
            else:
                skipped.append(f"{atype}: extraction returned nothing")
        except Exception as e:
            skipped.append(f"{atype}: error — {e}")

    conn.close()

    lines = [f"Re-extracted key facts for {company}:"]
    if updated:
        lines.append(f"\nUpdated ({len(updated)}):")
        for u in updated:
            lines.append(f"  ✓ {u}")
    if skipped:
        lines.append(f"\nSkipped ({len(skipped)}):")
        for s in skipped:
            lines.append(f"  - {s}")
    return "\n".join(lines)


def _parse_numeric(value):
    """Parse a numeric value from various formats. Returns float or None.

    Handles: 22547, "22547", "$50B", "$2.8T", "221,000", "12.5%", "$198.3M"
    """
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None

    text = value.strip().replace(",", "").replace("%", "")

    multipliers = {"T": 1e12, "B": 1e9, "M": 1e6, "K": 1e3}
    match = re.match(r"^\$?\s*([\d.]+)\s*([TBMK])?", text, re.IGNORECASE)
    if match:
        num = float(match.group(1))
        suffix = (match.group(2) or "").upper()
        return num * multipliers.get(suffix, 1.0)

    try:
        return float(text.lstrip("$"))
    except (ValueError, TypeError):
        return None


# Fields that should be compared numerically
_NUMERIC_FIELDS = {"revenue", "market_cap", "headcount", "patent_count", "founded"}
# Fields where any change is significant
_IMPORTANT_FIELDS = {"ceo", "sentiment_score", "hiring_trend", "sector"}
# List fields where we track additions/removals
_LIST_FIELDS = {"key_products", "key_competitors", "key_risks", "top_patent_areas"}
# Minimum % change to consider significant for numeric fields
_CHANGE_THRESHOLD_PCT = 5.0


def _detect_changes(old_facts, new_facts):
    """Compare old and new key facts, return list of change dicts.

    Each change: {field, old_value, new_value, change_type, pct_change?}
    change_type: increased | decreased | changed | added | removed
    """
    changes = []
    all_fields = set(old_facts.keys()) | set(new_facts.keys())

    for field in all_fields:
        old_val = old_facts.get(field)
        new_val = new_facts.get(field)

        # Skip notable_events — these are ephemeral, not tracked for changes
        if field == "notable_events":
            continue

        # Both missing or identical
        if old_val == new_val:
            continue

        # Field added (didn't exist before)
        if old_val is None and new_val is not None:
            changes.append({"field": field, "old_value": None, "new_value": new_val, "change_type": "added"})
            continue

        # Field removed
        if old_val is not None and new_val is None:
            continue  # Don't flag removals — LLM may just not extract it this time

        # Numeric comparison
        if field in _NUMERIC_FIELDS:
            old_num = _parse_numeric(old_val)
            new_num = _parse_numeric(new_val)
            if old_num is not None and new_num is not None and old_num != 0:
                pct = ((new_num - old_num) / abs(old_num)) * 100
                if abs(pct) >= _CHANGE_THRESHOLD_PCT:
                    change_type = "increased" if pct > 0 else "decreased"
                    changes.append({
                        "field": field, "old_value": old_val, "new_value": new_val,
                        "change_type": change_type, "pct_change": round(pct, 1),
                    })
            continue

        # List comparison
        if field in _LIST_FIELDS:
            if isinstance(old_val, list) and isinstance(new_val, list):
                old_set = set(str(x).lower() for x in old_val)
                new_set = set(str(x).lower() for x in new_val)
                added = new_set - old_set
                removed = old_set - new_set
                if added:
                    changes.append({
                        "field": field, "old_value": list(old_set), "new_value": list(new_set),
                        "change_type": "added", "items_added": list(added), "items_removed": list(removed),
                    })
                elif removed:
                    changes.append({
                        "field": field, "old_value": list(old_set), "new_value": list(new_set),
                        "change_type": "removed", "items_added": list(added), "items_removed": list(removed),
                    })
            continue

        # String/important field comparison
        if field in _IMPORTANT_FIELDS:
            if str(old_val).lower().strip() != str(new_val).lower().strip():
                changes.append({
                    "field": field, "old_value": old_val, "new_value": new_val,
                    "change_type": "changed",
                })

    return changes


def get_temporal_context(company, analysis_type, db_path="intel.db"):
    """Return a prompt section with previous key facts for temporal comparison.
    Returns empty string if no prior analysis exists."""
    from db import get_connection, get_dossier_by_company, get_previous_key_facts
    try:
        conn = get_connection(db_path)
        dossier = get_dossier_by_company(conn, company)
        if not dossier:
            conn.close()
            return ""
        prev = get_previous_key_facts(conn, dossier["id"], analysis_type)
        if not prev:
            conn.close()
            return ""
        row = conn.execute(
            """SELECT created_at FROM dossier_analyses
               WHERE dossier_id = ? AND analysis_type = ?
               ORDER BY created_at DESC LIMIT 1""",
            (dossier["id"], analysis_type)
        ).fetchone()
        conn.close()
        prev_date = (row["created_at"] or "")[:10] if row else "unknown"
        facts_json = json.dumps(prev, indent=2)
        return (
            f"\n\n## Previous Analysis ({prev_date})\n"
            f"We previously analyzed this company's {analysis_type} data. "
            f"Key findings from that analysis:\n{facts_json}\n\n"
            f"IMPORTANT: Compare your current findings against these previous values. "
            f"When you find a significant change, explicitly call it out "
            f"(e.g., 'Revenue increased from $48B to $52B, representing 8.3% growth "
            f"since {prev_date}'). Highlight what changed, what stayed the same, "
            f"and what the trend implies."
        )
    except Exception:
        return ""


def save_to_dossier(company, analysis_type, report_file=None, report_text=None,
                    model_used=None, db_path="intel.db", progress_cb=None):
    """Save an analysis to the company dossier with extracted key facts.

    Called at the end of every analysis agent. Extracts structured facts from
    the report, detects changes vs. previous run, and stores everything.
    """
    _cb = progress_cb or (lambda *a: None)
    _cb('analysis_start', {'analysis_type': 'dossier', 'label': 'Dossier Update'})

    try:
        conn = get_connection(db_path)

        # Get or create dossier
        dossier_id = get_or_create_dossier(conn, company)

        # Extract key facts from report text
        key_facts_json = None
        new_facts = None
        if report_text:
            print(f"[dossier] Extracting key facts for {company}/{analysis_type}...")
            _cb('source_start', {'source': 'extract', 'label': 'Key Facts Extraction', 'detail': f'Extracting from {analysis_type} report'})
            new_facts = extract_key_facts(company, report_text, analysis_type=analysis_type)
            if new_facts:
                key_facts_json = json.dumps(new_facts)
                print(f"[dossier] Extracted {len(new_facts)} facts: {list(new_facts.keys())}")
                facts_detail = '\n'.join(f'• {k}: {str(v)[:100]}' for k, v in list(new_facts.items())[:12])
                _cb('source_done', {'source': 'extract', 'status': 'done', 'summary': f'{len(new_facts)} facts: {", ".join(list(new_facts.keys())[:5])}', 'detail': facts_detail})
            else:
                print("[dossier] No key facts extracted")
                _cb('source_done', {'source': 'extract', 'status': 'skipped', 'summary': 'No facts extracted'})

        # Detect changes vs. previous analysis
        if new_facts:
            _cb('source_start', {'source': 'changes', 'label': 'Change Detection', 'detail': f'Comparing with prior {analysis_type} scan'})
            old_facts = get_previous_key_facts(conn, dossier_id, analysis_type)
            if old_facts:
                changes = _detect_changes(old_facts, new_facts)
                if changes:
                    print(f"[dossier] Detected {len(changes)} changes since last {analysis_type} scan:")
                    change_summaries = []
                    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    for c in changes:
                        # Log to console
                        if c.get("pct_change") is not None:
                            print(f"[dossier]   {c['field']}: {c['old_value']} -> {c['new_value']} ({c['pct_change']:+.1f}%)")
                            change_summaries.append(f"{c['field']} ({c['pct_change']:+.1f}%)")
                        elif c["change_type"] == "added" and c.get("items_added"):
                            print(f"[dossier]   {c['field']}: +{c['items_added']}")
                            change_summaries.append(f"{c['field']}: +{len(c['items_added'])} items")
                        else:
                            print(f"[dossier]   {c['field']}: {c['old_value']} -> {c['new_value']}")
                            change_summaries.append(f"{c['field']} changed")

                        # Save as timeline event
                        if c.get("pct_change") is not None:
                            title = f"{c['field']}: {c['old_value']} -> {c['new_value']} ({c['pct_change']:+.1f}%)"
                        elif c["change_type"] == "added" and c.get("items_added"):
                            title = f"{c['field']}: added {', '.join(c['items_added'][:3])}"
                        else:
                            title = f"{c['field']}: {c['old_value']} -> {c['new_value']}"

                        add_dossier_event(
                            conn, dossier_id,
                            event_type="change_detected",
                            title=title,
                            description=f"Detected during {analysis_type} analysis",
                            event_date=today,
                            data_json=json.dumps(c),
                        )
                    changes_detail = '\n'.join(f'• {s}' for s in change_summaries)
                    _cb('source_done', {'source': 'changes', 'status': 'done', 'summary': f'{len(changes)} changes: {", ".join(change_summaries[:3])}', 'detail': changes_detail})
                else:
                    print(f"[dossier] No significant changes since last {analysis_type} scan")
                    _cb('source_done', {'source': 'changes', 'status': 'done', 'summary': 'No significant changes'})
            else:
                print(f"[dossier] First {analysis_type} scan — no prior data to compare")
                _cb('source_done', {'source': 'changes', 'status': 'skipped', 'summary': f'First {analysis_type} scan'})

        # Store the analysis
        _cb('source_start', {'source': 'save', 'label': 'Save to Dossier', 'detail': f'Persisting to {company} dossier'})
        add_dossier_analysis(
            conn, dossier_id, analysis_type,
            report_file=report_file,
            key_facts_json=key_facts_json,
            model_used=model_used,
        )

        conn.close()
        print(f"[dossier] Saved {analysis_type} analysis to {company} dossier")
        save_detail = f"Company: {company}\nType: {analysis_type}\nReport: {report_file or 'N/A'}\nModel: {model_used or 'N/A'}"
        _cb('source_done', {'source': 'save', 'status': 'done', 'summary': f'Saved {analysis_type} to {company} dossier', 'detail': save_detail})
        _cb('analysis_done', {'analysis_type': 'dossier'})
        return dossier_id
    except Exception as e:
        print(f"[dossier] Error saving to dossier: {e}")
        _cb('source_done', {'source': 'save', 'status': 'error', 'summary': str(e)[:80]})
        _cb('analysis_done', {'analysis_type': 'dossier'})
        return None
