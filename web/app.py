"""Flask web app for SignalForge — single-page three-pane UI with agentic chat."""

import os
import sys
import json
import threading
import queue
from pathlib import Path

from flask import Flask, render_template, request, jsonify, Response

# Add parent dir to path so we can import agents/scraper/etc.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from agents.chat import ChatLLM, _execute_tool, MAX_TOOL_RESULT_CHARS
from prompts.chat import SYSTEM_PROMPT, TOOL_SCHEMAS
from db import (init_db, get_connection, get_all_dossiers, get_dossier_by_company,
                get_or_create_dossier, add_dossier_event, get_company_id, get_hiring_snapshots)


# --- Helpers ---

def _parse_report_filename(filename):
    """Extract company name, analysis type, and date from a report filename."""
    stem = Path(filename).stem  # e.g. "stripe_financial_2026-03-20"

    # Comparison reports: {company_a}_vs_{company_b}_{date}.md
    if "_vs_" in stem:
        # Split off date from end
        parts = stem.rsplit("_", 1)
        date = parts[-1] if len(parts) >= 2 and len(parts[-1]) == 10 else ""
        body = parts[0] if date else stem
        # Split on _vs_ to get both company names
        vs_parts = body.split("_vs_", 1)
        company_a = vs_parts[0].replace("_", " ").strip().title()
        company_b = vs_parts[1].replace("_", " ").strip().title() if len(vs_parts) > 1 else ""
        company = f"{company_a} Vs {company_b}" if company_b else company_a
        return {"company": company, "type": "comparison", "date": date, "filename": filename}

    # Landscape reports: {company}_landscape_{date}.md
    if "_landscape_" in stem:
        parts = stem.rsplit("_", 1)
        date = parts[-1] if len(parts) >= 2 and len(parts[-1]) == 10 else ""
        body = parts[0].rsplit("_landscape", 1)[0] if date else stem
        company = body.replace("_", " ").title()
        return {"company": company, "type": "landscape", "date": date, "filename": filename}

    # Standard reports: {company}_{type}_{date}.md
    parts = stem.rsplit("_", 2)

    if len(parts) >= 3 and len(parts[-1]) == 10:  # has date at end
        date = parts[-1]
        analysis_type = parts[-2]
        company = parts[0].replace("_", " ").title()
    elif len(parts) >= 2 and len(parts[-1]) == 10:
        date = parts[-1]
        analysis_type = "analysis"
        company = parts[0].replace("_", " ").title()
    else:
        date = ""
        analysis_type = "report"
        company = stem.replace("_", " ").title()

    return {"company": company, "type": analysis_type, "date": date, "filename": filename}


def _get_all_reports():
    """Get all reports sorted by modification time (newest first)."""
    reports_dir = Path("reports")
    reports = []
    if reports_dir.exists():
        for f in sorted(reports_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
            info = _parse_report_filename(f.name)
            info["size"] = f.stat().st_size
            reports.append(info)
    return reports


# --- App Factory ---

def create_app(db_path="intel.db"):
    app = Flask(__name__,
                template_folder=os.path.join(os.path.dirname(__file__), "templates"),
                static_folder=os.path.join(os.path.dirname(__file__), "static"))
    app.config["DB_PATH"] = db_path

    init_db(db_path)

    # --- Single page ---

    @app.route("/")
    def index():
        return render_template("base.html")

    # --- API routes ---

    @app.route("/api/reports")
    def list_reports():
        return jsonify(_get_all_reports())

    @app.route("/api/reports/<filename>/content")
    def report_content(filename):
        filepath = Path("reports") / filename
        if not filepath.exists() or filepath.suffix != ".md":
            return jsonify({"error": "Not found"}), 404
        content = filepath.read_text(encoding="utf-8")
        info = _parse_report_filename(filename)
        return jsonify({"content": content, **info})

    @app.route("/api/reports/<filename>", methods=["DELETE"])
    def delete_report(filename):
        filepath = Path("reports") / filename
        if filepath.exists() and filepath.suffix == ".md":
            filepath.unlink()
            return jsonify({"ok": True})
        return jsonify({"error": "Not found"}), 404

    # --- Dossier API ---

    @app.route("/api/dossiers")
    def list_dossiers():
        conn = get_connection(db_path)
        dossiers = get_all_dossiers(conn)
        conn.close()
        return jsonify(dossiers)

    @app.route("/api/dossiers/<company_name>")
    def get_dossier_detail(company_name):
        conn = get_connection(db_path)
        dossier = get_dossier_by_company(conn, company_name)
        conn.close()
        if not dossier:
            return jsonify({"error": "Not found"}), 404
        return jsonify(dossier)

    @app.route("/api/dossiers/<company_name>/events", methods=["POST"])
    def create_dossier_event(company_name):
        data = request.json
        if not data or not data.get("title") or not data.get("event_type"):
            return jsonify({"error": "title and event_type required"}), 400
        conn = get_connection(db_path)
        dossier_id = get_or_create_dossier(conn, company_name)
        event_id = add_dossier_event(
            conn, dossier_id,
            event_type=data["event_type"],
            title=data["title"],
            description=data.get("description"),
            event_date=data.get("event_date"),
            source_url=data.get("source_url"),
        )
        conn.close()
        return jsonify({"ok": True, "event_id": event_id})

    @app.route("/api/dossiers/<company_name>/hiring-snapshots")
    def get_company_snapshots(company_name):
        """Get hiring snapshot history for a company."""
        conn = get_connection(db_path)
        company_id = get_company_id(conn, company_name)
        if not company_id:
            conn.close()
            return jsonify({"error": "Company not found"}), 404
        snapshots = get_hiring_snapshots(conn, company_id, limit=20)
        conn.close()
        return jsonify(snapshots)

    @app.route("/api/dossiers/<company_name>/briefing", methods=["POST"])
    def generate_briefing_api(company_name):
        """Generate or refresh the intelligence briefing for a company."""
        from agents.briefing import generate_briefing

        try:
            briefing = generate_briefing(company_name, db_path)
            return jsonify({"ok": True, "briefing": briefing})
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # --- Chat API ---

    @app.route("/api/chat", methods=["POST"])
    def chat_api():
        data = request.json
        messages = data.get("messages", [])
        if not messages:
            return jsonify({"error": "No messages"}), 400

        history = [{"role": "system", "content": SYSTEM_PROMPT}] + messages

        def generate():
            try:
                llm = ChatLLM()
            except RuntimeError as e:
                yield f"data: {json.dumps({'type': 'error', 'text': str(e)})}\n\n"
                return

            max_rounds = 15

            for _ in range(max_rounds):
                try:
                    response = llm.chat(history, tools=TOOL_SCHEMAS)
                except RuntimeError as e:
                    error_msg = str(e).lower()
                    if any(kw in error_msg for kw in ["token", "context", "length", "too long", "too large", "maximum", "reduce"]):
                        history_trimmed = [history[0]] + history[-4:]
                        try:
                            response = llm.chat(history_trimmed, tools=TOOL_SCHEMAS)
                        except RuntimeError:
                            yield f"data: {json.dumps({'type': 'error', 'text': 'Sorry, I hit a temporary issue. Please try again.'})}\n\n"
                            return
                    else:
                        yield f"data: {json.dumps({'type': 'error', 'text': 'Sorry, I hit a temporary issue. Please try again.'})}\n\n"
                        return

                tool_calls = response.get("tool_calls")

                if tool_calls:
                    # Stream thinking content if the LLM included reasoning alongside tool calls
                    thinking_text = response.get("content", "")
                    if thinking_text and thinking_text.strip():
                        yield f"data: {json.dumps({'type': 'thinking', 'text': thinking_text.strip()})}\n\n"

                    history.append(response)

                    for tc in tool_calls:
                        fn_name = tc["function"]["name"]
                        fn_args = json.loads(tc["function"]["arguments"]) if isinstance(tc["function"]["arguments"], str) else tc["function"]["arguments"]

                        # Handle think tool as a thinking event, not a tool call
                        if fn_name == "think":
                            yield f"data: {json.dumps({'type': 'thinking', 'text': fn_args.get('reasoning', '')})}\n\n"
                            history.append({
                                "role": "tool",
                                "tool_call_id": tc["id"],
                                "content": "Thinking noted.",
                            })
                            continue

                        yield f"data: {json.dumps({'type': 'tool_call', 'name': fn_name, 'args': fn_args})}\n\n"

                        # Run tool in a thread so we can stream progress
                        progress_q = queue.Queue()
                        result_box = [None]

                        def _run(name=fn_name, args=fn_args):
                            try:
                                result_box[0] = _execute_tool(
                                    name, args, db_path,
                                    progress_callback=lambda msg: progress_q.put(msg),
                                )
                            except Exception as e:
                                result_box[0] = f"Tool error: {e}"

                        t = threading.Thread(target=_run)
                        t.start()

                        while t.is_alive():
                            try:
                                msg = progress_q.get(timeout=0.3)
                                yield f"data: {json.dumps({'type': 'tool_progress', 'name': fn_name, 'text': msg})}\n\n"
                            except queue.Empty:
                                pass

                        # Drain remaining progress messages
                        while not progress_q.empty():
                            try:
                                msg = progress_q.get_nowait()
                                yield f"data: {json.dumps({'type': 'tool_progress', 'name': fn_name, 'text': msg})}\n\n"
                            except queue.Empty:
                                break

                        result = result_box[0] or "Tool returned no result."

                        if len(result) > MAX_TOOL_RESULT_CHARS:
                            result = result[:MAX_TOOL_RESULT_CHARS] + "\n\n... (truncated)"

                        yield f"data: {json.dumps({'type': 'tool_result', 'name': fn_name, 'result': result})}\n\n"

                        history.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": result,
                        })

                    continue

                else:
                    text = response.get("content", "")
                    yield f"data: {json.dumps({'type': 'message', 'text': text})}\n\n"
                    return

            yield f"data: {json.dumps({'type': 'error', 'text': 'Reached the maximum number of tool calls for this query. Here is what I found so far.'})}\n\n"

        return Response(generate(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, port=5001, threaded=True)
