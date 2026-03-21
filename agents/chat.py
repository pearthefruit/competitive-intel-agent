"""Agent 4: Chat Interface — natural language LLM with function calling."""

import os
import json
import io
import sys

import httpx

from db import init_db, get_connection
from agents.collect import collect
from agents.classify import classify
from agents.analyze import analyze
from scraper.web_search import search_news, search_web, format_search_results
from prompts.chat import SYSTEM_PROMPT, TOOL_SCHEMAS

MAX_HISTORY = 20

# Providers that support OpenAI-compatible function calling
CHAT_PROVIDERS = [
    {
        "name": "groq",
        "env_key": "GROQ_API_KEY",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "model": "llama-3.3-70b-versatile",
    },
    {
        "name": "mistral",
        "env_key": "MISTRAL_API_KEY",
        "url": "https://api.mistral.ai/v1/chat/completions",
        "model": "mistral-small-latest",
    },
]


class ChatLLM:
    """OpenAI-compatible chat completions with tool/function calling support."""

    def __init__(self):
        self.http = httpx.Client(timeout=60, follow_redirects=True)
        self.providers = []
        for p in CHAT_PROVIDERS:
            key = os.environ.get(p["env_key"], "").strip()
            if key:
                self.providers.append({**p, "key": key})
        if not self.providers:
            raise RuntimeError("No API keys found for chat (need GROQ_API_KEY or MISTRAL_API_KEY)")

    def chat(self, messages, tools=None):
        """Send chat completion request. Returns the assistant message dict."""
        for p in self.providers:
            try:
                body = {
                    "model": p["model"],
                    "messages": messages,
                    "temperature": 0.3,
                }
                if tools:
                    body["tools"] = tools
                    body["tool_choice"] = "auto"

                headers = {
                    "Authorization": f"Bearer {p['key']}",
                    "Content-Type": "application/json",
                }
                resp = self.http.post(p["url"], json=body, headers=headers)

                if resp.status_code == 429:
                    continue  # Try next provider
                if resp.status_code != 200:
                    continue

                data = resp.json()
                return data["choices"][0]["message"]

            except Exception:
                continue

        raise RuntimeError("All chat providers failed")

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

        # Format as table
        lines = [" | ".join(columns)]
        lines.append("-" * len(lines[0]))
        for row in rows[:50]:  # Cap at 50 rows
            lines.append(" | ".join(str(v) for v in row))

        result = "\n".join(lines)
        if len(rows) > 50:
            result += f"\n... ({len(rows)} total rows, showing first 50)"
        return result

    except Exception as e:
        return f"SQL error: {e}"


def _execute_tool(name, args, db_path):
    """Execute a tool call and return the result as a string."""
    # Capture stdout from pipeline functions
    old_stdout = sys.stdout
    sys.stdout = captured = io.StringIO()

    try:
        if name == "collect":
            new, skipped = collect(args["company"], args.get("url"), db_path)
            output = captured.getvalue()
            return f"{output}\nResult: {new} new jobs, {skipped} duplicates skipped."

        elif name == "classify":
            count = classify(args["company"], db_path)
            output = captured.getvalue()
            return f"{output}\nResult: {count} jobs classified."

        elif name == "analyze":
            path = analyze(args["company"], db_path)
            output = captured.getvalue()
            if path:
                return f"{output}\nResult: Report saved to {path}"
            return f"{output}\nResult: Analysis failed — see output above."

        elif name == "full_pipeline":
            new, skipped = collect(args["company"], args.get("url"), db_path)
            if new == 0 and skipped == 0:
                output = captured.getvalue()
                return f"{output}\nPipeline stopped: no jobs collected."

            count = classify(args["company"], db_path)
            path = analyze(args["company"], db_path)
            output = captured.getvalue()
            summary = f"\nPipeline complete: {new} new jobs collected, {count} classified."
            if path:
                summary += f" Report: {path}"
            return f"{output}{summary}"

        elif name == "query_db":
            # Don't need captured stdout for DB queries
            sys.stdout = old_stdout
            old_stdout = None
            return _safe_query_db(args["sql"], db_path)

        elif name == "web_search":
            sys.stdout = old_stdout
            old_stdout = None
            query = args["query"]
            # Search both news and web
            news = search_news(query, max_results=5)
            web = search_web(query, max_results=5)
            all_results = news + web
            return format_search_results(all_results) if all_results else "No results found."

        else:
            return f"Unknown tool: {name}"

    except Exception as e:
        return f"Tool error: {e}"

    finally:
        if old_stdout is not None:
            sys.stdout = old_stdout
            # Print captured output so user sees progress
            progress = captured.getvalue()
            if progress:
                print(progress, end="")


def chat_repl(db_path="intel.db"):
    """Interactive chat loop with tool-calling support."""
    init_db(db_path)

    print("=" * 60)
    print("  Competitive Intelligence Chat")
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
                print(f"\n[error] {e}")
                break

            # Check if LLM wants to call tools
            tool_calls = response.get("tool_calls")

            if tool_calls:
                # Add assistant message with tool calls to history
                history.append(response)

                for tc in tool_calls:
                    fn_name = tc["function"]["name"]
                    fn_args = json.loads(tc["function"]["arguments"]) if isinstance(tc["function"]["arguments"], str) else tc["function"]["arguments"]

                    print(f"\n[calling {fn_name}({', '.join(f'{k}={v!r}' for k, v in fn_args.items())})]")

                    result = _execute_tool(fn_name, fn_args, db_path)

                    # Add tool result to history
                    history.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result,
                    })

                # Loop back to let LLM process tool results
                continue

            else:
                # Plain text response — print and break to next user input
                text = response.get("content", "")
                print(f"\nAssistant: {text}\n")
                history.append({"role": "assistant", "content": text})
                break

        # Trim history to avoid context overflow (keep system + last N messages)
        if len(history) > MAX_HISTORY + 1:
            history = [history[0]] + history[-(MAX_HISTORY):]
