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
                get_or_create_dossier, add_dossier_event, get_company_id, get_hiring_snapshots,
                get_latest_key_facts)


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


def _build_context_injection(company_name, db_path):
    """Build a context block for the system prompt when the user is viewing a company."""
    try:
        conn = get_connection(db_path)
        dossier = get_dossier_by_company(conn, company_name)
        if not dossier:
            conn.close()
            return f"[CONTEXT] The user is currently viewing information about {company_name}. No dossier exists yet for this company."

        dossier_id = dossier["id"]
        facts = get_latest_key_facts(conn, dossier_id)
        conn.close()

        lines = [f"[CONTEXT] The user is currently viewing information about {company_name}."]
        if dossier.get("sector"):
            lines.append(f"Sector: {dossier['sector']}")

        if facts:
            lines.append("Key intelligence on file:")
            for atype, info in facts.items():
                data = info.get("data", {})
                if isinstance(data, dict):
                    # Grab up to 5 key facts
                    snippets = []
                    for k, v in list(data.items())[:5]:
                        val = str(v)[:120] if v else ""
                        if val:
                            snippets.append(f"  - {k}: {val}")
                    if snippets:
                        lines.append(f"  [{atype}] (as of {info.get('as_of', '?')}):")
                        lines.extend(snippets)

        lines.append("Use this context to answer questions about the company. Don't call get_dossier unless the user asks for deeper details.")
        return "\n".join(lines)
    except Exception:
        return None


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

    @app.route("/api/reports/<filename>/pdf")
    def export_report_pdf(filename):
        """Convert a markdown report to a styled PDF and return it for download."""
        import markdown as md
        from xhtml2pdf import pisa
        import io

        filepath = Path("reports") / filename
        if not filepath.exists() or filepath.suffix != ".md":
            return jsonify({"error": "Not found"}), 404

        content = filepath.read_text(encoding="utf-8")
        info = _parse_report_filename(filename)
        company = info.get("company", "Report")
        report_type = info.get("type", "analysis").replace("_", " ").title()
        report_date = info.get("date", "")

        # Convert markdown to HTML
        html_body = md.markdown(content, extensions=["tables", "fenced_code", "toc"])

        # Build full HTML doc with light-theme print styles
        html_doc = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
    @page {{
        size: A4;
        margin: 20mm 18mm 20mm 18mm;
        @frame footer {{
            -pdf-frame-content: page-footer;
            bottom: 0mm;
            margin-left: 18mm;
            margin-right: 18mm;
            height: 12mm;
        }}
    }}
    body {{
        font-family: Helvetica, Arial, sans-serif;
        font-size: 11px;
        line-height: 1.6;
        color: #1a1a1a;
    }}
    .header {{
        border-bottom: 2px solid #3b82f6;
        padding-bottom: 10px;
        margin-bottom: 20px;
    }}
    .header-company {{
        font-size: 22px;
        font-weight: bold;
        color: #111;
    }}
    .header-meta {{
        font-size: 10px;
        color: #666;
        margin-top: 4px;
    }}
    .header-brand {{
        font-size: 12px;
        font-weight: bold;
        color: #3b82f6;
        text-align: right;
        float: right;
    }}
    .header-brand-sub {{
        font-size: 8px;
        color: #999;
        text-align: right;
    }}
    h1 {{ font-size: 18px; font-weight: bold; margin: 18px 0 8px; color: #111; }}
    h2 {{ font-size: 15px; font-weight: bold; margin: 16px 0 6px; color: #222; }}
    h3 {{ font-size: 13px; font-weight: bold; margin: 12px 0 4px; color: #333; }}
    p {{ margin: 6px 0; }}
    ul, ol {{ padding-left: 20px; margin: 6px 0; }}
    li {{ margin: 3px 0; }}
    strong {{ color: #111; }}
    a {{ color: #3b82f6; text-decoration: none; }}
    table {{
        width: 100%;
        border-collapse: collapse;
        margin: 10px 0;
        font-size: 10px;
    }}
    th {{
        text-align: left;
        padding: 6px 8px;
        background: #f3f4f6;
        border: 1px solid #d1d5db;
        font-weight: 600;
    }}
    td {{
        padding: 5px 8px;
        border: 1px solid #d1d5db;
    }}
    blockquote {{
        border-left: 3px solid #3b82f6;
        padding-left: 12px;
        color: #555;
        margin: 8px 0;
    }}
    code {{
        background: #f3f4f6;
        padding: 1px 4px;
        border-radius: 3px;
        font-size: 10px;
    }}
    pre {{
        background: #f3f4f6;
        padding: 10px;
        border-radius: 4px;
        font-size: 10px;
        overflow: hidden;
        margin: 8px 0;
    }}
    hr {{
        border: none;
        border-top: 1px solid #ddd;
        margin: 14px 0;
    }}
    #page-footer {{
        font-size: 8px;
        color: #999;
        border-top: 1px solid #eee;
        padding-top: 4px;
    }}
</style>
</head>
<body>
    <div class="header">
        <div class="header-brand">SignalForge<br><span class="header-brand-sub">Competitive Intelligence</span></div>
        <div class="header-company">{company}</div>
        <div class="header-meta">{report_type} &middot; {report_date}</div>
    </div>
    {html_body}
    <div id="page-footer">
        Generated by SignalForge &middot; {report_date or 'N/A'}
    </div>
</body>
</html>"""

        # Render PDF
        pdf_buffer = io.BytesIO()
        pisa_status = pisa.CreatePDF(html_doc, dest=pdf_buffer)

        if pisa_status.err:
            return jsonify({"error": "PDF generation failed"}), 500

        pdf_buffer.seek(0)
        pdf_filename = filename.replace(".md", ".pdf")

        return Response(
            pdf_buffer.getvalue(),
            mimetype="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename={pdf_filename}",
                "Content-Type": "application/pdf",
            },
        )

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

    @app.route("/api/dossiers/<company_name>/pdf")
    def export_briefing_pdf(company_name):
        """Export a company's intelligence briefing as a styled PDF."""
        from xhtml2pdf import pisa
        import io

        conn = get_connection(db_path)
        dossier = get_dossier_by_company(conn, company_name)
        conn.close()

        if not dossier or not dossier.get("briefing_json"):
            return jsonify({"error": "No briefing found for this company"}), 404

        briefing = dossier["briefing_json"]
        if isinstance(briefing, str):
            briefing = json.loads(briefing)

        dm = briefing.get("digital_maturity", {})
        overall = dm.get("overall_score", "N/A")
        label = dm.get("overall_label", "")
        score_val = overall if isinstance(overall, int) else 0
        score_color = "#22c55e" if score_val >= 80 else "#3b82f6" if score_val >= 60 else "#f59e0b" if score_val >= 40 else "#ef4444" if score_val >= 20 else "#dc2626"
        subs = dm.get("sub_scores", {})

        # Build sub-scores table rows
        sub_rows = ""
        for key, name in [("tech_modernity", "Tech Modernity"), ("data_analytics", "Data & Analytics"),
                          ("ai_readiness", "AI Readiness"), ("organizational_readiness", "Org Readiness")]:
            s = subs.get(key, {})
            sub_rows += f"<tr><td>{name}</td><td><strong>{s.get('score', 'N/A')}</strong>/100</td><td>{s.get('rationale', '')}</td></tr>"

        # Engagement opportunities
        opps_html = ""
        for opp in briefing.get("engagement_opportunities", []):
            priority = opp.get("priority", "medium").upper()
            p_color = "#dc2626" if priority == "HIGH" else "#d97706" if priority == "MEDIUM" else "#16a34a"
            opps_html += f"""
            <div style="margin-bottom:14px;padding:10px 12px;border:1px solid #e5e7eb;border-radius:6px;border-left:3px solid {p_color}">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
                    <strong>{opp.get('area', '')}</strong>
                    <span style="font-size:9px;font-weight:600;color:{p_color};text-transform:uppercase">{priority}</span>
                </div>
                <div style="font-size:10px;color:#555;margin-bottom:4px">{opp.get('detail', '')}</div>
                {f'<div style="font-size:10px;color:#3b82f6;font-style:italic">{opp.get("why_now", "")}</div>' if opp.get('why_now') else ''}
            </div>"""

        # Budget signals
        budget = briefing.get("budget_signals", {})
        budget_html = ""
        if budget:
            budget_html = f"""
            <h2>Budget &amp; Appetite Signals</h2>
            <table><tr><th>Signal</th><th>Detail</th></tr>
            <tr><td>Estimated IT Spend</td><td>{budget.get('estimated_it_spend', 'N/A')}</td></tr>
            <tr><td>Consulting Appetite</td><td>{budget.get('consulting_appetite', 'N/A')}</td></tr>
            <tr><td>Evidence</td><td>{budget.get('evidence', '')}</td></tr>
            </table>"""

        # Risk profile
        risks_html = ""
        for risk in briefing.get("risk_profile", []):
            sev = risk.get("severity", "medium")
            sev_color = "#dc2626" if sev == "high" else "#d97706" if sev == "medium" else "#16a34a"
            risks_html += f"<li><strong style='color:{sev_color}'>[{sev.upper()}]</strong> <strong>{risk.get('category', '')}</strong>: {risk.get('description', '')}</li>"

        # Hiring trajectory
        hiring = briefing.get("hiring_trajectory", {})
        hiring_html = ""
        if hiring:
            hiring_html = f"""
            <h2>Hiring Trajectory</h2>
            <p><strong>Trend:</strong> {hiring.get('trend', 'N/A')} &mdash; <strong>Signal:</strong> {hiring.get('signal', '')}</p>
            <p>{hiring.get('detail', '')}</p>"""

        # Strategic assessment
        strategic = briefing.get("strategic_assessment", "")

        # Competitive pressure
        comp = briefing.get("competitive_pressure", {})
        comp_html = ""
        if comp:
            comp_html = f"""
            <h2>Competitive Pressure</h2>
            <p><strong>Level:</strong> {comp.get('level', 'N/A')}</p>
            <p>{comp.get('detail', '')}</p>"""

        generated_at = dossier.get("briefing_generated_at", "")[:10]

        html_doc = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
    @page {{
        size: A4;
        margin: 18mm 16mm 18mm 16mm;
    }}
    body {{
        font-family: Helvetica, Arial, sans-serif;
        font-size: 11px;
        line-height: 1.6;
        color: #1a1a1a;
    }}
    .header {{
        border-bottom: 2px solid #3b82f6;
        padding-bottom: 10px;
        margin-bottom: 16px;
    }}
    .header-company {{ font-size: 22px; font-weight: bold; color: #111; }}
    .header-meta {{ font-size: 10px; color: #666; margin-top: 4px; }}
    .header-brand {{ font-size: 12px; font-weight: bold; color: #3b82f6; float: right; }}
    .header-brand-sub {{ font-size: 8px; color: #999; }}
    .score-box {{
        text-align: center;
        padding: 16px;
        margin: 16px 0;
        border: 2px solid #3b82f6;
        border-radius: 8px;
    }}
    .score-number {{ font-size: 36px; font-weight: bold; color: {score_color}; }}
    .score-label {{ font-size: 14px; font-weight: 600; color: {score_color}; margin-top: 4px; }}
    h2 {{ font-size: 15px; font-weight: bold; margin: 18px 0 8px; color: #222; border-bottom: 1px solid #e5e7eb; padding-bottom: 4px; }}
    table {{ width: 100%; border-collapse: collapse; margin: 10px 0; font-size: 10px; }}
    th {{ text-align: left; padding: 6px 8px; background: #f3f4f6; border: 1px solid #d1d5db; font-weight: 600; }}
    td {{ padding: 5px 8px; border: 1px solid #d1d5db; }}
    ul {{ padding-left: 18px; }}
    li {{ margin: 4px 0; }}
    p {{ margin: 6px 0; }}
    strong {{ color: #111; }}
    .footer {{
        margin-top: 20px;
        padding-top: 6px;
        border-top: 1px solid #ddd;
        font-size: 8px;
        color: #999;
    }}
</style>
</head>
<body>
    <div class="header">
        <div class="header-brand">SignalForge<br><span class="header-brand-sub">Competitive Intelligence</span></div>
        <div class="header-company">{company_name}</div>
        <div class="header-meta">Intelligence Briefing &middot; {generated_at}</div>
    </div>

    <div class="score-box">
        <div class="score-number">{overall}</div>
        <div class="score-label">{label}</div>
        <div style="font-size:9px;color:#666;margin-top:4px">Digital Maturity Score</div>
    </div>

    <h2>Sub-Scores</h2>
    <table>
        <tr><th>Dimension</th><th>Score</th><th>Rationale</th></tr>
        {sub_rows}
    </table>

    <h2>Engagement Opportunities</h2>
    {opps_html}

    {budget_html}
    {hiring_html}
    {comp_html}

    {'<h2>Risk Profile</h2><ul>' + risks_html + '</ul>' if risks_html else ''}

    <h2>Strategic Assessment</h2>
    <p>{strategic}</p>

    <div class="footer">
        Generated by SignalForge &middot; {generated_at}
    </div>
</body>
</html>"""

        pdf_buffer = io.BytesIO()
        pisa_status = pisa.CreatePDF(html_doc, dest=pdf_buffer)

        if pisa_status.err:
            return jsonify({"error": "PDF generation failed"}), 500

        pdf_buffer.seek(0)
        safe_name = company_name.lower().replace(" ", "_")
        pdf_filename = f"{safe_name}_briefing_{generated_at}.pdf"

        return Response(
            pdf_buffer.getvalue(),
            mimetype="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename={pdf_filename}",
                "Content-Type": "application/pdf",
            },
        )

    # --- Chat API ---

    @app.route("/api/chat", methods=["POST"])
    def chat_api():
        data = request.json
        messages = data.get("messages", [])
        if not messages:
            return jsonify({"error": "No messages"}), 400

        # Inject current date + company context into system prompt
        from datetime import datetime
        today = datetime.now().strftime("%A, %B %d, %Y")
        context = data.get("context")
        system_content = SYSTEM_PROMPT + f"\n\n[TODAY] The current date is {today}. Always use the current year ({datetime.now().year}) in search queries and when referencing time. Never assume an older date."
        if context and context.get("company"):
            context_text = _build_context_injection(context["company"], db_path)
            if context_text:
                system_content += "\n\n" + context_text

        history = [{"role": "system", "content": system_content}] + messages

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
                    elif any(kw in error_msg for kw in ["rate limit", "429", "quota", "resource_exhausted"]):
                        yield f"data: {json.dumps({'type': 'error', 'text': 'Rate limited — all AI providers are temporarily exhausted. Wait a minute and try again.'})}\n\n"
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
