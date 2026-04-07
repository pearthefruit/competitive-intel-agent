"""Flask web app for SignalVault — single-page three-pane UI with agentic chat."""

import os
import sys
import json
import threading
import queue
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, render_template, request, jsonify, Response

# Add parent dir to path so we can import agents/scraper/etc.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from agents.chat import ChatLLM, _execute_tool, MAX_TOOL_RESULT_CHARS
from prompts.chat import SYSTEM_PROMPT, CONDENSED_SYSTEM_PROMPT, TOOL_SCHEMAS, get_tool_schemas
from db import (init_db, get_connection, get_all_dossiers, get_dossier_by_company,
                get_or_create_dossier, add_dossier_event, get_company_id, get_hiring_snapshots,
                get_latest_key_facts)


# --- Helpers ---

def _parse_report_filename(filename):
    """Extract company name, analysis type, and date from a report filename."""
    import re
    
    stem = Path(filename).stem  # e.g. "stripe_financial_2026-03-20"
    # Strip any trailing deduplication suffixes like " (1)", " 7", or "_7" appended by OS/browsers or our own save logic
    stem = re.sub(r'[\s\(\)]+\d+\s*$', '', stem)
    stem = re.sub(r'_(\d+)$', '', stem)

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


def _build_report_meta_map(db_path="intel.db"):
    """Build a mapping of report filename → {type, company} from the DB."""
    try:
        conn = get_connection(db_path)
        rows = conn.execute(
            """SELECT da.report_file, da.analysis_type, d.company_name
               FROM dossier_analyses da
               JOIN dossiers d ON d.id = da.dossier_id
               WHERE da.report_file IS NOT NULL"""
        ).fetchall()
        conn.close()
        return {
            Path(r["report_file"]).name: {
                "type": r["analysis_type"],
                "company": r["company_name"],
            }
            for r in rows
        }
    except Exception:
        return {}


def _get_all_reports():
    """Get all reports sorted by modification time (newest first)."""
    reports_dir = Path("reports")
    reports = []
    if reports_dir.exists():
        meta_map = _build_report_meta_map()
        for f in sorted(reports_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
            info = _parse_report_filename(f.name)
            db_meta = meta_map.get(f.name)
            if db_meta:
                info["type"] = db_meta["type"]
                info["company"] = db_meta["company"]
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


def _compress_history(history):
    """Aggressively compress conversation history to prevent context overflow.

    Strategy:
    1. Truncate ALL tool results older than the last 2 to 200 chars
    2. If total history is still > 30K chars, drop middle messages entirely
       (keep system prompt + first user message + last 4 messages)
    3. Cap any single tool result at 4000 chars
    """
    if len(history) <= 3:
        return

    # Step 1: Cap all tool results at 4000 chars
    for msg in history:
        if msg.get("role") == "tool" and len(msg.get("content", "")) > 4000:
            msg["content"] = msg["content"][:4000] + "\n\n... (truncated)"

    # Step 2: Truncate old tool results aggressively
    tool_indices = [i for i, m in enumerate(history) if m.get("role") == "tool"]
    if len(tool_indices) > 2:
        for idx in tool_indices[:-2]:
            content = history[idx].get("content", "")
            if len(content) > 200:
                history[idx]["content"] = content[:200] + "\n... (compressed)"

    # Step 3: If still too large, drop middle messages
    total = sum(len(str(m.get("content", ""))) for m in history)
    if total > 30000 and len(history) > 6:
        # Keep: system[0] + last 4 messages
        kept = [history[0]] + history[-4:]
        history.clear()
        history.extend(kept)


def _summarize_tool_result(tool_name, raw_result):
    """Use a fast LLM call to compress verbose tool results for conversation history.

    Multi-step approach: spend a small, fast LLM call to summarize each tool result,
    keeping the conversation history lean so the main chat LLM doesn't hit context limits.
    The user still sees the full result in the UI — only the history gets compressed.
    """
    if len(raw_result) < 600:
        return raw_result  # Already short — no need to summarize

    from agents.llm import generate_text, FAST_CHAIN
    prompt = (
        f"Compress this {tool_name} tool result into a dense 2-3 sentence summary. "
        f"Keep ALL key data points, numbers, company names, and actionable findings. "
        f"Drop formatting, boilerplate, and redundancy.\n\n"
        f"Result:\n{raw_result[:4000]}\n\nDense summary:"
    )

    try:
        summary, _ = generate_text(prompt, timeout=15, chain=FAST_CHAIN)
        if summary and len(summary.strip()) > 30:
            return summary.strip()
    except Exception as e:
        print(f"[chat] Summarization failed ({e}), falling back to truncation")

    # Fallback: simple truncation
    return raw_result[:600] + "\n... (truncated)"


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

    @app.route("/api/reports/<path:filename>/content")
    def report_content(filename):
        filepath = Path("reports") / filename
        info = _parse_report_filename(filename)
        # Override with DB metadata (correct company name for lens reports etc.)
        db_meta = _build_report_meta_map().get(Path(filename).name)
        if db_meta:
            info["type"] = db_meta["type"]
            info["company"] = db_meta["company"]
        if not filepath.exists():
            # File missing — return a placeholder instead of 404
            return jsonify({"content": f"*Report file not found on disk.* The analysis ran but the file `{filename}` is missing — it may have been moved or deleted.", **info})
        content = filepath.read_text(encoding="utf-8")
        return jsonify({"content": content, **info})

    @app.route("/api/reports/<path:filename>/pdf")
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
        db_meta = _build_report_meta_map().get(Path(filename).name)
        if db_meta:
            info["type"] = db_meta["type"]
            info["company"] = db_meta["company"]
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
        <div class="header-brand">SignalVault<br><span class="header-brand-sub">Competitive Intelligence</span></div>
        <div class="header-company">{company}</div>
        <div class="header-meta">{report_type} &middot; {report_date}</div>
    </div>
    {html_body}
    <div id="page-footer">
        Generated by SignalVault &middot; {report_date or 'N/A'}
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

    @app.route("/api/reports/<path:filename>", methods=["PATCH", "DELETE"])
    def manage_report(filename):
        if request.method == "DELETE":
            filepath = Path("reports") / filename
            if filepath.exists() and filepath.suffix == ".md":
                filepath.unlink()
                # Also clean up from DB
                conn = get_connection(db_path)
                conn.execute("UPDATE dossier_analyses SET report_file = NULL WHERE report_file = ? OR report_file = ?", (filename, f"reports/{filename}"))
                conn.commit()
                conn.close()
                return jsonify({"ok": True})
            return jsonify({"error": "Not found"}), 404
            
        elif request.method == "PATCH":
            data = request.json
            new_filename = data.get("new_filename")
            if not new_filename:
                return jsonify({"error": "new_filename required"}), 400
            if not new_filename.endswith(".md"):
                new_filename += ".md"
            
            old_path = Path("reports") / filename
            new_path = Path("reports") / new_filename
            
            if not old_path.exists():
                return jsonify({"error": "Original report not found"}), 404
            if new_path.exists():
                return jsonify({"error": "A report with that name already exists"}), 400
                
            try:
                old_path.rename(new_path)
                # Update DB references
                conn = get_connection(db_path)
                conn.execute("UPDATE dossier_analyses SET report_file = ? WHERE report_file = ? OR report_file = ?", 
                             (new_filename, filename, f"reports/{filename}"))
                conn.commit()
                conn.close()
                return jsonify({"ok": True, "new_filename": new_filename})
            except Exception as e:
                return jsonify({"error": str(e)}), 500

    @app.route("/api/dossiers/<path:name>", methods=["PATCH"])
    def rename_dossier(name):
        data = request.json
        new_name = data.get("new_name")
        if not new_name:
            return jsonify({"error": "new_name required"}), 400
            
        conn = get_connection(db_path)
        existing = conn.execute("SELECT id FROM dossiers WHERE company_name COLLATE NOCASE = ?", (new_name,)).fetchone()
        if existing:
            conn.close()
            return jsonify({"error": "A company with that name already exists"}), 400
            
        try:
            conn.execute("UPDATE dossiers SET company_name = ?, updated_at = ? WHERE company_name COLLATE NOCASE = ?",
                         (new_name, datetime.now(timezone.utc).isoformat(), name))
            conn.commit()
            conn.close()
            return jsonify({"ok": True})
        except Exception as e:
            if conn: conn.close()
            return jsonify({"error": str(e)}), 500

    @app.route("/api/dossiers/<path:name>/delete", methods=["POST"])
    def delete_dossier(name):
        """Delete a company dossier and all its analyses, lens scores, and events."""
        try:
            conn = get_connection(db_path)
            row = conn.execute("SELECT id FROM dossiers WHERE company_name COLLATE NOCASE = ?", (name,)).fetchone()
            if not row:
                conn.close()
                return jsonify({"error": "Not found"}), 404
            dossier_id = row["id"]
            conn.execute("DELETE FROM campaign_prospects WHERE dossier_id = ?", (dossier_id,))
            conn.execute("DELETE FROM dossier_analyses WHERE dossier_id = ?", (dossier_id,))
            conn.execute("DELETE FROM dossier_events WHERE dossier_id = ?", (dossier_id,))
            conn.execute("DELETE FROM lens_scores WHERE dossier_id = ?", (dossier_id,))
            conn.execute("DELETE FROM dossiers WHERE id = ?", (dossier_id,))
            conn.commit()
            conn.close()
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/analyses/<int:analysis_id>", methods=["DELETE"])
    def delete_analysis(analysis_id):
        conn = get_connection(db_path)
        conn.execute("DELETE FROM dossier_analyses WHERE id = ?", (analysis_id,))
        conn.commit()
        conn.close()
        return jsonify({"ok": True})

    @app.route("/api/dossiers/merge", methods=["POST"])
    def merge_dossiers_route():
        from db import merge_dossiers
        data = request.json or {}
        keep = data.get("keep")
        merge = data.get("merge")
        if not keep or not merge:
            return jsonify({"error": "Provide 'keep' and 'merge' company names"}), 400
        try:
            conn = get_connection(db_path)
            kept_id, count = merge_dossiers(conn, keep, merge)
            conn.close()
            return jsonify({"ok": True, "kept_id": kept_id, "merged_records": count})
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    # --- Dossier API ---

    @app.route("/api/llm-usage")
    def llm_usage():
        from db import get_llm_usage_stats
        stats = get_llm_usage_stats(db_path)
        return jsonify(stats)

    @app.route("/api/llm-health")
    def llm_health():
        from agents.llm import get_health_status
        return jsonify(get_health_status())

    @app.route("/api/dossiers")
    def list_dossiers():
        hide_empty = request.args.get("hide_empty", "1") == "1"
        conn = get_connection(db_path)
        dossiers = get_all_dossiers(conn, hide_empty=hide_empty)
        conn.close()
        return jsonify(dossiers)

    @app.route("/api/dossiers/<path:company_name>")
    def get_dossier_detail(company_name):
        conn = get_connection(db_path)
        dossier = get_dossier_by_company(conn, company_name)
        if not dossier:
            conn.close()
            return jsonify({"error": "Not found"}), 404

        # Backfill missing key_facts synchronously (one-time per report)
        from agents.llm import extract_key_facts
        for analysis in dossier.get("analyses", []):
            if analysis.get("key_facts_json") or not analysis.get("report_file"):
                continue
            report_path = Path(analysis["report_file"])
            if not report_path.exists():
                continue
            try:
                report_text = report_path.read_text(encoding="utf-8")
                facts = extract_key_facts(company_name, report_text, analysis_type=analysis["analysis_type"])
                if facts:
                    facts_json = json.dumps(facts)
                    conn.execute("UPDATE dossier_analyses SET key_facts_json = ? WHERE id = ?",
                                 (facts_json, analysis["id"]))
                    conn.commit()
                    analysis["key_facts_json"] = facts_json
            except Exception:
                pass

        # Attach lens scores
        from db import get_lens_scores_for_dossier
        lens_scores = get_lens_scores_for_dossier(conn, dossier["id"])
        for s in lens_scores:
            s.pop("score_json", None)
            s.pop("lens_config_json", None)
        dossier["lens_scores"] = lens_scores

        conn.close()
        return jsonify(dossier)

    @app.route("/api/dossiers/<path:company_name>/events", methods=["POST"])
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

    @app.route("/api/dossiers/<path:company_name>/hiring-snapshots")
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

    @app.route("/api/dossiers/<path:company_name>/briefing", methods=["POST"])
    def generate_briefing_api(company_name):
        """Generate or refresh the intelligence briefing for a company."""
        from agents.briefing import generate_briefing

        data = request.json or {}
        lens_id = data.get("lens_id")

        try:
            briefing = generate_briefing(company_name, db_path, lens_id=lens_id)
            return jsonify({"ok": True, "briefing": briefing})
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/dossiers/<path:company_name>/pdf")
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

        # Support both new "scoring" key and legacy "digital_maturity" key
        dm = briefing.get("scoring") or briefing.get("digital_maturity", {})
        overall = dm.get("overall_score", "N/A")
        label = dm.get("overall_label", "")
        score_val = overall if isinstance(overall, int) else 0
        score_color = "#22c55e" if score_val >= 80 else "#3b82f6" if score_val >= 60 else "#f59e0b" if score_val >= 40 else "#ef4444" if score_val >= 20 else "#dc2626"
        subs = dm.get("sub_scores", {})

        # Dynamic score label from lens metadata, fallback for legacy briefings
        lens_info = dm.get("_lens", {})
        score_title = lens_info.get("score_label", "Digital Maturity Score")

        # Dynamic dimensions from lens metadata, fallback for legacy briefings
        dims = dm.get("_dimensions") or [
            {"key": "tech_modernity", "label": "Tech Modernity", "weight": 0.30},
            {"key": "data_analytics", "label": "Data & Analytics", "weight": 0.25},
            {"key": "ai_readiness", "label": "AI Readiness", "weight": 0.25},
            {"key": "organizational_readiness", "label": "Org Readiness", "weight": 0.20},
        ]

        # Build sub-scores table rows from dynamic dimensions
        sub_rows = ""
        for dim in dims:
            s = subs.get(dim["key"], {})
            sub_rows += f"<tr><td>{dim['label']}</td><td><strong>{s.get('score', 'N/A')}</strong>/100</td><td>{s.get('rationale', '')}</td></tr>"

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
        <div class="header-brand">SignalVault<br><span class="header-brand-sub">Competitive Intelligence</span></div>
        <div class="header-company">{company_name}</div>
        <div class="header-meta">Intelligence Briefing &middot; {generated_at}</div>
    </div>

    <div class="score-box">
        <div class="score-number">{overall}</div>
        <div class="score-label">{label}</div>
        <div style="font-size:9px;color:#666;margin-top:4px">{score_title}</div>
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
        Generated by SignalVault &middot; {generated_at}
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

    # --- Lens API ---

    @app.route("/api/lenses")
    def list_lenses_api():
        """List all available lenses."""
        from db import get_all_lenses
        conn = get_connection(db_path)
        lenses = get_all_lenses(conn)
        conn.close()
        # Strip heavy config_json from list response, keep config parsed
        for l in lenses:
            l.pop("config_json", None)
        return jsonify(lenses)

    @app.route("/api/lenses/<int:lens_id>")
    def get_lens_api(lens_id):
        """Get a single lens with full config."""
        from db import get_lens
        conn = get_connection(db_path)
        lens = get_lens(conn, lens_id)
        conn.close()
        if not lens:
            return jsonify({"error": "Lens not found"}), 404
        return jsonify(lens)

    @app.route("/api/lenses", methods=["POST"])
    def create_lens_api():
        """Create a new lens. Body: {name, slug, description, config}"""
        from db import create_lens
        data = request.json or {}
        name = data.get("name", "").strip()
        slug = data.get("slug", "").strip()
        description = data.get("description", "")
        config = data.get("config")
        if not name or not slug or not config:
            return jsonify({"error": "name, slug, and config are required"}), 400
        try:
            conn = get_connection(db_path)
            lens_id = create_lens(conn, name, slug, description, config)
            conn.close()
            return jsonify({"ok": True, "id": lens_id})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/lenses/generate", methods=["POST"])
    def generate_lens_api():
        """LLM-generate a lens config from name + description."""
        from agents.llm import generate_json
        from prompts.lens import build_lens_generation_prompt
        from db import create_lens, get_lens
        data = request.json or {}
        name = data.get("name", "").strip()
        description = data.get("description", "").strip()
        if not name or not description:
            return jsonify({"error": "name and description are required"}), 400
        try:
            prompt = build_lens_generation_prompt(name, description)
            config = generate_json(prompt, timeout=60)
            if not isinstance(config, dict) or "dimensions" not in config:
                return jsonify({"error": "LLM did not produce a valid lens config"}), 500
            # Validate weights sum to ~1.0
            total_weight = sum(d.get("weight", 0) for d in config.get("dimensions", []))
            if abs(total_weight - 1.0) > 0.05:
                # Normalize
                for d in config["dimensions"]:
                    d["weight"] = round(d["weight"] / total_weight, 2)
            slug = name.lower().replace(" ", "-").replace("_", "-")
            slug = "".join(c for c in slug if c.isalnum() or c == "-")[:50]
            conn = get_connection(db_path)
            lens_id = create_lens(conn, name, slug, description, config)
            lens = get_lens(conn, lens_id)
            conn.close()
            return jsonify({"ok": True, "lens": lens})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/lenses/<int:lens_id>", methods=["PUT"])
    def update_lens_api(lens_id):
        """Update a lens config."""
        from db import update_lens
        data = request.json or {}
        try:
            conn = get_connection(db_path)
            update_lens(conn, lens_id,
                       name=data.get("name"), description=data.get("description"),
                       config_json=data.get("config"))
            conn.close()
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/lenses/<int:lens_id>", methods=["DELETE"])
    def delete_lens_api(lens_id):
        """Delete a non-preset lens."""
        from db import delete_lens
        conn = get_connection(db_path)
        deleted = delete_lens(conn, lens_id)
        conn.close()
        if not deleted:
            return jsonify({"error": "Cannot delete preset lens"}), 400
        return jsonify({"ok": True})

    @app.route("/api/dossiers/<path:company_name>/score-lens", methods=["POST"])
    def score_lens_api(company_name):
        """Score a company through a lens. Body: {lens_id, website_url?}"""
        from agents.lens import score_with_lens
        data = request.json or {}
        lens_id = data.get("lens_id")
        if not lens_id:
            return jsonify({"error": "lens_id is required"}), 400
        website_url = data.get("website_url")
        try:
            score_data = score_with_lens(
                company_name, lens_id, db_path=db_path, website_url=website_url
            )
            if score_data:
                # Update campaign scoring_lens_id if this company belongs to any campaign
                from db import get_or_create_dossier, set_campaign_lens
                conn = get_connection(db_path)
                did = get_or_create_dossier(conn, company_name)
                campaign_rows = conn.execute(
                    "SELECT DISTINCT campaign_id FROM campaign_prospects WHERE dossier_id = ?",
                    (did,),
                ).fetchall()
                for cr in campaign_rows:
                    set_campaign_lens(conn, cr["campaign_id"], lens_id)
                conn.close()
                return jsonify({"ok": True, "score": score_data})
            return jsonify({"error": "Failed to generate lens score"}), 500
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/dossiers/<path:company_name>/lens-scores")
    def get_dossier_lens_scores(company_name):
        """Get all lens scores for a company."""
        from db import get_lens_scores_for_dossier, get_or_create_dossier
        conn = get_connection(db_path)
        dossier_id = get_or_create_dossier(conn, company_name)
        scores = get_lens_scores_for_dossier(conn, dossier_id)
        conn.close()
        # Clean up heavy fields for JSON response
        for s in scores:
            s.pop("score_json", None)
            s.pop("lens_config_json", None)
        return jsonify(scores)

    # --- ICP Profile API ---

    @app.route("/api/icp-profiles")
    def list_icp_profiles():
        """List all ICP profiles."""
        from db import get_all_icp_profiles
        conn = get_connection(db_path)
        profiles = get_all_icp_profiles(conn)
        conn.close()
        # Strip large config_json from list response (config is in parsed 'config' key)
        for p in profiles:
            p.pop("config_json", None)
            p.pop("survey_answers_json", None)
        return jsonify(profiles)

    @app.route("/api/icp-profiles/<int:profile_id>")
    def get_icp_profile_route(profile_id):
        """Get a single ICP profile with full config."""
        from db import get_icp_profile
        conn = get_connection(db_path)
        profile = get_icp_profile(conn, profile_id)
        conn.close()
        if not profile:
            return jsonify({"error": "Profile not found"}), 404
        return jsonify(profile)

    @app.route("/api/icp-profiles", methods=["POST"])
    def create_icp_profile_route():
        """Create a new ICP profile."""
        from db import create_icp_profile, set_active_icp_profile
        data = request.json or {}
        name = data.get("name", "").strip()
        config = data.get("config")
        if not name or not config:
            return jsonify({"error": "name and config are required"}), 400
        conn = get_connection(db_path)
        pid = create_icp_profile(
            conn, name, data.get("description", ""),
            json.dumps(config),
            survey_answers_json=json.dumps(data["survey_answers"]) if data.get("survey_answers") else None,
        )
        set_active_icp_profile(conn, pid)
        conn.close()
        return jsonify({"ok": True, "id": pid})

    @app.route("/api/icp-profiles/<int:profile_id>", methods=["PUT"])
    def update_icp_profile_route(profile_id):
        """Update an ICP profile."""
        from db import update_icp_profile
        data = request.json or {}
        conn = get_connection(db_path)
        update_icp_profile(
            conn, profile_id,
            name=data.get("name"),
            description=data.get("description"),
            config_json=json.dumps(data["config"]) if "config" in data else None,
        )
        conn.close()
        return jsonify({"ok": True})

    @app.route("/api/icp-profiles/<int:profile_id>", methods=["DELETE"])
    def delete_icp_profile_route(profile_id):
        """Delete a non-default ICP profile."""
        from db import get_icp_profile, delete_icp_profile, get_active_icp_profile, set_active_icp_profile
        conn = get_connection(db_path)
        profile = get_icp_profile(conn, profile_id)
        if not profile:
            conn.close()
            return jsonify({"error": "Not found"}), 404
        if profile.get("is_default"):
            conn.close()
            return jsonify({"error": "Cannot delete the default profile"}), 400
        delete_icp_profile(conn, profile_id)
        # If deleted profile was active, fall back to default
        active = get_active_icp_profile(conn)
        if not active:
            default_row = conn.execute("SELECT id FROM icp_profiles WHERE is_default = 1").fetchone()
            if default_row:
                set_active_icp_profile(conn, default_row["id"])
        conn.close()
        return jsonify({"ok": True})

    @app.route("/api/icp-profiles/<int:profile_id>/activate", methods=["POST"])
    def activate_icp_profile_route(profile_id):
        """Set a profile as the active one."""
        from db import set_active_icp_profile
        conn = get_connection(db_path)
        set_active_icp_profile(conn, profile_id)
        conn.close()
        return jsonify({"ok": True})

    @app.route("/api/icp-profiles/generate", methods=["POST"])
    def generate_icp_profile_route():
        """Generate an ICP config from wizard survey answers using LLM."""
        data = request.json or {}
        survey_answers = data.get("survey_answers")
        if not survey_answers:
            return jsonify({"error": "survey_answers required"}), 400
        try:
            from prompts.icp_generate import build_icp_generation_prompt
            from agents.llm import generate_json as llm_generate_json, BRIEFING_CHAIN
            prompt = build_icp_generation_prompt(survey_answers)
            config = llm_generate_json(prompt, timeout=90, chain=BRIEFING_CHAIN)
            if not isinstance(config, dict) or "dimensions" not in config:
                return jsonify({"error": "LLM did not return valid ICP config. Try again."}), 500
            # Validate weights sum to ~1.0 and normalize if needed
            total_weight = sum(d.get("weight", 0) for d in config.get("dimensions", []))
            if abs(total_weight - 1.0) > 0.05:
                for d in config["dimensions"]:
                    d["weight"] = round(d["weight"] / total_weight, 2)
                # Fix rounding: adjust first dimension to make sum exactly 1.0
                remainder = 1.0 - sum(d["weight"] for d in config["dimensions"])
                if config["dimensions"]:
                    config["dimensions"][0]["weight"] = round(config["dimensions"][0]["weight"] + remainder, 2)
            return jsonify({"ok": True, "config": config, "survey_answers": survey_answers})
        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    # --- Prospecting API ---

    @app.route("/api/ua-targets")
    def list_ua_targets():
        """Get all companies with ICP fit scores, filtered by active ICP profile."""
        from db import get_ua_targets, get_active_icp_profile
        conn = get_connection(db_path)
        # Filter by ICP profile if specified, otherwise use active profile
        icp_profile_id = request.args.get("icp_profile_id", type=int)
        if icp_profile_id is None:
            active = get_active_icp_profile(conn)
            if active:
                icp_profile_id = active["id"]
        targets = get_ua_targets(conn, icp_profile_id=icp_profile_id)
        conn.close()
        return jsonify(targets)

    @app.route("/api/dossiers/<path:company_name>/ua-fit", methods=["POST"])
    def compute_ua_fit(company_name):
        """Score a single company's prospect fit using research analysis reports."""
        from agents.ua_fit import score_ua_fit
        data = request.json or {}
        website_url = data.get("website_url")
        try:
            fit = score_ua_fit(company_name, website_url=website_url, db_path=db_path)
            if fit:
                return jsonify({"ok": True, "score": fit})
            return jsonify({"error": "Failed to generate fit score"}), 500
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # --- Campaign API ---

    @app.route("/api/campaigns")
    def list_campaigns():
        """Get root campaigns (sidebar) with children tree and prospect data."""
        from db import get_root_campaigns, get_campaign_detail, get_campaign_tree
        conn = get_connection(db_path)
        campaigns = get_root_campaigns(conn)
        for c in campaigns:
            detail = get_campaign_detail(conn, c["id"])
            if detail:
                c["prospects"] = detail.get("prospects", [])
                c["insight"] = detail.get("insight")
                c["execution_log"] = detail.get("execution_log")
                c["niche_eval"] = detail.get("niche_eval")
                c["scoring_lens_id"] = detail.get("scoring_lens_id")
            else:
                c["prospects"] = []
            # Attach child campaigns for tree rendering in Pane 2
            tree = get_campaign_tree(conn, c["id"])
            children = [n for n in tree if n["id"] != c["id"]]
            for ch in children:
                ch_detail = get_campaign_detail(conn, ch["id"])
                if ch_detail:
                    ch["prospects"] = ch_detail.get("prospects", [])
                    ch["insight"] = ch_detail.get("insight")
                    ch["execution_log"] = ch_detail.get("execution_log")
                    ch["niche_eval"] = ch_detail.get("niche_eval")
                    ch["scoring_lens_id"] = ch_detail.get("scoring_lens_id")
                else:
                    ch["prospects"] = []
            c["children"] = children
        conn.close()
        return jsonify(campaigns)

    @app.route("/api/campaigns/<int:campaign_id>")
    def get_campaign(campaign_id):
        """Get a single campaign with its prospects joined to dossier ua_fit data."""
        from db import get_campaign_detail
        conn = get_connection(db_path)
        campaign = get_campaign_detail(conn, campaign_id)
        conn.close()
        if not campaign:
            return jsonify({"error": "Campaign not found"}), 404
        return jsonify(campaign)

    @app.route("/api/campaigns/<int:campaign_id>/tree")
    def get_campaign_tree_api(campaign_id):
        """Get the full tree of campaigns rooted at campaign_id."""
        from db import get_campaign_tree, get_campaign_detail
        conn = get_connection(db_path)
        nodes = get_campaign_tree(conn, campaign_id)
        for node in nodes:
            detail = get_campaign_detail(conn, node["id"])
            node["prospects"] = detail.get("prospects", []) if detail else []
        conn.close()
        return jsonify(nodes)

    @app.route("/api/campaigns/<int:campaign_id>", methods=["PATCH"])
    def update_campaign(campaign_id):
        """Rename a campaign."""
        from db import rename_campaign
        data = request.json or {}
        name = data.get("name", "").strip()
        if not name:
            return jsonify({"error": "name is required"}), 400
        conn = get_connection(db_path)
        rename_campaign(conn, campaign_id, name)
        conn.close()
        return jsonify({"ok": True})

    @app.route("/api/campaigns/<int:campaign_id>", methods=["DELETE"])
    def remove_campaign(campaign_id):
        """Delete a campaign and its prospect links (not the dossiers)."""
        from db import delete_campaign
        conn = get_connection(db_path)
        delete_campaign(conn, campaign_id)
        conn.close()
        return jsonify({"ok": True})

    @app.route("/api/campaign-prospects/<int:campaign_id>/<int:dossier_id>", methods=["PATCH"])
    def update_campaign_prospect(campaign_id, dossier_id):
        """Update a prospect's workflow status."""
        from db import update_prospect_status
        data = request.json or {}
        status = data.get("prospect_status", "").strip()
        if status not in ("new", "reviewing", "brief_ready", "contacted"):
            return jsonify({"error": "Invalid prospect_status"}), 400
        conn = get_connection(db_path)
        update_prospect_status(conn, campaign_id, dossier_id, status)
        conn.close()
        return jsonify({"ok": True})

    @app.route("/api/campaigns/<int:campaign_id>/insight", methods=["POST"])
    def generate_campaign_insight(campaign_id):
        """Generate a vertical insight for a campaign (lens-aware)."""
        # Check if campaign has lens scores — use lens insight if so
        from db import get_campaign_detail
        conn = get_connection(db_path)
        campaign = get_campaign_detail(conn, campaign_id)
        conn.close()
        has_lens = campaign and any(p.get("lens_score") for p in (campaign.get("prospects") or []))
        if has_lens:
            from agents.lens import generate_lens_vertical_insight
            insight = generate_lens_vertical_insight(campaign_id, db_path=db_path)
        else:
            from agents.ua_fit import generate_vertical_insight
            insight = generate_vertical_insight(campaign_id, db_path=db_path)
        if not insight:
            return jsonify({"error": "Could not generate insight"}), 500
        return jsonify(insight)

    @app.route("/api/campaigns/<int:campaign_id>/prospects/<path:company_name>/brief", methods=["POST"])
    def generate_prospect_brief(campaign_id, company_name):
        """Generate an outreach brief for a prospect in a campaign."""
        from agents.ua_fit import generate_outreach_brief
        brief = generate_outreach_brief(company_name, campaign_id, db_path=db_path)
        if not brief:
            return jsonify({"error": "Could not generate brief"}), 500
        return jsonify(brief)

    @app.route("/api/send-to-research", methods=["POST"])
    def send_to_research():
        """Mark selected companies from discovery for research.
        Ensures dossiers exist and saves website_url if present.
        """
        from db import get_or_create_dossier
        data = request.json or {}
        companies = data.get("companies", [])
        if not companies or len(companies) > 3:
            return jsonify({"error": "Select 1-3 companies"}), 400

        conn = get_connection(db_path)
        dossier_names = []
        for c in companies:
            name = (c.get("name") or "").strip()
            if not name:
                continue
            dossier_id = get_or_create_dossier(conn, name)
            website = c.get("website_url") or c.get("website")
            if website:
                conn.execute(
                    "UPDATE dossiers SET website_url = ? WHERE id = ? AND (website_url IS NULL OR website_url = '')",
                    (website, dossier_id),
                )
            dossier_names.append(name)
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "companies": dossier_names})

    @app.route("/api/ua-pipeline", methods=["POST"])
    def ua_pipeline_api():
        """Run the prospecting pipeline with SSE progress streaming.

        Pipeline: Discover -> Validate websites -> Save & Complete.
        Scoring happens separately in Research via lens system.
        """
        data = request.json or {}
        niche = data.get("niche", "").strip()
        top_n = min(data.get("top_n", 10), 20)
        niche_context = data.get("context", {})  # structured fields from Niche Builder
        seed_company = data.get("seed_company", "").strip()  # "Find Similar" mode
        parent_campaign_id = data.get("parent_campaign_id")  # child campaign link
        if not niche:
            return jsonify({"error": "niche is required"}), 400

        def generate():
            import queue
            import threading
            from concurrent.futures import ThreadPoolExecutor, as_completed

            campaign_id = None

            try:
                # ---- Phase 1: Discovery (with progress streaming) ----
                # Depth check for "Find Similar" mode
                if seed_company and parent_campaign_id:
                    from db import get_campaign_depth
                    _depth_conn = get_connection(db_path)
                    depth = get_campaign_depth(_depth_conn, parent_campaign_id)
                    _depth_conn.close()
                    if depth >= 3:
                        yield f"data: {json.dumps({'type': 'error', 'text': 'Maximum expansion depth (3) reached.'})}\n\n"
                        return

                if seed_company:
                    yield f"data: {json.dumps({'type': 'status', 'text': f'Finding companies similar to: {seed_company}...'})}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'status', 'text': f'Discovering companies in: {niche}...'})}\n\n"

                from agents.discover import discover_prospects, discover_similar

                disc_q = queue.Queue()
                disc_holder = [None]
                execution_log = []  # collect search events for persistence

                def _disc_cb(event_type, ev_data):
                    disc_q.put((event_type, ev_data))

                def _run_discovery():
                    try:
                        if seed_company:
                            result = discover_similar(
                                seed_company, top_n=top_n, db_path=db_path,
                                progress_cb=_disc_cb,
                            )
                        else:
                            result = discover_prospects(
                                niche, top_n=top_n, db_path=db_path,
                                context=niche_context, progress_cb=_disc_cb,
                            )
                        disc_holder[0] = result
                    except Exception as exc:
                        print(f"[pipeline] Discovery error: {exc}")
                        disc_holder[0] = []
                    finally:
                        disc_q.put(("_done", None))

                dt = threading.Thread(target=_run_discovery, daemon=True)
                dt.start()

                while True:
                    try:
                        ev_type, ev_data = disc_q.get(timeout=0.2)
                    except queue.Empty:
                        continue
                    if ev_type == "_done":
                        break
                    # Collect all meaningful events for execution log persistence
                    if ev_type in ("discovery_plan", "search_start", "search_done",
                                   "search_complete", "extracting", "extracted",
                                   "seed_profile"):
                        execution_log.append({"type": ev_type, **(ev_data or {})})
                    yield f"data: {json.dumps({'type': ev_type, **(ev_data or {})})}\n\n"

                dt.join(timeout=300)
                companies = disc_holder[0] or []

                # Create campaign record (before early-return so failed searches persist)
                from db import (create_campaign, add_campaign_prospect,
                                update_campaign_status, get_or_create_dossier,
                                save_campaign_execution_log)
                conn = get_connection(db_path)
                campaign_id = create_campaign(
                    conn, niche, top_n,
                    parent_campaign_id=parent_campaign_id or None,
                    seed_company=seed_company or None,
                )

                # Persist execution log (search queries, results, etc.)
                if execution_log:
                    save_campaign_execution_log(conn, campaign_id, execution_log)

                if not companies:
                    update_campaign_status(conn, campaign_id, "empty")
                    conn.close()
                    yield f"data: {json.dumps({'type': 'error', 'text': 'No companies found for this niche.', 'campaign_id': campaign_id})}\n\n"
                    return

                conn.close()

                yield f"data: {json.dumps({'type': 'discovered', 'companies': companies, 'campaign_id': campaign_id})}\n\n"

                # ---- Phase 2: Website Validation ----
                yield f"data: {json.dumps({'type': 'status', 'text': f'Validating {len(companies)} company websites...'})}\n\n"

                from agents.ua_fit import validate_websites

                valid_q = queue.Queue()
                valid_holder = [None]

                def _valid_cb(event_type, ev_data):
                    valid_q.put((event_type, ev_data))

                def _run_validation():
                    try:
                        valid, results = validate_websites(companies, progress_cb=_valid_cb)
                        valid_holder[0] = (valid, results)
                    except Exception as exc:
                        print(f"[pipeline] Validation error: {exc}")
                        valid_holder[0] = (companies, [])
                    finally:
                        valid_q.put(("_done", None))

                vt = threading.Thread(target=_run_validation, daemon=True)
                vt.start()

                while True:
                    try:
                        ev_type, ev_data = valid_q.get(timeout=0.2)
                    except queue.Empty:
                        continue
                    if ev_type == "_done":
                        break
                    # Collect validation events for execution log
                    if ev_type in ("validating", "validated"):
                        execution_log.append({"type": ev_type, **(ev_data or {})})
                    yield f"data: {json.dumps({'type': ev_type, **ev_data})}\n\n"

                vt.join(timeout=120)

                valid_companies, validation_results = valid_holder[0]
                rejected = [v for v in (validation_results or []) if not v.get("valid")]

                # Build discovery lookup for persistence
                discovery_lookup = {}
                for c in companies:
                    cname = (c.get("name") or "").strip()
                    if cname:
                        discovery_lookup[cname.lower()] = json.dumps({
                            "description": c.get("description", ""),
                            "estimated_size": c.get("estimated_size", ""),
                            "why_included": c.get("why_included", ""),
                            "evidence": c.get("evidence", []),
                            "website": c.get("website", ""),
                        })

                # Persist campaign_prospects with validation status + discovery data
                conn = get_connection(db_path)
                for vr in (validation_results or []):
                    name = vr.get("name", "")
                    dossier_id = get_or_create_dossier(conn, name)
                    if not vr.get("valid"):
                        vstatus = "parked"
                    elif vr.get("limited"):
                        vstatus = "http_403" if "403" in (vr.get("reason") or "") else "connection_failed"
                    else:
                        vstatus = "valid"
                    add_campaign_prospect(conn, campaign_id, dossier_id,
                                          validation_status=vstatus,
                                          validation_reason=vr.get("reason"),
                                          discovery_json=discovery_lookup.get(name.strip().lower()))
                conn.close()

                limited_count = sum(1 for v in (validation_results or []) if v.get("limited"))
                yield f"data: {json.dumps({'type': 'validation_complete', 'valid_count': len(valid_companies), 'rejected_count': len(rejected), 'limited_count': limited_count})}\n\n"

                if not valid_companies:
                    conn = get_connection(db_path)
                    update_campaign_status(conn, campaign_id, 'error')
                    conn.close()
                    yield f"data: {json.dumps({'type': 'error', 'text': 'No valid companies after website validation.'})}\n\n"
                    return

                # ---- Phase 2.5: Lightweight Financial Scan ----
                yield f"data: {json.dumps({'type': 'status', 'text': f'Scanning financial data for {len(valid_companies)} companies...'})}\n\n"

                from agents.niche_eval import scan_niche_financials, compute_niche_aggregates
                from db import save_financial_snapshot, save_niche_evaluation

                scan_q = queue.Queue()
                scan_holder = [None]

                def _scan_cb(event_type, ev_data):
                    scan_q.put((event_type, ev_data))

                def _run_scan():
                    try:
                        results = scan_niche_financials(valid_companies, progress_cb=_scan_cb)
                        scan_holder[0] = results
                    except Exception as exc:
                        print(f"[pipeline] Niche scan error: {exc}")
                        scan_holder[0] = []
                    finally:
                        scan_q.put(("_done", None))

                st = threading.Thread(target=_run_scan, daemon=True)
                st.start()

                while True:
                    try:
                        ev_type, ev_data = scan_q.get(timeout=0.2)
                    except queue.Empty:
                        continue
                    if ev_type == "_done":
                        break
                    yield f"data: {json.dumps({'type': ev_type, **(ev_data or {})})}\n\n"

                st.join(timeout=180)

                scan_results = scan_holder[0] or []

                # Save per-company snapshots to dossiers
                if scan_results:
                    conn = get_connection(db_path)
                    for snap in scan_results:
                        snap_name = snap.get("company_name", "")
                        if snap_name and snap.get("data_quality", "none") != "none":
                            did = get_or_create_dossier(conn, snap_name)
                            save_financial_snapshot(conn, did, snap)
                    conn.close()

                # Compute and save niche aggregates
                niche_eval = compute_niche_aggregates(scan_results)
                conn = get_connection(db_path)
                save_niche_evaluation(conn, campaign_id, niche_eval)
                conn.close()

                yield f"data: {json.dumps({'type': 'niche_eval_complete', 'niche_eval': niche_eval})}\n\n"

                # ---- Phase 3: Save website URLs + Complete ----
                # Only save websites that actually validated — skip bad URLs
                bad_websites = {
                    vr.get("name", "").strip().lower()
                    for vr in (validation_results or [])
                    if vr.get("limited")
                }
                conn = get_connection(db_path)
                for company in valid_companies:
                    name = company.get("name", "")
                    website = company.get("website")
                    if name and website and name.strip().lower() not in bad_websites:
                        dossier_id = get_or_create_dossier(conn, name)
                        conn.execute(
                            "UPDATE dossiers SET website_url = ? WHERE id = ? AND (website_url IS NULL OR website_url = '')",
                            (website, dossier_id),
                        )
                conn.commit()
                update_campaign_status(conn, campaign_id, 'complete')
                # Re-save execution log with validation events included
                if execution_log:
                    save_campaign_execution_log(conn, campaign_id, execution_log)
                conn.close()

                yield f"data: {json.dumps({'type': 'complete', 'total_discovered': len(valid_companies), 'campaign_id': campaign_id})}\n\n"

            except Exception as e:
                import traceback
                traceback.print_exc()
                if campaign_id:
                    try:
                        conn = get_connection(db_path)
                        update_campaign_status(conn, campaign_id, 'error')
                        conn.close()
                    except Exception:
                        pass
                yield f"data: {json.dumps({'type': 'error', 'text': f'Pipeline error: {str(e)[:300]}'})}\n\n"

        return Response(generate(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # --- Unified Companies API ---

    @app.route("/api/companies")
    def list_companies():
        """Unified company list merging dossier data with orphan reports."""
        conn = get_connection(db_path)
        hide_empty = request.args.get("hide_empty", "1") == "1"
        dossiers = get_all_dossiers(conn, hide_empty=hide_empty)

        # Get all analyses with report_file for each dossier
        all_analyses = conn.execute(
            """SELECT da.id, da.dossier_id, da.analysis_type, da.report_file,
                      da.created_at, d.company_name
               FROM dossier_analyses da
               JOIN dossiers d ON da.dossier_id = d.id
               ORDER BY da.created_at DESC"""
        ).fetchall()
        conn.close()

        # Build company objects from dossiers
        companies = {}
        for dos in dossiers:
            name = dos["company_name"]
            companies[name] = {
                "name": name,
                "sector": dos.get("sector") or "",
                "analysis_count": dos.get("analysis_count", 0),
                "event_count": dos.get("event_count", 0),
                "has_briefing": bool(dos.get("briefing_json")),
                "briefing_generated_at": dos.get("briefing_generated_at"),
                "last_updated": dos.get("updated_at") or dos.get("last_analysis_at") or "",
                "analyses": [],
                "orphan_reports": [],
            }

        # Attach analyses to companies (deduplicate by report_file)
        reports_dir = Path("reports")
        seen_report_files = set()
        for a in all_analyses:
            name = a["company_name"]
            if name not in companies:
                continue
            report_basename = os.path.basename(a["report_file"]) if a["report_file"] else None
            # Skip duplicate entries pointing to the same file (keep the first,
            # which is the most recent since results are ordered by created_at DESC)
            if report_basename and report_basename in seen_report_files:
                continue
            if report_basename:
                seen_report_files.add(report_basename)
            has_report = bool(report_basename and (reports_dir / report_basename).exists())
            date_str = (a["created_at"] or "")[:19]
            companies[name]["analyses"].append({
                "id": a["id"],
                "type": a["analysis_type"],
                "report_file": report_basename,
                "date": date_str,
                "has_report": has_report,
            })

        # Find orphan reports (on disk but not in any dossier_analyses)
        db_report_basenames = set()
        for a in all_analyses:
            if a["report_file"]:
                db_report_basenames.add(os.path.basename(a["report_file"]))

        if reports_dir.exists():
            for f in reports_dir.glob("*.md"):
                if f.name not in db_report_basenames:
                    info = _parse_report_filename(f.name)
                    matched = False
                    for cname in companies:
                        if cname.lower() == info["company"].lower():
                            companies[cname]["orphan_reports"].append({
                                "filename": f.name, "type": info["type"], "date": info["date"],
                            })
                            matched = True
                            break
                    if not matched:
                        pname = info["company"]
                        if pname not in companies:
                            companies[pname] = {
                                "name": pname, "sector": "", "analysis_count": 0,
                                "event_count": 0, "has_briefing": False,
                                "last_updated": "", "analyses": [], "orphan_reports": [],
                            }
                        companies[pname]["orphan_reports"].append({
                            "filename": f.name, "type": info["type"], "date": info["date"],
                        })

        result = sorted(companies.values(), key=lambda c: c["last_updated"] or "", reverse=True)
        return jsonify(result)

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
            yield from _generate_inner(history, today, db_path)
          except Exception as e:
            import traceback
            traceback.print_exc()
            yield f"data: {json.dumps({'type': 'error', 'text': f'Server error: {str(e)[:300]}'})}\n\n"

        def _generate_inner(history, today, db_path):
            try:
                llm = ChatLLM()
            except RuntimeError as e:
                yield f"data: {json.dumps({'type': 'error', 'text': str(e)})}\n\n"
                return

            max_rounds = 15
            # Build date suffix once for reuse in condensed prompt
            date_suffix = f"\n\n[TODAY] The current date is {today}. Use {datetime.now().year} in searches."

            for round_num in range(max_rounds):
                # Dynamic tool selection: full tools on round 1, core tools after
                # This drops from ~17K chars of schemas to ~6K on follow-up rounds
                if round_num == 0:
                    current_tools = TOOL_SCHEMAS
                else:
                    current_tools = get_tool_schemas("follow_up")
                    # Swap to condensed system prompt to save ~8K chars
                    if history and history[0].get("role") == "system":
                        history[0]["content"] = CONDENSED_SYSTEM_PROMPT + date_suffix

                # Compress old tool results as safety net
                _compress_history(history)

                try:
                    response = llm.chat(history, tools=current_tools,
                                        force_tools=(round_num == 0))
                except RuntimeError as e:
                    error_msg = str(e).lower()
                    print(f"[chat] LLM error: {e}")

                    # Check rate limit FIRST — TPM/RPM errors contain "token"
                    # and "limit" which false-match context overflow detection
                    is_rate = any(kw in error_msg for kw in [
                        "rate limit", "429", "413", "quota", "resource_exhausted",
                        "tokens per minute", "requests per minute", "tpm", "rpm",
                    ])
                    is_context = (not is_rate) and any(kw in error_msg for kw in [
                        "context", "length", "too long", "too large",
                        "maximum", "reduce", "exceed",
                    ])

                    if is_context or (not is_rate and len(str(history)) > 50000):
                        # Nuclear trim: condensed system + last user message only, no tools
                        last_user = None
                        for msg in reversed(history):
                            if msg.get("role") == "user":
                                last_user = msg
                                break
                        if not last_user:
                            last_user = {"role": "user", "content": "Please summarize what you found so far."}

                        # Use condensed system prompt + no tools to minimize context
                        condensed_sys = {"role": "system", "content": CONDENSED_SYSTEM_PROMPT + date_suffix}
                        history_trimmed = [condensed_sys, last_user]
                        try:
                            response = llm.chat(history_trimmed, tools=None)
                        except RuntimeError as e2:
                            print(f"[chat] Retry also failed: {e2}")
                            yield f"data: {json.dumps({'type': 'error', 'text': 'Context too large — try starting a new chat.'})}\n\n"
                            return
                    elif is_rate:
                        yield f"data: {json.dumps({'type': 'error', 'text': 'Rate limited — all AI providers are temporarily exhausted. Wait a minute and try again.'})}\n\n"
                        return
                    else:
                        yield f"data: {json.dumps({'type': 'error', 'text': f'LLM error: {str(e)[:200]}'})}\n\n"
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

                        def _structured_cb(*args):
                            """Handle both string progress and structured (event_type, data) callbacks."""
                            if len(args) == 1:
                                progress_q.put(args[0])  # plain string
                            elif len(args) >= 2:
                                # Structured event: (event_type, data_dict)
                                evt, data = args[0], args[1] if len(args) > 1 else {}
                                progress_q.put({"_structured": True, "event": evt, **(data if isinstance(data, dict) else {"detail": str(data)})})

                        def _run(name=fn_name, args=fn_args):
                            try:
                                result_box[0] = _execute_tool(
                                    name, args, db_path,
                                    progress_callback=_structured_cb,
                                )
                            except Exception as e:
                                result_box[0] = f"Tool error: {e}"

                        t = threading.Thread(target=_run)
                        t.start()

                        def _emit_progress(msg):
                            """Emit a progress message as SSE, handling both strings and structured dicts."""
                            if isinstance(msg, dict) and msg.get("_structured"):
                                # Structured event from analysis agents — emit as tool_progress_structured
                                payload = {k: v for k, v in msg.items() if k != "_structured"}
                                return f"data: {json.dumps({'type': 'tool_progress', 'name': fn_name, 'structured': True, **payload})}\n\n"
                            else:
                                return f"data: {json.dumps({'type': 'tool_progress', 'name': fn_name, 'text': str(msg)})}\n\n"

                        while t.is_alive():
                            try:
                                msg = progress_q.get(timeout=2)
                                yield _emit_progress(msg)
                            except queue.Empty:
                                # Send SSE keepalive comment to prevent connection timeout
                                yield ": keepalive\n\n"

                        # Drain remaining progress messages
                        while not progress_q.empty():
                            try:
                                msg = progress_q.get_nowait()
                                yield _emit_progress(msg)
                            except queue.Empty:
                                break

                        result = result_box[0] or "Tool returned no result."

                        if len(result) > MAX_TOOL_RESULT_CHARS:
                            result = result[:MAX_TOOL_RESULT_CHARS] + "\n\n... (truncated)"

                        yield f"data: {json.dumps({'type': 'tool_result', 'name': fn_name, 'result': result})}\n\n"

                        # Summarize for history to keep context lean (multi-step LLM approach)
                        # User sees full result above; only the summary goes into LLM context
                        history_content = _summarize_tool_result(fn_name, result)
                        history.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": history_content,
                        })

                    continue

                else:
                    text = response.get("content", "")
                    yield f"data: {json.dumps({'type': 'message', 'text': text})}\n\n"
                    return

            yield f"data: {json.dumps({'type': 'error', 'text': 'Reached the maximum number of tool calls for this query. Here is what I found so far.'})}\n\n"

        return Response(generate(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ── Signal routes ─────────────────────────────────────────────────

    @app.route("/api/signals/scan", methods=["POST"])
    def signals_scan_api():
        """Scan for signals across all or specific domains, then auto-synthesize into threads. SSE-streamed."""
        data = request.json or {}
        domains = data.get("domains")  # list of domain names, or None for all
        auto_synthesize = data.get("auto_synthesize", True)

        def generate():
            from agents.signals_collect import collect_all_domains, collect_domain_signals, ALL_DOMAINS
            from db import insert_signals_batch, get_signals

            scan_q = queue.Queue()

            def _cb(event_type, ev_data):
                scan_q.put((event_type, ev_data or {}))

            result_box = [None]
            synth_result = [None]  # initialized here so save_scan_history always has access

            def _run_scan():
                try:
                    if domains:
                        all_sigs = []
                        for dom in domains:
                            sigs = collect_domain_signals(dom, max_per_source=8, progress_cb=_cb)
                            all_sigs.extend(sigs)
                        result_box[0] = all_sigs
                    else:
                        result_box[0] = collect_all_domains(max_per_source=8, progress_cb=_cb)
                except Exception as exc:
                    print(f"[signals] Scan error: {exc}")
                    scan_q.put(("error", {"text": str(exc)}))
                    result_box[0] = []
                finally:
                    scan_q.put(("_done", {}))

            t = threading.Thread(target=_run_scan, daemon=True)
            t.start()

            while True:
                try:
                    ev_type, ev_data = scan_q.get(timeout=0.3)
                except queue.Empty:
                    yield ": keepalive\n\n"
                    continue
                if ev_type == "_done":
                    break
                yield f"data: {json.dumps({'type': ev_type, **ev_data})}\n\n"

            t.join(timeout=300)
            signals = result_box[0] or []

            # Persist to DB
            conn = get_connection(db_path)
            new_count = insert_signals_batch(conn, signals)

            yield f"data: {json.dumps({'type': 'scan_complete', 'total_collected': len(signals), 'new_inserted': new_count})}\n\n"

            # Auto-synthesize: group new signals into threads
            if auto_synthesize and new_count > 0:
                yield f"data: {json.dumps({'type': 'status', 'text': 'Synthesizing signals into threads...'})}\n\n"

                from agents.signals_synthesize import synthesize_into_threads, enrich_thread_signals, extract_entities

                # Fetch the recently inserted signals (last 1 day to catch this scan)
                recent = get_signals(conn, days_back=1, limit=300)

                synth_q = queue.Queue()
                synth_result = [None]

                def _synth_cb(event_type, ev_data):
                    synth_q.put((event_type, ev_data or {}))

                def _run_synth():
                    try:
                        result = synthesize_into_threads(conn, recent, progress_cb=_synth_cb)
                        synth_result[0] = result
                        # Fetch full article text for signals in threads
                        _synth_cb("status", {"text": "Fetching article text for thread signals..."})
                        enrich_thread_signals(conn, progress_cb=_synth_cb)
                        # Re-read enriched signals for entity extraction
                        enriched = get_signals(conn, days_back=1, limit=300)
                        _synth_cb("status", {"text": "Extracting entities..."})
                        extract_entities(conn, enriched, progress_cb=_synth_cb)
                    except Exception as exc:
                        print(f"[signals] Synthesis error: {exc}")
                        synth_q.put(("synth_error", {"text": str(exc)}))
                    finally:
                        synth_q.put(("_synth_done", {}))

                st = threading.Thread(target=_run_synth, daemon=True)
                st.start()

                while True:
                    try:
                        ev_type, ev_data = synth_q.get(timeout=0.5)
                    except queue.Empty:
                        yield ": keepalive\n\n"
                        continue
                    if ev_type == "_synth_done":
                        break
                    yield f"data: {json.dumps({'type': ev_type, **ev_data})}\n\n"

                st.join(timeout=120)
                sr = synth_result[0] or {}
                yield f"data: {json.dumps({'type': 'threads_ready', 'assigned': sr.get('assigned_count', 0), 'new_threads': sr.get('new_thread_count', 0)})}\n\n"

            # Save scan history (last 3 only)
            from db import save_scan_history
            _sr = synth_result[0] or {}
            save_scan_history(conn, {
                "total_collected": len(signals),
                "new_inserted": new_count,
                "threads_created": _sr.get("new_thread_count", 0),
                "threads_assigned": _sr.get("assigned_count", 0),
            })

            conn.close()

        return Response(generate(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.route("/api/signals", methods=["GET"])
    def signals_list_api():
        """Fetch signals with optional domain filter."""
        domain = request.args.get("domain")
        days_back = int(request.args.get("days_back", 7))
        limit = int(request.args.get("limit", 200))

        from db import get_signals
        conn = get_connection(db_path)
        signals = get_signals(conn, domain=domain, days_back=days_back, limit=limit)
        conn.close()
        return jsonify({"signals": signals})

    @app.route("/api/signals/threads", methods=["GET"])
    def signals_threads_api():
        """Fetch signal threads with momentum data."""
        domain = request.args.get("domain")
        status = request.args.get("status", "active")
        limit = int(request.args.get("limit", 50))

        from db import get_signal_clusters
        from agents.signals_synthesize import compute_thread_momentum

        conn = get_connection(db_path)
        threads = get_signal_clusters(conn, domain=domain, status=status, limit=limit)

        # Enrich with momentum
        for t in threads:
            t["momentum"] = compute_thread_momentum(conn, t["id"])

        conn.close()
        return jsonify({"threads": threads})

    @app.route("/api/signals/clusters", methods=["GET"])
    def signals_clusters_api():
        """Fetch signal clusters (alias for threads, backwards compat)."""
        domain = request.args.get("domain")
        status = request.args.get("status", "active")
        limit = int(request.args.get("limit", 50))

        from db import get_signal_clusters
        conn = get_connection(db_path)
        clusters = get_signal_clusters(conn, domain=domain, status=status, limit=limit)
        conn.close()
        return jsonify({"clusters": clusters})

    @app.route("/api/signals/threads/<int:thread_id>", methods=["GET"])
    def signals_thread_detail_api(thread_id):
        """Fetch a single thread with signals, entities, and momentum."""
        from db import get_cluster_detail
        from agents.signals_synthesize import compute_thread_momentum

        conn = get_connection(db_path)
        detail = get_cluster_detail(conn, thread_id)
        if not detail:
            conn.close()
            return jsonify({"error": "Thread not found"}), 404

        detail["momentum"] = compute_thread_momentum(conn, thread_id)

        # Get entities for this thread's signals
        entities = conn.execute(
            "SELECT * FROM signal_entities WHERE cluster_id = ? OR signal_id IN "
            "(SELECT signal_id FROM signal_cluster_items WHERE cluster_id = ?)",
            (thread_id, thread_id),
        ).fetchall()
        detail["entities"] = [dict(e) for e in entities]

        conn.close()
        return jsonify(detail)

    @app.route("/api/signals/clusters/<int:cluster_id>", methods=["GET"])
    def signals_cluster_detail_api(cluster_id):
        """Fetch a single cluster with signals and entities."""
        from db import get_cluster_detail
        conn = get_connection(db_path)
        detail = get_cluster_detail(conn, cluster_id)
        conn.close()
        if not detail:
            return jsonify({"error": "Cluster not found"}), 404
        return jsonify(detail)

    @app.route("/api/signals/<int:signal_id>/fetch-article", methods=["POST"])
    def signals_fetch_article_api(signal_id):
        """Fetch full article text for a signal on demand."""
        from scraper.web_search import fetch_page_text

        conn = get_connection(db_path)
        row = conn.execute("SELECT id, url, body FROM signals WHERE id = ?", (signal_id,)).fetchone()
        if not row:
            conn.close()
            return jsonify({"error": "Signal not found"}), 404

        url = row["url"]
        if not url:
            conn.close()
            return jsonify({"error": "Signal has no URL"}), 400

        # Fetch article text
        text = fetch_page_text(url, max_chars=5000)
        if text and len(text) > 100:
            conn.execute("UPDATE signals SET body = ? WHERE id = ?", (text, signal_id))
            conn.commit()
            conn.close()
            return jsonify({"ok": True, "body": text, "chars": len(text)})

        conn.close()
        return jsonify({"ok": False, "body": row["body"] or "", "error": "Could not extract article text"})

    @app.route("/api/signals/search", methods=["POST"])
    def signals_targeted_search_api():
        """Run a targeted signal search for a specific query. Optionally link results to a pattern."""
        from datetime import datetime, timedelta

        data = request.json or {}
        query = data.get("query", "").strip()
        pattern_id = data.get("pattern_id")  # optional: link new signals to this pattern
        if not query:
            return jsonify({"error": "query required"}), 400

        from scraper.google_news import search_google_news
        from scraper.hackernews import search_stories
        from agents.signals_collect import _normalize_signal
        from db import insert_signal, link_signal_to_cluster

        cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

        # Track audit data per source
        audit = {"sources": [], "filtered_stale": 0}

        results = []
        # Search Google News
        news_raw = search_google_news(query, max_results=12, days_back=30)
        news_fresh = []
        for item in news_raw:
            sig = _normalize_signal(item, "google_news", "targeted")
            if not sig:
                continue
            # Filter stale: drop if published_at is set and older than cutoff
            pub = sig.get("published_at", "")
            if pub and pub < cutoff:
                audit["filtered_stale"] += 1
                continue
            news_fresh.append(sig)
            results.append(sig)
        audit["sources"].append({"source": "Google News", "query": query, "raw": len(news_raw), "after_filter": len(news_fresh)})

        # Search HackerNews
        hn_raw = search_stories(query, max_results=8, sort="date")
        hn_fresh = []
        for item in hn_raw:
            sig = _normalize_signal(item, "hackernews", "targeted")
            if not sig:
                continue
            pub = sig.get("published_at", "")
            if pub and pub[:10] < cutoff:
                audit["filtered_stale"] += 1
                continue
            hn_fresh.append(sig)
            results.append(sig)
        audit["sources"].append({"source": "Hacker News", "query": query, "raw": len(hn_raw), "after_filter": len(hn_fresh)})

        conn = get_connection(db_path)
        new_count = 0
        linked_count = 0
        for sig in results:
            sig_id = insert_signal(conn, sig)
            if sig_id:
                new_count += 1
                if pattern_id:
                    link_signal_to_cluster(conn, pattern_id, sig_id)
                    linked_count += 1
            elif pattern_id:
                existing = conn.execute(
                    "SELECT id FROM signals WHERE content_hash = ?", (sig["content_hash"],)
                ).fetchone()
                if existing:
                    link_signal_to_cluster(conn, pattern_id, existing["id"])
                    linked_count += 1
        conn.commit()

        if pattern_id and linked_count > 0:
            conn.execute(
                "UPDATE signal_clusters SET last_signal_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (pattern_id,),
            )
            conn.commit()

        conn.close()

        return jsonify({
            "ok": True,
            "query": query,
            "total_found": len(results),
            "new_inserted": new_count,
            "linked_to_pattern": linked_count,
            "filtered_stale": audit["filtered_stale"],
            "audit": audit,
        })

    @app.route("/api/signals/resynthesize", methods=["POST"])
    def signals_resynthesize_api():
        """Re-run pattern detection on recent signals. SSE-streamed."""
        def generate():
            from agents.signals_synthesize import synthesize_into_threads, enrich_thread_signals, extract_entities
            from db import get_signals

            conn = get_connection(db_path)
            recent = get_signals(conn, days_back=14, limit=500)
            yield f"data: {json.dumps({'type': 'status', 'text': f'Re-analyzing {len(recent)} signals...'})}\n\n"

            synth_q = queue.Queue()
            result_box = [None]

            def _cb(event_type, ev_data):
                synth_q.put((event_type, ev_data or {}))

            def _run():
                try:
                    result = synthesize_into_threads(conn, recent, progress_cb=_cb)
                    result_box[0] = result
                    _cb("status", {"text": "Enriching articles..."})
                    enrich_thread_signals(conn, progress_cb=_cb)
                    enriched = get_signals(conn, days_back=14, limit=500)
                    _cb("status", {"text": "Extracting entities..."})
                    extract_entities(conn, enriched, progress_cb=_cb)
                except Exception as exc:
                    synth_q.put(("error", {"text": str(exc)}))
                finally:
                    synth_q.put(("_done", {}))

            t = threading.Thread(target=_run, daemon=True)
            t.start()

            while True:
                try:
                    ev_type, ev_data = synth_q.get(timeout=0.5)
                except queue.Empty:
                    yield ": keepalive\n\n"
                    continue
                if ev_type == "_done":
                    break
                yield f"data: {json.dumps({'type': ev_type, **ev_data})}\n\n"

            t.join(timeout=120)
            sr = result_box[0] or {}
            yield f"data: {json.dumps({'type': 'resynth_complete', 'new_patterns': sr.get('new_thread_count', 0), 'assigned': sr.get('assigned_count', 0)})}\n\n"

            conn.close()

        return Response(generate(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.route("/api/signals/scan-history", methods=["GET"])
    def signals_scan_history_api():
        """Fetch last 3 scan results."""
        from db import get_scan_history
        conn = get_connection(db_path)
        history = get_scan_history(conn)
        conn.close()
        return jsonify({"scans": history})

    @app.route("/api/signals/freshness", methods=["GET"])
    def signals_freshness_api():
        """Get last scan timestamps per domain."""
        from db import get_signal_freshness, get_signal_counts_by_domain
        conn = get_connection(db_path)
        freshness = get_signal_freshness(conn)
        counts = get_signal_counts_by_domain(conn)
        conn.close()
        return jsonify({"freshness": freshness, "counts": counts})

    @app.route("/api/signals/graph", methods=["GET"])
    def signals_graph_api():
        """Build graph data: thread nodes + entity-based edges."""
        from db import get_signal_clusters
        from agents.signals_synthesize import compute_thread_momentum

        conn = get_connection(db_path)
        threads = get_signal_clusters(conn, status="active", limit=50)

        # Build nodes
        nodes = []
        for t in threads:
            t["momentum"] = compute_thread_momentum(conn, t["id"])
            nodes.append({
                "id": t["id"],
                "title": t["title"],
                "domain": t["domain"],
                "signal_count": t.get("signal_count", 0),
                "synthesis": t.get("synthesis", ""),
                "momentum": t["momentum"],
            })

        # Find shared entities between threads to build edges
        # Get all entities grouped by thread (via cluster_id or signal_id → cluster)
        thread_entities = {}
        for t in threads:
            ents = conn.execute(
                """SELECT DISTINCT entity_type, COALESCE(normalized_value, entity_value) as name
                   FROM signal_entities
                   WHERE cluster_id = ? OR signal_id IN
                     (SELECT signal_id FROM signal_cluster_items WHERE cluster_id = ?)""",
                (t["id"], t["id"]),
            ).fetchall()
            thread_entities[t["id"]] = [(e["entity_type"], e["name"]) for e in ents]

        # Build edges from shared entities (2+ shared = edge)
        edges = []
        thread_ids = [t["id"] for t in threads]
        for i, tid_a in enumerate(thread_ids):
            for tid_b in thread_ids[i+1:]:
                ents_a = set(thread_entities.get(tid_a, []))
                ents_b = set(thread_entities.get(tid_b, []))
                shared = ents_a & ents_b
                if len(shared) >= 1:  # at least 1 shared entity creates an edge
                    edges.append({
                        "source": tid_a,
                        "target": tid_b,
                        "shared_entities": [{"type": t, "name": n} for t, n in shared],
                        "weight": len(shared),
                    })

        # Also include manual thread links as edges
        from db import get_thread_links
        manual_links = get_thread_links(conn)
        edge_keys = set((e["source"], e["target"]) for e in edges)
        for ml in manual_links:
            a, b = ml["thread_a_id"], ml["thread_b_id"]
            if (a, b) not in edge_keys and (b, a) not in edge_keys:
                edges.append({
                    "source": a,
                    "target": b,
                    "shared_entities": [{"type": "manual", "name": ml.get("label") or "user linked"}],
                    "weight": 2,
                    "manual": True,
                })

        conn.close()
        return jsonify({"nodes": nodes, "edges": edges})

    @app.route("/api/signals/brainstorm", methods=["POST"])
    def signals_brainstorm_api():
        """Generate hypotheses from connected threads."""
        data = request.json or {}
        thread_ids = data.get("thread_ids", [])
        if len(thread_ids) < 2:
            return jsonify({"error": "Select at least 2 threads"}), 400

        from db import get_cluster_detail
        from agents.llm import generate_json, FAST_CHAIN
        from prompts.signals import build_brainstorm_prompt

        conn = get_connection(db_path)

        # Build thread summaries
        threads_text_parts = []
        all_entities = {}
        for tid in thread_ids[:4]:
            detail = get_cluster_detail(conn, tid)
            if not detail:
                continue
            threads_text_parts.append(
                f"[Thread: {detail['title']}] Domain: {detail['domain']}\n"
                f"Summary: {detail.get('synthesis', 'No summary')}\n"
                f"Signals ({len(detail.get('signals', []))}):\n" +
                "\n".join(f"  - {s['title']}" for s in detail.get("signals", [])[:5])
            )
            for e in detail.get("entities", []):
                key = (e["entity_type"], e.get("normalized_value") or e["entity_value"])
                if key not in all_entities:
                    all_entities[key] = set()
                all_entities[key].add(tid)

        # Find shared entities
        shared = {k: v for k, v in all_entities.items() if len(v) >= 2}
        shared_text = "\n".join(
            f"- {etype}: {ename} (appears in {len(tids)} threads)"
            for (etype, ename), tids in shared.items()
        ) or "No shared entities found — these threads may be connected by theme rather than specific entities."

        threads_text = "\n\n".join(threads_text_parts)
        prompt = build_brainstorm_prompt(threads_text, shared_text)

        try:
            result = generate_json(prompt, timeout=45, chain=FAST_CHAIN)
            if not result:
                conn.close()
                return jsonify({"error": "LLM returned no result"}), 500
            # Persist brainstorm
            from db import save_brainstorm
            brainstorm_id = save_brainstorm(conn, thread_ids, result)
            result["brainstorm_id"] = brainstorm_id
            conn.close()
            return jsonify(result)
        except Exception as e:
            conn.close()
            return jsonify({"error": str(e)}), 500

    @app.route("/api/signals/brainstorms", methods=["GET"])
    def signals_brainstorms_list_api():
        """List previous brainstorm sessions."""
        from db import get_brainstorms, get_signal_clusters
        conn = get_connection(db_path)
        brainstorms = get_brainstorms(conn)
        # Enrich with thread titles
        all_threads = {t["id"]: t for t in get_signal_clusters(conn, status="active", limit=100)}
        for b in brainstorms:
            b["thread_titles"] = [all_threads.get(tid, {}).get("title", f"Thread {tid}") for tid in b.get("thread_ids", [])]
        conn.close()
        return jsonify({"brainstorms": brainstorms})

    @app.route("/api/signals/brainstorms/<int:brainstorm_id>", methods=["GET"])
    def signals_brainstorm_detail_api(brainstorm_id):
        """Fetch a single past brainstorm."""
        from db import get_brainstorm, get_signal_clusters
        conn = get_connection(db_path)
        b = get_brainstorm(conn, brainstorm_id)
        if not b:
            conn.close()
            return jsonify({"error": "Brainstorm not found"}), 404
        # Enrich with thread titles and data
        all_threads = {t["id"]: t for t in get_signal_clusters(conn, status="active", limit=100)}
        b["threads"] = [all_threads.get(tid, {"id": tid, "title": f"Thread {tid}", "domain": "unknown"}) for tid in b.get("thread_ids", [])]
        conn.close()
        return jsonify(b)

    @app.route("/api/signals/thread-links", methods=["GET"])
    def signals_thread_links_list_api():
        """List manual thread links."""
        from db import get_thread_links
        conn = get_connection(db_path)
        links = get_thread_links(conn)
        conn.close()
        return jsonify({"links": links})

    @app.route("/api/signals/thread-links", methods=["POST"])
    def signals_thread_link_create_api():
        """Create a manual link between two threads."""
        data = request.json or {}
        thread_a = data.get("thread_a_id")
        thread_b = data.get("thread_b_id")
        label = data.get("label", "")
        if not thread_a or not thread_b:
            return jsonify({"error": "thread_a_id and thread_b_id required"}), 400
        from db import add_thread_link
        conn = get_connection(db_path)
        link_id = add_thread_link(conn, thread_a, thread_b, label)
        conn.close()
        if link_id:
            return jsonify({"ok": True, "link_id": link_id})
        return jsonify({"ok": False, "error": "Link already exists"})

    @app.route("/api/signals/thread-links/<int:link_id>", methods=["DELETE"])
    def signals_thread_link_delete_api(link_id):
        """Delete a manual thread link."""
        from db import delete_thread_link
        conn = get_connection(db_path)
        delete_thread_link(conn, link_id)
        conn.close()
        return jsonify({"ok": True})

    @app.route("/api/signals/entity-context/<entity_type>/<path:entity_value>", methods=["GET"])
    def signals_entity_context_api(entity_type, entity_value):
        """Get context for an entity — dossier info for companies, campaigns for sectors."""
        conn = get_connection(db_path)
        context = {"type": entity_type, "value": entity_value}

        if entity_type == "company":
            # Check for matching dossier
            dossier = conn.execute(
                "SELECT id, company_name, sector, description, website_url FROM dossiers WHERE company_name = ? COLLATE NOCASE",
                (entity_value,),
            ).fetchone()
            if not dossier:
                # Try normalized value
                norm = conn.execute(
                    "SELECT normalized_value FROM signal_entities WHERE entity_type = 'company' AND entity_value = ? COLLATE NOCASE LIMIT 1",
                    (entity_value,),
                ).fetchone()
                if norm and norm["normalized_value"]:
                    dossier = conn.execute(
                        "SELECT id, company_name, sector, description, website_url FROM dossiers WHERE company_name = ? COLLATE NOCASE",
                        (norm["normalized_value"],),
                    ).fetchone()
            if dossier:
                d = dict(dossier)
                # Get latest analyses
                analyses = conn.execute(
                    "SELECT analysis_type, created_at FROM dossier_analyses WHERE dossier_id = ? ORDER BY created_at DESC LIMIT 5",
                    (d["id"],),
                ).fetchall()
                d["analyses"] = [dict(a) for a in analyses]
                context["dossier"] = d

        elif entity_type == "sector":
            # Find matching campaigns
            campaigns = conn.execute(
                "SELECT id, niche, name, status, created_at FROM campaigns WHERE niche LIKE ? COLLATE NOCASE ORDER BY created_at DESC LIMIT 5",
                (f"%{entity_value}%",),
            ).fetchall()
            context["campaigns"] = [dict(c) for c in campaigns]

        # Count signals mentioning this entity
        signal_count = conn.execute(
            "SELECT COUNT(DISTINCT signal_id) as cnt FROM signal_entities WHERE entity_type = ? AND (entity_value = ? COLLATE NOCASE OR normalized_value = ? COLLATE NOCASE)",
            (entity_type, entity_value, entity_value),
        ).fetchone()["cnt"]
        context["signal_count"] = signal_count

        conn.close()
        return jsonify(context)

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, port=5001, threaded=True)
