"""Flask web app for SignalVault — single-page three-pane UI with agentic chat."""

import os
import sys
import json
import sqlite3
import threading
import queue
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

# ── Background body-scraping pool ────────────────────────────────────────────
# Fetches full article text for newly ingested signals with thin body (<200 chars).
# 3 workers — light I/O, no GPU contention, daemon so it doesn't block shutdown.
_body_scrape_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="body_scrape")


def _scrape_and_update_body(db_path, sig_id, url):
    """Fetch full article text for a signal and update body in DB.

    Runs in a background thread. Opens its own DB connection (cross-thread safe).
    Only updates if body is still thin (<200 chars) to avoid overwriting enriched rows.
    """
    try:
        from scraper.web_search import fetch_page_text
        text = fetch_page_text(url, max_chars=4000)
        if not text or len(text) < 100:
            return
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "UPDATE signals SET body = ? WHERE id = ? AND (body IS NULL OR length(body) < 200)",
            (text, sig_id),
        )
        conn.commit()
        conn.close()
        print(f"[body_scrape] sig {sig_id}: {len(text)} chars from {url[:70]}")
    except Exception as e:
        print(f"[body_scrape] failed sig {sig_id} ({url[:60]}): {e}")

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
            new_count, to_scrape = insert_signals_batch(conn, signals)

            # Background: fetch full article text for signals with thin body
            if to_scrape:
                for _sid, _url in to_scrape:
                    _body_scrape_pool.submit(_scrape_and_update_body, db_path, _sid, _url)
                print(f"[signals] Queued {len(to_scrape)} signals for background body scraping")

            yield f"data: {json.dumps({'type': 'scan_complete', 'total_collected': len(signals), 'new_inserted': new_count})}\n\n"

            # Auto-synthesize: group new signals into threads
            if auto_synthesize and new_count > 0:
                yield f"data: {json.dumps({'type': 'status', 'text': 'Synthesizing signals into threads...'})}\n\n"

                from agents.signals_synthesize import synthesize_into_threads, enrich_thread_signals, extract_entities
                from db import get_unassigned_signals

                # Only synthesize signals not already assigned to a thread
                recent = get_unassigned_signals(conn, days_back=1, limit=300)

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

    @app.route("/api/signals/<int:sig_id>/scrape", methods=["POST"])
    def signals_scrape_api(sig_id):
        """Scrape full article text for a specific signal and update DB."""
        from scraper.web_search import fetch_page_text

        conn = get_connection(db_path)
        row = conn.execute("SELECT url FROM signals WHERE id = ?", (sig_id,)).fetchone()
        if not row or not row["url"]:
            conn.close()
            return jsonify({"error": "Signal not found or has no URL"}), 404

        url = row["url"]
        try:
            text = fetch_page_text(url, max_chars=8000)
            if text and len(text) > 200:
                conn.execute("UPDATE signals SET body = ? WHERE id = ?", (text, sig_id))
                conn.commit()
                conn.close()
                return jsonify({"ok": True, "body": text})
            else:
                conn.close()
                return jsonify({"error": "Failed to extract meaningful text from page"}), 500
        except Exception as e:
            conn.close()
            return jsonify({"error": str(e)}), 500

    @app.route("/api/signals/threads", methods=["GET"])
    def signals_threads_api():
        """Fetch signal threads with momentum data."""
        domain = request.args.get("domain")
        status = request.args.get("status", "active")
        limit = int(request.args.get("limit", 50))

        from db import get_signal_clusters
        from agents.signals_synthesize import compute_thread_momentum

        conn = get_connection(db_path)
        # Exclude narrative threads from the Threads tab (they live in their narrative)
        exclude = None if domain else "narrative"
        threads = get_signal_clusters(conn, domain=domain, status=status, limit=limit, exclude_domain=exclude)

        # Enrich with momentum
        for t in threads:
            t["momentum"] = compute_thread_momentum(conn, t["id"])

        conn.close()
        return jsonify({"threads": threads})

    @app.route("/api/signals/threads/names", methods=["GET"])
    def signals_threads_names_api():
        """Fetch all thread IDs and titles lightweight."""
        conn = get_connection(db_path)
        rows = conn.execute("SELECT id, title, domain, (SELECT COUNT(1) FROM signal_cluster_items WHERE cluster_id = signal_clusters.id) as signal_count FROM signal_clusters").fetchall()
        conn.close()
        threads = [{"id": r["id"], "title": r["title"], "domain": r["domain"], "signal_count": r["signal_count"]} for r in rows]
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

        # Include parent narrative info if this thread belongs to one
        if detail.get("narrative_id"):
            narr_row = conn.execute(
                "SELECT id, title FROM narratives WHERE id = ?", (detail["narrative_id"],)
            ).fetchone()
            if narr_row:
                detail["narrative"] = {"id": narr_row["id"], "title": narr_row["title"]}

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

    @app.route("/api/signals/threads/<int:thread_id>", methods=["DELETE"])
    def signals_thread_delete_api(thread_id):
        """Delete a thread and unlink its signals."""
        conn = get_connection(db_path)
        conn.execute("DELETE FROM signal_cluster_items WHERE cluster_id = ?", (thread_id,))
        conn.execute("DELETE FROM signal_entities WHERE cluster_id = ?", (thread_id,))
        conn.execute("DELETE FROM board_positions WHERE node_type = 'thread' AND node_id = ?", (thread_id,))
        conn.execute("DELETE FROM thread_links WHERE thread_a_id = ? OR thread_b_id = ?", (thread_id, thread_id))
        conn.execute("DELETE FROM signal_clusters WHERE id = ?", (thread_id,))
        conn.commit()
        conn.close()
        return jsonify({"ok": True})

    @app.route("/api/signals/threads/<int:thread_id>/ai-rename", methods=["POST"])
    def signals_thread_ai_rename_api(thread_id):
        """LLM generates a better directional title for a thread based on its signals."""
        from db import get_cluster_detail
        from agents.llm import generate_json, FAST_CHAIN
        conn = get_connection(db_path)
        detail = get_cluster_detail(conn, thread_id)
        if not detail:
            conn.close()
            return jsonify({"error": "Thread not found"}), 404
        signals = detail.get("signals", [])[:15]
        signals_text = "\n".join(f"- {s.get('title', '')}" for s in signals)
        prompt = f"""Rename this thread to have a specific DIRECTIONAL claim title.

Current title: {detail.get('title', '')}
Domain: {detail.get('domain', '')}
Signals:
{signals_text}

RULES:
- The title MUST take a DIRECTION — something is going UP, DOWN, ACCELERATING, DECLINING, SHIFTING
- BAD: "Labor Market Trends" → GOOD: "US Labor Market Weakening Despite Strong Headlines"
- BAD: "Stock Market Rotation" → GOOD: "Tech Stocks Surging While Industrials Decline"
- Be specific with entities, geographies, sectors

Return JSON: {{"title": "New directional title"}}"""
        try:
            result = generate_json(prompt, timeout=10, chain=FAST_CHAIN)
        except Exception as e:
            conn.close()
            return jsonify({"error": str(e)}), 500
        new_title = (result or {}).get("title", "").strip()
        if not new_title:
            conn.close()
            return jsonify({"error": "LLM returned empty title"}), 500
        conn.execute("UPDATE signal_clusters SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (new_title, thread_id))
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "title": new_title})

    @app.route("/api/signals/threads/<int:thread_id>/propose-split", methods=["POST"])
    def signals_thread_propose_split_api(thread_id):
        """LLM proposes how to split a large thread into specific sub-threads."""
        from db import get_cluster_detail
        from agents.llm import generate_json, FAST_CHAIN
        from prompts.signals import build_thread_split_prompt
        from agents.signals_synthesize import _format_signals_for_prompt

        conn = get_connection(db_path)
        detail = get_cluster_detail(conn, thread_id)
        conn.close()
        if not detail:
            return jsonify({"error": "Thread not found"}), 404

        signals = detail.get("signals", [])
        if len(signals) < 6:
            return jsonify({"error": "Thread needs at least 6 signals to split"}), 400

        signals_text = "\n".join(
            f"[{s['id']}] {s['title']}" for s in signals
        )

        prompt = build_thread_split_prompt(detail["title"], signals_text)
        try:
            result = generate_json(prompt, timeout=30, chain=FAST_CHAIN)
        except Exception as e:
            return jsonify({"error": f"LLM error: {e}"}), 500

        if not result:
            return jsonify({"error": "LLM returned no result"}), 500

        # Drop any proposed sub-thread with fewer than 2 signals — merge back to remaining
        proposed = result.get("proposed_splits", [])
        remaining = result.get("remaining") or {"title": None, "signal_ids": []}
        filtered = []
        for split in proposed:
            if len(split.get("signal_ids", [])) >= 2:
                filtered.append(split)
            else:
                remaining["signal_ids"].extend(split.get("signal_ids", []))
        result["proposed_splits"] = filtered
        result["remaining"] = remaining

        if len(filtered) < 2:
            return jsonify({"error": "Not enough distinct groupings found — thread may already be focused"}), 400

        return jsonify({"ok": True, "thread_id": thread_id, "thread_title": detail["title"], **result})

    @app.route("/api/signals/threads/<int:thread_id>/execute-split", methods=["POST"])
    def signals_thread_execute_split_api(thread_id):
        """Execute a proposed thread split — create new threads and reassign signals."""
        from db import insert_signal_cluster, link_signal_to_cluster, sanitize_domain

        data = request.json or {}
        splits = data.get("splits", [])
        if not splits:
            return jsonify({"error": "No splits provided"}), 400

        conn = get_connection(db_path)
        created = []
        for split in splits:
            title = split.get("title", "").strip()
            sig_ids = split.get("signal_ids", [])
            external = split.get("external_signals", [])
            domain = sanitize_domain(split.get("domain", ""))
            target_thread_id = split.get("target_thread_id")
            if not title or (not sig_ids and not external):
                continue

            if target_thread_id:
                # Merge into existing thread — move signals, don't create new
                dest_id = int(target_thread_id)
                for sid in sig_ids:
                    conn.execute("DELETE FROM signal_cluster_items WHERE cluster_id = ? AND signal_id = ?", (thread_id, sid))
                    link_signal_to_cluster(conn, dest_id, sid)
                for ext in external:
                    from_tid = ext.get("from_thread_id")
                    ext_sid = ext.get("signal_id")
                    if from_tid and ext_sid:
                        conn.execute("DELETE FROM signal_cluster_items WHERE cluster_id = ? AND signal_id = ?", (from_tid, ext_sid))
                        link_signal_to_cluster(conn, dest_id, ext_sid)
                conn.execute("UPDATE signal_clusters SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (dest_id,))
                created.append({"id": dest_id, "title": title, "signal_count": len(sig_ids) + len(external), "merged": True})
            else:
                # Create new thread
                new_id = insert_signal_cluster(conn, {"domain": domain, "title": title, "synthesis": split.get("rationale", "")})
                conn.execute("UPDATE signal_clusters SET last_signal_at = CURRENT_TIMESTAMP WHERE id = ?", (new_id,))
                for sid in sig_ids:
                    conn.execute("DELETE FROM signal_cluster_items WHERE cluster_id = ? AND signal_id = ?", (thread_id, sid))
                    link_signal_to_cluster(conn, new_id, sid)
                for ext in external:
                    from_tid = ext.get("from_thread_id")
                    ext_sid = ext.get("signal_id")
                    if from_tid and ext_sid:
                        conn.execute("DELETE FROM signal_cluster_items WHERE cluster_id = ? AND signal_id = ?", (from_tid, ext_sid))
                        link_signal_to_cluster(conn, new_id, ext_sid)
                created.append({"id": new_id, "title": title, "signal_count": len(sig_ids) + len(external)})

        conn.execute("UPDATE signal_clusters SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (thread_id,))
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "created": created})

    @app.route("/api/signals/threads/<int:thread_id>/lab", methods=["GET"])
    def signals_thread_lab_api(thread_id):
        """Thread Lab: auto-cluster thread signals (TF-IDF KMeans) + find related signals from other threads."""
        import numpy as np
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.cluster import KMeans
        from sklearn.metrics.pairwise import cosine_similarity
        from db import get_cluster_detail, get_thread_date_range
        from datetime import datetime as _labdt

        conn = get_connection(db_path)
        detail = get_cluster_detail(conn, thread_id)
        if not detail:
            conn.close()
            return jsonify({"error": "Thread not found"}), 404

        signals = detail.get("signals", [])
        n = len(signals)
        if n < 4:
            conn.close()
            return jsonify({"error": "Thread needs at least 4 signals for Thread Lab"}), 400

        # Use title (weighted 2x) + body for richer TF-IDF features
        docs = []
        for s in signals:
            t = s.get("title", "") or ""
            b = (s.get("body") or s.get("body_text") or "")[:500]
            docs.append(f"{t} {t} {b}")  # title repeated for 2x weight
        try:
            vectorizer = TfidfVectorizer(ngram_range=(1, 2), max_features=3000,
                                          stop_words="english", sublinear_tf=True)
            X = vectorizer.fit_transform(docs)
        except Exception as e:
            conn.close()
            return jsonify({"error": f"Vectorization failed: {e}"}), 500

        k = max(2, min(6, round(n / 8)))
        km = KMeans(n_clusters=k, random_state=42, n_init=10)
        labels = km.fit_predict(X)

        feature_names = vectorizer.get_feature_names_out()
        sub_groups = []
        for ci in range(k):
            idxs = [i for i in range(n) if labels[i] == ci]
            if not idxs:
                continue
            center = np.asarray(km.cluster_centers_[ci]).flatten()
            top_idx = center.argsort()[::-1][:12]
            # Filter out TLD fragments, year numbers, and generic news noise
            _LAB_NOISE = {
                "com", "org", "net", "www", "html", "says", "said", "new", "year",
                "report", "says", "data", "use", "time", "day", "week", "month",
                "bloomberg", "reuters", "cnbc", "wsj", "cnn", "bbc", "nyt", "ft",
                "nationaltoday", "bitget", "stockstory", "bnnbloomberg", "biospace",
                "investing", "finance", "yahoo", "google", "markets", "barrons",
            }
            key_terms = [
                feature_names[j] for j in top_idx
                if center[j] > 0
                and feature_names[j] not in _LAB_NOISE
                and not feature_names[j].isdigit()
                and len(feature_names[j]) > 2
            ]
            # Prefer bigrams (contain a space) for the label — more descriptive
            bigrams = [t for t in key_terms if ' ' in t]
            label_terms = bigrams[:2] if bigrams else key_terms[:2]
            cluster_sigs = [signals[i] for i in idxs]
            sub_groups.append({
                "cluster_idx": ci,
                "label": " / ".join(label_terms).title() if label_terms else f"Group {ci + 1}",
                "key_terms": key_terms[:5],
                "signal_ids": [s["id"] for s in cluster_sigs],
                "signals": [
                    {"id": s["id"], "title": s.get("title", ""),
                     "published_at": (s.get("published_at") or "")[:10],
                     "source_name": s.get("source_name") or s.get("source") or "",
                     "body": (s.get("body") or s.get("body_text") or "")[:300]}
                    for s in cluster_sigs
                ],
            })
        sub_groups.sort(key=lambda g: len(g["signal_ids"]), reverse=True)

        # Auto-suggest existing threads for each group (keyword overlap via TF-IDF)
        existing_threads = conn.execute(
            "SELECT id, title FROM signal_clusters WHERE domain != 'narrative' AND id != ?"
            " ORDER BY last_signal_at DESC LIMIT 200",
            (thread_id,)
        ).fetchall()
        for g in sub_groups:
            g["suggested_thread"] = None
            if not existing_threads:
                continue
            # Try TF-IDF cosine similarity first
            try:
                ci = g["cluster_idx"]
                center = np.asarray(km.cluster_centers_[ci]).flatten().reshape(1, -1)
                et_titles = [r["title"] or "" for r in existing_threads]
                et_vecs = vectorizer.transform(et_titles)
                sims = cosine_similarity(center, et_vecs)[0]
                best_idx = int(sims.argmax())
                best_sim = float(sims[best_idx])
                if best_sim >= 0.15:
                    g["suggested_thread"] = {
                        "id": int(existing_threads[best_idx]["id"]),
                        "title": existing_threads[best_idx]["title"],
                        "similarity": round(best_sim, 3),
                    }
                    continue
            except Exception:
                pass
            # Fallback: keyword overlap between group key_terms and thread titles
            try:
                kw = set(t.lower() for t in g.get("key_terms", []))
                if len(kw) < 2:
                    continue
                best_match, best_overlap = None, 0
                for et in existing_threads:
                    et_lower = (et["title"] or "").lower()
                    overlap = sum(1 for k in kw if k in et_lower)
                    if overlap > best_overlap:
                        best_overlap = overlap
                        best_match = et
                if best_match and best_overlap >= 2:
                    g["suggested_thread"] = {
                        "id": int(best_match["id"]),
                        "title": best_match["title"],
                        "similarity": round(best_overlap / max(len(kw), 1), 3),
                    }
            except Exception:
                pass

        # Coherence: average pairwise cosine similarity
        if n > 1:
            sim_mat = cosine_similarity(X)
            np.fill_diagonal(sim_mat, 0)
            coherence = float(sim_mat.sum() / (n * (n - 1)))
        else:
            coherence = 1.0

        tmin, tmax, dated_count = get_thread_date_range(conn, thread_id)
        date_span_days = None
        if tmin and tmax:
            date_span_days = (_labdt.strptime(tmax, "%Y-%m-%d") -
                              _labdt.strptime(tmin, "%Y-%m-%d")).days

        # Related signals from other threads (similarity >= 0.15 to thread centroid)
        other_rows = conn.execute("""
            SELECT s.id, s.title, s.published_at, s.source_name,
                   sci.cluster_id as thread_id, sc.title as thread_title
            FROM signals s
            JOIN signal_cluster_items sci ON sci.signal_id = s.id
            JOIN signal_clusters sc ON sc.id = sci.cluster_id
            WHERE sci.cluster_id != ? AND sc.domain != 'narrative'
            ORDER BY s.collected_at DESC LIMIT 600
        """, (thread_id,)).fetchall()
        conn.close()

        related = []
        if other_rows:
            try:
                other_titles = [r["title"] or "" for r in other_rows]
                other_vecs = vectorizer.transform(other_titles)
                centroid = np.asarray(X.mean(axis=0))
                sims = cosine_similarity(centroid, other_vecs)[0]
                for i, sim_score in enumerate(sims):
                    if sim_score >= 0.15:
                        related.append({
                            "signal_id": other_rows[i]["id"],
                            "title": other_rows[i]["title"],
                            "published_at": (other_rows[i]["published_at"] or "")[:10],
                            "source_name": other_rows[i]["source_name"] or "",
                            "current_thread_id": other_rows[i]["thread_id"],
                            "current_thread_title": other_rows[i]["thread_title"],
                            "similarity": round(float(sim_score), 3),
                        })
            except Exception:
                pass
        related.sort(key=lambda x: x["similarity"], reverse=True)

        # Pairwise similarity matrix for client-side per-column cohesion
        sim_order = [s["id"] for s in signals]
        sim_data = sim_mat.round(3).tolist() if n > 1 else []

        return jsonify({
            "thread_id": thread_id,
            "title": detail["title"],
            "health": {
                "signal_count": n,
                "date_span_days": date_span_days,
                "date_min": tmin,
                "date_max": tmax,
                "coherence_score": round(coherence, 3),
            },
            "sub_groups": sub_groups,
            "related_from_other_threads": related[:30],
            "sim_order": sim_order,
            "sim_matrix": sim_data,
        })

    @app.route("/api/signals/organize-lab", methods=["GET"])
    def signals_organize_lab_api():
        """
        Organize mode: semantic signal grouping via sentence embeddings + temporal event detection.

        Algorithm:
          1. Encode threads with all-MiniLM-L6-v2 (title + recent signal titles as context).
          2. Encode each unassigned signal (title + body[:500]).
          3. Match each signal to its best thread (cosine >= MATCH_THRESH = 0.28).
             Column = real thread, cohesion = avg embedding similarity to thread.
          4. Remaining signals → DBSCAN event-burst detection.
             Distance = 1 - (0.65 * emb_cos_sim + 0.35 * temporal_sim).
             temporal_sim(i,j) = max(0, 1 - |days_apart| / 7).
          5. Key terms extracted via lightweight TF-IDF on titles only (for labelling).
          6. Columns sorted: thread-matches by count desc, event bursts chronologically.
        """
        import os, numpy as np
        from datetime import datetime, timedelta
        from sklearn.cluster import DBSCAN
        from sklearn.feature_extraction.text import TfidfVectorizer

        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

        MATCH_THRESH  = 0.28  # min embedding cosine to assign signal → thread
        THREAD_MIN    = 2     # min signals to show as a thread column (singletons → DBSCAN)
        DBSCAN_EPS    = 0.55  # max combined distance to be in same burst
        DBSCAN_MIN    = 2     # min signals per burst

        limit = int(request.args.get("limit", 200))
        conn = get_connection(db_path)

        # ── 1. Fetch unassigned signals ────────────────────────────────────────
        rows = conn.execute("""
            SELECT s.id, s.title, s.body, s.published_at, s.collected_at,
                   s.source_name, s.source
            FROM signals s
            LEFT JOIN signal_cluster_items sci ON sci.signal_id = s.id
            WHERE sci.id IS NULL AND COALESCE(s.signal_status, 'signal') != 'noise'
            ORDER BY s.published_at DESC LIMIT ?
        """, (limit,)).fetchall()
        signals = [dict(r) for r in rows]
        n = len(signals)

        total_unassigned = conn.execute("""
            SELECT COUNT(*) FROM signals s
            LEFT JOIN signal_cluster_items sci ON sci.signal_id = s.id
            WHERE sci.id IS NULL AND COALESCE(s.signal_status, 'signal') != 'noise'
        """).fetchone()[0]

        if n < 3:
            conn.close()
            return jsonify({"error": f"Only {n} unassigned signals — not enough to cluster",
                            "total_unassigned": total_unassigned}), 400

        # ── 2. Parse signal publish dates ──────────────────────────────────────
        now = datetime.now()

        def _parse_date(s):
            for src in [s.get("published_at"), s.get("collected_at")]:
                if not src:
                    continue
                src = str(src).strip()
                if len(src) >= 10 and src[4:5] == "-":
                    try:
                        return datetime.fromisoformat(src[:10])
                    except Exception:
                        pass
                for fmt in ("%a, %d %b %Y", "%d %b %Y"):
                    try:
                        return datetime.strptime(src[:len(fmt) + 2], fmt)
                    except Exception:
                        pass
            return now

        sig_dates = [_parse_date(s) for s in signals]

        # ── 3. Fetch existing threads + recent signal content for time decay ───
        threads = conn.execute("""
            SELECT sc.id, sc.title, sc.synthesis
            FROM signal_clusters sc
            WHERE sc.domain != 'narrative' AND sc.status = 'active'
            ORDER BY sc.last_signal_at DESC LIMIT 300
        """).fetchall()
        threads = [dict(t) for t in threads]
        thread_ids = [t["id"] for t in threads]

        thread_signals = {}  # tid → {recent_14d: [...], recent_90d: [...]}
        if thread_ids:
            cutoff_90 = (now - timedelta(days=90)).strftime("%Y-%m-%d")
            cutoff_14 = (now - timedelta(days=14)).strftime("%Y-%m-%d")
            placeholders = ",".join("?" * len(thread_ids))
            ts_rows = conn.execute(f"""
                SELECT sci.cluster_id, s.title, s.published_at
                FROM signal_cluster_items sci
                JOIN signals s ON s.id = sci.signal_id
                WHERE sci.cluster_id IN ({placeholders})
                  AND COALESCE(s.published_at, '2000-01-01') >= ?
                ORDER BY s.published_at DESC
            """, thread_ids + [cutoff_90]).fetchall()
            for r in ts_rows:
                cid = r["cluster_id"]
                if cid not in thread_signals:
                    thread_signals[cid] = {"recent_14d": [], "recent_90d": []}
                pa = str(r["published_at"] or "")[:10]
                title = r["title"] or ""
                if pa >= cutoff_14:
                    thread_signals[cid]["recent_14d"].append(title)
                else:
                    thread_signals[cid]["recent_90d"].append(title)

        conn.close()

        # ── 4. Load sentence embedding model (cached globally) ─────────────────
        if not hasattr(signals_organize_lab_api, "_st_model"):
            try:
                from sentence_transformers import SentenceTransformer
                signals_organize_lab_api._st_model = SentenceTransformer("all-MiniLM-L6-v2")
            except Exception as e:
                return jsonify({"error": f"Embedding model unavailable: {e}. Run: pip install sentence-transformers"}), 500
        model = signals_organize_lab_api._st_model

        # ── 5. Build embedding documents ───────────────────────────────────────
        def _thread_doc(t):
            # Thread title + up to 5 recent signal titles as semantic context
            ts = thread_signals.get(t["id"], {"recent_14d": [], "recent_90d": []})
            recent = (ts["recent_14d"] + ts["recent_90d"])[:5]
            parts = [t["title"] or ""]
            if recent:
                parts.append(". ".join(recent))
            return ". ".join(parts)

        def _sig_doc(s):
            title = s.get("title") or ""
            body  = (s.get("body") or "")[:500]
            return f"{title}. {body}" if body.strip() else title

        thread_docs = [_thread_doc(t) for t in threads]
        sig_docs    = [_sig_doc(s) for s in signals]

        # ── 6. Encode + compute similarity ─────────────────────────────────────
        try:
            t_embs = model.encode(thread_docs, normalize_embeddings=True,
                                  show_progress_bar=False, batch_size=64) if threads \
                     else np.zeros((0, 384))
            s_embs = model.encode(sig_docs, normalize_embeddings=True,
                                  show_progress_bar=False, batch_size=64)
        except Exception as e:
            return jsonify({"error": f"Embedding failed: {e}"}), 500

        # Cosine similarity: normalized vectors → dot product
        sim_st = (s_embs @ t_embs.T) if threads else np.zeros((n, 0))

        # Lightweight TF-IDF on titles only — used for key term extraction / labelling
        _tfidf = TfidfVectorizer(ngram_range=(1, 2), max_features=2000,
                                 stop_words="english", sublinear_tf=True)
        try:
            _X_sig_titles = _tfidf.fit_transform([s.get("title") or "" for s in signals])
            _feat = _tfidf.get_feature_names_out()
        except Exception:
            _X_sig_titles = None
            _feat = []

        # ── 7. Thread matching ─────────────────────────────────────────────────
        # sim_st[i, j] = cosine(signal_i, thread_j)

        thread_groups  = {}   # tid → {"thread": t, "items": [(sig_idx, sim)]}
        unmatched_idxs = []

        for i in range(n):
            if sim_st.shape[1] == 0:
                unmatched_idxs.append(i)
                continue
            best_j   = int(sim_st[i].argmax())
            best_sim = float(sim_st[i, best_j])
            if best_sim >= MATCH_THRESH:
                tid = threads[best_j]["id"]
                if tid not in thread_groups:
                    thread_groups[tid] = {"thread": threads[best_j],
                                          "thread_j": best_j, "items": []}
                thread_groups[tid]["items"].append((i, best_sim))
            else:
                unmatched_idxs.append(i)

        # ── 8. Helpers ─────────────────────────────────────────────────────────
        _NOISE = {
            "com", "org", "net", "www", "html", "says", "said", "new", "year",
            "report", "data", "use", "time", "day", "week", "month",
            "bloomberg", "reuters", "cnbc", "wsj", "cnn", "bbc", "nyt", "ft",
            "investing", "finance", "yahoo", "google", "markets", "barrons",
        }

        def _key_terms(sig_idxs):
            """Extract key terms from signal titles via TF-IDF centroid."""
            if not sig_idxs or _X_sig_titles is None or not len(_feat):
                return []
            centroid = np.asarray(_X_sig_titles[sig_idxs].mean(axis=0)).flatten()
            top_idx  = centroid.argsort()[::-1][:15]
            return [
                _feat[j] for j in top_idx
                if centroid[j] > 0 and _feat[j] not in _NOISE
                and not _feat[j].isdigit() and len(_feat[j]) > 2
            ]

        def _label(terms):
            bigrams = [t for t in terms if " " in t]
            parts   = bigrams[:2] if bigrams else terms[:2]
            return " / ".join(parts).title() if parts else "Group"

        def _fmt_date(dt):
            return dt.strftime("%b") + " " + str(dt.day)

        def _date_range(dates):
            valid = sorted([d for d in dates if d])
            if not valid:
                return ""
            mn, mx = valid[0], valid[-1]
            if mn.date() == mx.date():
                return _fmt_date(mn)
            if mn.month == mx.month:
                return f"{_fmt_date(mn)}–{mx.day}"
            return f"{_fmt_date(mn)} – {_fmt_date(mx)}"

        def _sig_payload(s):
            return {
                "id": s["id"],
                "title": s.get("title") or "",
                "published_at": (s.get("published_at") or "")[:10],
                "source_name": s.get("source_name") or s.get("source") or "",
                "body": (s.get("body") or "")[:300],
            }

        sub_groups     = []
        overflow_signals = []
        cluster_idx    = 0

        # ── 9. Build thread-match columns (≥ THREAD_MIN signals each) ────────
        for tid, grp in thread_groups.items():
            items = grp["items"]
            if len(items) < THREAD_MIN:
                # Too few signals to warrant a column — push to DBSCAN pool
                for i, _ in items:
                    unmatched_idxs.append(i)
                continue
            t       = grp["thread"]
            tj      = grp["thread_j"]
            sig_idxs = [i for i, _ in items]
            avg_sim  = round(float(np.mean([s for _, s in items])), 3)
            dates_g  = [sig_dates[i] for i in sig_idxs]
            terms    = _key_terms(sig_idxs)
            # Sort signals best-match first within column
            items_sorted = sorted(items, key=lambda x: -x[1])
            sub_groups.append({
                "cluster_idx": cluster_idx,
                "label": t["title"] or _label(terms),
                "key_terms": terms[:5],
                "cohesion": avg_sim,
                "date_range": _date_range(dates_g),
                "group_type": "thread_match",
                "suggested_thread": {
                    "id": int(tid), "title": t["title"], "similarity": avg_sim,
                },
                "signals": [_sig_payload(signals[i]) for i, _ in items_sorted],
                "signal_ids": [signals[i]["id"] for i, _ in items_sorted],
            })
            cluster_idx += 1

        # ── 10. DBSCAN event-burst on unmatched signals ────────────────────────
        um = len(unmatched_idxs)
        if um >= DBSCAN_MIN:
            # Embedding cosine similarity between unmatched signals
            um_embs = s_embs[unmatched_idxs]
            cs_um   = um_embs @ um_embs.T  # already normalized → dot = cosine

            # Temporal similarity: 1 - |days_apart| / 7, clamped [0,1]
            um_dates = [sig_dates[i] for i in unmatched_idxs]
            ts_um = np.zeros((um, um))
            for a in range(um):
                for b in range(um):
                    days = abs((um_dates[a] - um_dates[b]).days)
                    ts_um[a, b] = max(0.0, 1.0 - days / 7.0)

            dist = 1.0 - np.clip(0.65 * cs_um + 0.35 * ts_um, 0, 1)
            np.fill_diagonal(dist, 0.0)

            db_labels = DBSCAN(eps=DBSCAN_EPS, min_samples=DBSCAN_MIN,
                               metric="precomputed").fit_predict(dist)

            for lbl in sorted(set(db_labels)):
                local_idxs = [unmatched_idxs[j] for j in range(um)
                               if db_labels[j] == lbl]
                if lbl == -1 or len(local_idxs) < DBSCAN_MIN:
                    for i in local_idxs:
                        overflow_signals.append(_sig_payload(signals[i]))
                    continue
                terms   = _key_terms(local_idxs)
                dates_g = [sig_dates[i] for i in local_idxs]
                # Cohesion = mean pairwise embedding cosine within burst
                grp_embs = s_embs[local_idxs]
                sm = grp_embs @ grp_embs.T
                np.fill_diagonal(sm, 0)
                cohesion = round(float(sm.sum() / (len(local_idxs) *
                                                    max(len(local_idxs) - 1, 1))), 3)
                median_date = sorted(dates_g)[len(dates_g) // 2]
                sub_groups.append({
                    "cluster_idx": cluster_idx,
                    "label": _label(terms),
                    "key_terms": terms[:5],
                    "cohesion": cohesion,
                    "date_range": _date_range(dates_g),
                    "group_type": "event_burst",
                    "suggested_thread": None,
                    "_sort_date": median_date.isoformat(),
                    "signals": [_sig_payload(signals[i])
                                for i in sorted(local_idxs,
                                                key=lambda x: sig_dates[x])],
                    "signal_ids": [signals[i]["id"] for i in local_idxs],
                })
                cluster_idx += 1
        else:
            for i in unmatched_idxs:
                overflow_signals.append(_sig_payload(signals[i]))

        # ── 11. Sort: thread-matches by size, event bursts chronologically ──────
        tm_groups = [g for g in sub_groups if g.get("group_type") == "thread_match"]
        eb_groups = [g for g in sub_groups if g.get("group_type") == "event_burst"]
        tm_groups.sort(key=lambda g: len(g["signals"]), reverse=True)
        eb_groups.sort(key=lambda g: g.get("_sort_date", ""))
        sub_groups = tm_groups + eb_groups

        # Overall coherence = avg best embedding similarity across all signals
        coherence = round(float(sim_st.max(axis=1).mean()), 3) if sim_st.shape[1] else 0.0

        return jsonify({
            "mode": "organize",
            "total_unassigned": total_unassigned,
            "health": {
                "signal_count": n,
                "coherence_score": coherence,
                "date_span_days": None,
                "date_min": None,
                "date_max": None,
            },
            "sub_groups": sub_groups,
            "overflow_signals": overflow_signals,
        })

    @app.route("/api/signals/search", methods=["GET"])
    def signals_keyword_search_api():
        """Search signals by keyword across title + body, return thread matches with counts."""
        q = request.args.get("q", "").strip()
        if not q or len(q) < 2:
            return jsonify({"error": "Query too short"}), 400

        conn = get_connection(db_path)
        like = f"%{q}%"
        rows = conn.execute(
            """SELECT s.id as signal_id, s.title, sci.cluster_id as thread_id
               FROM signals s
               JOIN signal_cluster_items sci ON sci.signal_id = s.id
               JOIN signal_clusters sc ON sc.id = sci.cluster_id
               WHERE sc.domain != 'narrative'
                 AND (s.title LIKE ? COLLATE NOCASE OR s.body LIKE ? COLLATE NOCASE)
               ORDER BY sci.cluster_id""",
            (like, like),
        ).fetchall()
        conn.close()

        # Group by thread
        threads = {}
        for r in rows:
            tid = r["thread_id"]
            if tid not in threads:
                threads[tid] = {"thread_id": tid, "match_count": 0, "signals": []}
            threads[tid]["match_count"] += 1
            threads[tid]["signals"].append({"id": r["signal_id"], "title": r["title"]})

        return jsonify({
            "query": q,
            "thread_matches": list(threads.values()),
            "total_signals": len(rows),
            "total_threads": len(threads),
        })

    @app.route("/api/signals/entity-threads", methods=["GET"])
    def signals_entity_threads_api():
        """Find all thread IDs containing a specific entity."""
        entity_type = request.args.get("type", "")
        entity_value = request.args.get("value", "")
        conn = get_connection(db_path)
        rows = conn.execute(
            """SELECT DISTINCT sc.id FROM signal_clusters sc
               JOIN signal_cluster_items sci ON sci.cluster_id = sc.id
               JOIN signal_entities se ON se.signal_id = sci.signal_id
               WHERE se.entity_type = ? AND (
                 LOWER(se.entity_value) = LOWER(?) OR
                 LOWER(se.normalized_value) = LOWER(?)
               )""",
            (entity_type, entity_value, entity_value),
        ).fetchall()
        conn.close()
        return jsonify({"thread_ids": [r["id"] for r in rows]})

    @app.route("/api/signals/threads/<int:thread_id>/related", methods=["GET"])
    def signals_thread_related_api(thread_id):
        """Find threads that share entities with this thread."""
        conn = get_connection(db_path)
        # Get this thread's entities
        my_entities = conn.execute(
            """SELECT DISTINCT entity_type, COALESCE(normalized_value, entity_value) as name
               FROM signal_entities
               WHERE cluster_id = ? OR signal_id IN
                 (SELECT signal_id FROM signal_cluster_items WHERE cluster_id = ?)""",
            (thread_id, thread_id),
        ).fetchall()
        my_ent_set = {(e["entity_type"], e["name"].lower()) for e in my_entities}
        if not my_ent_set:
            conn.close()
            return jsonify({"related": []})

        # Find other threads that share entities
        all_threads = conn.execute(
            "SELECT id, title, domain FROM signal_clusters WHERE id != ? AND domain != 'narrative'",
            (thread_id,),
        ).fetchall()

        related = []
        for t in all_threads:
            t_ents = conn.execute(
                """SELECT DISTINCT entity_type, COALESCE(normalized_value, entity_value) as name
                   FROM signal_entities
                   WHERE cluster_id = ? OR signal_id IN
                     (SELECT signal_id FROM signal_cluster_items WHERE cluster_id = ?)""",
                (t["id"], t["id"]),
            ).fetchall()
            t_ent_set = {(e["entity_type"], e["name"].lower()) for e in t_ents}
            shared = my_ent_set & t_ent_set
            if len(shared) >= 1:
                shared_list = [{"type": s[0], "name": s[1]} for s in list(shared)[:5]]
                related.append({
                    "id": t["id"], "title": t["title"], "domain": t["domain"],
                    "shared_count": len(shared), "shared_entities": shared_list,
                })

        related.sort(key=lambda x: x["shared_count"], reverse=True)
        conn.close()
        return jsonify({"related": related[:10]})

    @app.route("/api/signals/reassign", methods=["POST"])
    def signals_reassign_api():
        """Move signals from one thread to another."""
        from db import link_signal_to_cluster
        data = request.json or {}
        signal_ids = data.get("signal_ids", [])
        from_thread_id = data.get("from_thread_id")
        to_thread_id = data.get("to_thread_id")
        if not signal_ids or not to_thread_id:
            return jsonify({"error": "signal_ids and to_thread_id required"}), 400

        conn = get_connection(db_path)
        moved = 0
        for sig_id in signal_ids:
            # Remove from old thread if specified
            if from_thread_id:
                conn.execute(
                    "DELETE FROM signal_cluster_items WHERE cluster_id = ? AND signal_id = ?",
                    (from_thread_id, sig_id),
                )
            # Add to new thread
            link_signal_to_cluster(conn, to_thread_id, sig_id)
            moved += 1

        # Update timestamps
        if from_thread_id:
            conn.execute("UPDATE signal_clusters SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (from_thread_id,))
        conn.execute("UPDATE signal_clusters SET last_signal_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (to_thread_id,))
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "moved": moved})

    @app.route("/api/signals/<int:signal_id>/status", methods=["POST"])
    def signals_set_status_api(signal_id):
        """Set a signal's status (signal or noise)."""
        data = request.json or {}
        status = data.get("status", "signal")
        if status not in ("signal", "noise"):
            return jsonify({"error": "status must be 'signal' or 'noise'"}), 400
        from db import set_signal_status
        conn = get_connection(db_path)
        set_signal_status(conn, signal_id, status)
        conn.close()
        return jsonify({"ok": True, "signal_id": signal_id, "status": status})

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

    # ── Quick Capture ──────────────────────────────────────────────────

    @app.route("/capture")
    def capture_page():
        return render_template("capture.html")

    @app.route("/api/signals/manual", methods=["POST"])
    def signals_manual_capture():
        """Manually capture a signal from pasted content (LinkedIn, X, etc.).

        Accepts raw text, auto-parses LinkedIn format, classifies domain,
        runs TF-IDF for immediate thread assignment.
        """
        import hashlib
        import re
        import json as _json
        from datetime import datetime as _dt, timedelta as _td
        from agents.signals_collect import _classify_domain

        data = request.json or {}
        content = (data.get("content") or "").strip()
        if not content:
            return jsonify({"error": "content required"}), 400

        source_tag = data.get("source", "linkedin")  # linkedin, twitter, manual, etc.
        source_url = (data.get("url") or "").strip()
        user_author = (data.get("author") or "").strip()
        user_author_context = (data.get("author_context") or "").strip()
        user_date = (data.get("published_at") or "").strip()

        # ── Smart paste parser (LinkedIn format detection) ──────────
        parsed_author = user_author
        parsed_author_context = user_author_context
        parsed_date = user_date
        parsed_engagement = None
        parsed_content = content

        lines = content.split("\n")
        lines_stripped = [l.strip() for l in lines]

        # Detect LinkedIn format: Name / Title at Company / Time indicator / content
        is_linkedin_format = False
        header_end = 0

        if len(lines_stripped) >= 3:
            # Line 2 often has title/company pattern, line 3 has relative time
            time_pattern = re.compile(
                r"^(\d+[dhwmo]|just now|yesterday|\d+\s*(day|hour|week|month|min)s?\s*ago)",
                re.IGNORECASE,
            )
            # Check lines 1-4 for a time indicator
            for i in range(1, min(5, len(lines_stripped))):
                line = lines_stripped[i]
                # LinkedIn time lines often end with "• 🌐" or "• Edited" or just the time
                clean_line = re.sub(r"[•·🌐🔒]\s*|Edited\s*", "", line).strip()
                if time_pattern.match(clean_line) and len(clean_line) < 40:
                    is_linkedin_format = True
                    header_end = i + 1
                    # Parse relative time to absolute date
                    now = _dt.now()
                    m = re.match(r"(\d+)\s*([dhwmo])", clean_line)
                    if m:
                        n, unit = int(m.group(1)), m.group(2)
                        delta = {"d": _td(days=n), "h": _td(hours=n),
                                 "w": _td(weeks=n), "m": _td(days=n*30),
                                 "o": _td(days=n*30)}.get(unit, _td(days=n))
                        parsed_date = parsed_date or (now - delta).strftime("%Y-%m-%d")
                    elif "yesterday" in clean_line.lower():
                        parsed_date = parsed_date or (now - _td(days=1)).strftime("%Y-%m-%d")
                    elif "just now" in clean_line.lower():
                        parsed_date = parsed_date or now.strftime("%Y-%m-%d")
                    break

        if is_linkedin_format:
            # Line 0 = author name
            if not parsed_author and lines_stripped[0]:
                parsed_author = lines_stripped[0]
            # Lines between name and time = title/company context
            context_lines = [l for l in lines_stripped[1:header_end-1] if l and not re.match(r"^\d+[dhwmo]", l)]
            if not parsed_author_context and context_lines:
                parsed_author_context = " · ".join(context_lines)

            # Extract engagement metrics from bottom
            engagement_pattern = re.compile(
                r"(?:(\d[\d,]*)\s*(?:likes?|reactions?|👍|❤️|🎉))|(?:(\d[\d,]*)\s*comments?)|(?:(\d[\d,]*)\s*reposts?)",
                re.IGNORECASE,
            )
            # Check last 3 lines for engagement
            for line in reversed(lines_stripped[-3:]):
                matches = engagement_pattern.findall(line)
                if matches:
                    eng = {}
                    for likes, comments, reposts in matches:
                        if likes:
                            eng["likes"] = int(likes.replace(",", ""))
                        if comments:
                            eng["comments"] = int(comments.replace(",", ""))
                        if reposts:
                            eng["reposts"] = int(reposts.replace(",", ""))
                    if eng:
                        parsed_engagement = eng
                    break

            # Strip header and engagement lines from content
            # Skip blank lines after header
            body_start = header_end
            while body_start < len(lines_stripped) and not lines_stripped[body_start]:
                body_start += 1
            # Strip engagement footer
            body_end = len(lines)
            if parsed_engagement:
                for i in range(len(lines_stripped) - 1, max(body_start, len(lines_stripped) - 4), -1):
                    if engagement_pattern.search(lines_stripped[i]):
                        body_end = i
                        break
            parsed_content = "\n".join(lines[body_start:body_end]).strip()

        # Strip hashtags from content, preserve as tags
        hashtags = re.findall(r"#(\w+)", parsed_content)
        clean_content = re.sub(r"\s*#\w+", "", parsed_content).strip()

        # ── Build signal dict ──────────────────────────────────────
        title = clean_content[:120].split("\n")[0].rstrip(".")
        if len(clean_content) > 120:
            title = title.rsplit(" ", 1)[0] + "…"

        domain = _classify_domain(title, clean_content)
        content_hash = hashlib.sha256(
            f"manual|{source_url or ''}|{title}".lower().strip().encode()
        ).hexdigest()

        engagement_str = _json.dumps(parsed_engagement) if parsed_engagement else None

        signal_dict = {
            "source": source_tag,
            "domain": domain,
            "title": title,
            "url": source_url,
            "body": clean_content[:2000],
            "published_at": parsed_date or _dt.now().strftime("%Y-%m-%d"),
            "source_name": source_tag.replace("_", " ").title(),
            "content_hash": content_hash,
            "raw_json": _json.dumps({
                "original_paste": content[:3000],
                "hashtags": hashtags,
                "parsed_format": "linkedin" if is_linkedin_format else "raw",
            }),
            "source_type": "social",
            "author": parsed_author or None,
            "author_context": parsed_author_context or None,
            "engagement_json": engagement_str,
        }

        # ── Insert signal ──────────────────────────────────────────
        from db import insert_signal, link_signal_to_cluster
        conn = get_connection(db_path)
        sig_id = insert_signal(conn, signal_dict)

        if not sig_id:
            conn.close()
            return jsonify({"ok": False, "error": "Duplicate signal (already captured)"}), 409

        conn.commit()

        # ── Immediate TF-IDF thread assignment ─────────────────────
        thread_assignment = None
        try:
            from agents.signals_classify import score_signals
            sig_row = conn.execute("SELECT id, title FROM signals WHERE id = ?", (sig_id,)).fetchone()
            if sig_row:
                scored = score_signals(conn, [{"id": sig_row["id"], "title": sig_row["title"]}])
                if scored and scored[0]["confidence"] == "high" and scored[0]["top_thread_id"]:
                    tid = scored[0]["top_thread_id"]
                    link_signal_to_cluster(conn, tid, sig_id)
                    conn.execute(
                        "UPDATE signal_clusters SET last_signal_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (tid,),
                    )
                    conn.commit()
                    top = scored[0]["scores"][0] if scored[0]["scores"] else {}
                    thread_assignment = {
                        "thread_id": tid,
                        "thread_title": top.get("thread_title", ""),
                        "score": scored[0]["top_score"],
                        "confidence": "high",
                    }
                elif scored and scored[0]["confidence"] == "medium" and scored[0]["top_thread_id"]:
                    top = scored[0]["scores"][0] if scored[0]["scores"] else {}
                    thread_assignment = {
                        "thread_id": scored[0]["top_thread_id"],
                        "thread_title": top.get("thread_title", ""),
                        "score": scored[0]["top_score"],
                        "confidence": "medium",
                        "suggestion": True,
                    }
        except Exception as e:
            print(f"[capture] TF-IDF assignment error: {e}")

        conn.close()

        return jsonify({
            "ok": True,
            "signal_id": sig_id,
            "title": title,
            "domain": domain,
            "author": parsed_author,
            "author_context": parsed_author_context,
            "published_at": signal_dict["published_at"],
            "engagement": parsed_engagement,
            "thread_assignment": thread_assignment,
            "parsed_format": "linkedin" if is_linkedin_format else "raw",
        })

    @app.route("/api/signals/search", methods=["POST"])
    def signals_targeted_search_api():
        """Run a targeted signal search for a specific query. Optionally link results to a pattern.

        Searches across ALL sources: Google News, DuckDuckGo News, HackerNews,
        Reddit, Government RSS (keyword-filtered), and FRED (keyword search).
        """
        data = request.json or {}
        query = data.get("query", "").strip()
        pattern_id = data.get("pattern_id")  # optional: link new signals to this pattern
        if not query:
            return jsonify({"error": "query required"}), 400

        from agents.signals_collect import targeted_search
        from db import insert_signal, link_signal_to_cluster

        results, audit = targeted_search(query, days_back=30)

        conn = get_connection(db_path)
        new_count = 0
        linked_count = 0
        _search_to_scrape = []
        for sig in results:
            sig_id = insert_signal(conn, sig)
            if sig_id:
                new_count += 1
                if pattern_id:
                    link_signal_to_cluster(conn, pattern_id, sig_id)
                    linked_count += 1
                # Queue body scraping if body is thin
                url = sig.get("url", "") or ""
                body = sig.get("body", "") or ""
                if url.startswith("http") and len(body) < 200:
                    _search_to_scrape.append((sig_id, url))
            elif pattern_id:
                existing = conn.execute(
                    "SELECT id FROM signals WHERE content_hash = ?", (sig["content_hash"],)
                ).fetchone()
                if existing:
                    link_signal_to_cluster(conn, pattern_id, existing["id"])
                    linked_count += 1
        conn.commit()

        # Background: fetch full article text for thin-body new signals
        if _search_to_scrape:
            for _sid, _url in _search_to_scrape:
                _body_scrape_pool.submit(_scrape_and_update_body, db_path, _sid, _url)

        if pattern_id and linked_count > 0:
            conn.execute(
                "UPDATE signal_clusters SET last_signal_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (pattern_id,),
            )
            conn.commit()

        # Extract entities from newly inserted signals
        if new_count > 0:
            try:
                from agents.signals_synthesize import extract_entities
                from db import get_signals
                recent = get_signals(conn, days_back=1, limit=new_count + 10)
                extract_entities(conn, recent)
            except Exception as e:
                print(f"[search] Entity extraction failed: {e}")

        conn.close()

        return jsonify({
            "ok": True,
            "query": query,
            "total_found": len(results),
            "new_inserted": new_count,
            "linked_to_pattern": linked_count,
            "audit": audit,
        })

    @app.route("/api/signals/patterns/<int:pattern_id>/signals", methods=["GET"])
    def signals_pattern_signals_api(pattern_id):
        """Get signals inside a pattern for sub-graph rendering."""
        conn = get_connection(db_path)
        signals = conn.execute(
            """SELECT s.id, s.title, s.domain, s.source, s.source_name, s.url,
                      s.published_at, s.signal_status, SUBSTR(s.body, 1, 300) as body_snippet, LENGTH(s.body) as body_len
               FROM signals s
               JOIN signal_cluster_items sci ON sci.signal_id = s.id
               WHERE sci.cluster_id = ?
               ORDER BY s.collected_at DESC""",
            (pattern_id,),
        ).fetchall()

        # Get pattern info
        pattern = conn.execute(
            "SELECT id, title, domain, synthesis FROM signal_clusters WHERE id = ?",
            (pattern_id,),
        ).fetchone()

        # Get entities for these signals
        entities = conn.execute(
            """SELECT DISTINCT entity_type, COALESCE(normalized_value, entity_value) as name, signal_id
               FROM signal_entities
               WHERE signal_id IN (SELECT signal_id FROM signal_cluster_items WHERE cluster_id = ?)""",
            (pattern_id,),
        ).fetchall()

        # Build entity-based edges between signals (shared entities)
        sig_entities = {}
        for e in entities:
            sid = e["signal_id"]
            if sid not in sig_entities:
                sig_entities[sid] = set()
            sig_entities[sid].add((e["entity_type"], e["name"]))

        edges = []
        sig_ids = [s["id"] for s in signals]
        for i, a in enumerate(sig_ids):
            for b in sig_ids[i+1:]:
                shared = (sig_entities.get(a, set()) & sig_entities.get(b, set()))
                if shared:
                    edges.append({
                        "source": a, "target": b,
                        "shared": [{"type": t, "name": n} for t, n in shared],
                    })

        conn.close()
        return jsonify({
            "pattern": dict(pattern) if pattern else None,
            "signals": [dict(s) for s in signals],
            "edges": edges,
        })

    @app.route("/api/signals/threads/create", methods=["POST"])
    def signals_create_thread_api():
        """Create a thread manually, optionally with pasted content split into signals."""
        import hashlib
        from db import insert_signal_cluster, link_signal_to_cluster, insert_signal
        from agents.signals_collect import _classify_domain

        data = request.json or {}
        title = (data.get("title") or "").strip()
        paste = (data.get("content") or "").strip()
        if not title:
            return jsonify({"error": "title required"}), 400

        domain = _classify_domain(title, paste)
        conn = get_connection(db_path)
        thread_id = insert_signal_cluster(conn, {"domain": domain, "title": title, "synthesis": ""})
        conn.execute("UPDATE signal_clusters SET last_signal_at = CURRENT_TIMESTAMP WHERE id = ?", (thread_id,))

        # If paste content provided, split into signals and link to thread
        signals_created = 0
        if paste:
            import re
            # Split on bullet points, numbered items, or double newlines
            items = re.split(r'\n\s*[-•·]\s+|\n\s*\d+[.)]\s+|\n\s*\n', paste)
            items = [item.strip() for item in items if item.strip() and len(item.strip()) > 15]
            if not items:
                items = [paste]

            for item in items:
                sig_title = item[:120].split('\n')[0].rstrip('.')
                if len(item) > 120:
                    sig_title = sig_title.rsplit(' ', 1)[0] + '…'
                content_hash = hashlib.sha256(f"manual||{sig_title}".lower().strip().encode()).hexdigest()
                sig_id = insert_signal(conn, {
                    "source": "manual",
                    "domain": domain,
                    "title": sig_title,
                    "url": "",
                    "body": item[:2000],
                    "published_at": "",
                    "source_name": "Manual",
                    "content_hash": content_hash,
                    "source_type": "social",
                })
                if sig_id:
                    link_signal_to_cluster(conn, thread_id, sig_id)
                    signals_created += 1

        conn.commit()
        conn.close()
        return jsonify({"ok": True, "thread_id": thread_id, "signals_created": signals_created})

    @app.route("/api/signals/patterns", methods=["POST"])
    def signals_create_pattern_api():
        """Manually create a pattern from selected signal IDs."""
        data = request.json or {}
        title = data.get("title", "").strip()
        signal_ids = data.get("signal_ids", [])
        if not title or not signal_ids:
            return jsonify({"error": "title and signal_ids required"}), 400

        from db import insert_signal_cluster, link_signal_to_cluster

        conn = get_connection(db_path)
        # Determine domain from signals
        domains = conn.execute(
            f"SELECT domain, COUNT(*) as cnt FROM signals WHERE id IN ({','.join('?' * len(signal_ids))}) GROUP BY domain ORDER BY cnt DESC",
            signal_ids,
        ).fetchall()
        domain = domains[0]["domain"] if domains else "economics"

        pattern_id = insert_signal_cluster(conn, {
            "domain": domain,
            "title": title,
            "synthesis": data.get("summary", ""),
        })
        conn.execute(
            "UPDATE signal_clusters SET last_signal_at = CURRENT_TIMESTAMP WHERE id = ?",
            (pattern_id,),
        )
        for sid in signal_ids:
            link_signal_to_cluster(conn, pattern_id, sid)
        conn.commit()
        conn.close()

        return jsonify({"ok": True, "pattern_id": pattern_id})

    @app.route("/api/signals/resynthesize", methods=["POST"])
    def signals_resynthesize_api():
        """Re-run pattern detection on unassigned signals. SSE-streamed."""
        def generate():
            # Pre-fetch unassigned signals on main thread, pass data (not conn) to worker
            pre_conn = get_connection(db_path)
            unassigned = pre_conn.execute(
                """SELECT * FROM signals
                   WHERE id NOT IN (SELECT signal_id FROM signal_cluster_items)
                   ORDER BY collected_at DESC LIMIT 500"""
            ).fetchall()
            unassigned = [dict(r) for r in unassigned]
            pre_conn.close()

            if not unassigned:
                yield f"data: {json.dumps({'type': 'status', 'text': 'All signals are already in threads.'})}\n\n"
                yield f"data: {json.dumps({'type': 'resynth_complete', 'new_patterns': 0, 'assigned': 0})}\n\n"
                return

            yield f"data: {json.dumps({'type': 'status', 'text': f'Analyzing {len(unassigned)} unassigned signals...'})}\n\n"

            synth_q = queue.Queue()
            result_box = [None]

            def _cb(event_type, ev_data):
                synth_q.put((event_type, ev_data or {}))

            def _run():
                # Create connection inside the thread — SQLite requires same-thread access
                from agents.signals_synthesize import synthesize_into_threads, enrich_thread_signals, extract_entities
                from agents.signals_classify import keyword_assign
                conn = get_connection(db_path)
                try:
                    # ── Tier 1: TF-IDF keyword assignment (instant, no LLM) ──
                    _cb("status", {"text": f"Tier 1: keyword matching {len(unassigned)} signals..."})
                    kw_result = keyword_assign(conn, unassigned, progress_cb=_cb)
                    kw_assigned = len(kw_result["assigned"])
                    needs_llm = kw_result["needs_llm"]
                    needs_review = kw_result["needs_review"]
                    _cb("status", {"text": f"Tier 1 done: {kw_assigned} auto-assigned, {len(needs_llm)} for LLM, {len(needs_review)} for review"})

                    # ── Tier 2: LLM assignment for medium-confidence signals (batches of 10) ──
                    total_new = 0
                    total_llm_assigned = 0
                    if needs_llm:
                        _cb("status", {"text": f"Tier 2: LLM analyzing {len(needs_llm)} signals..."})
                        for i in range(0, len(needs_llm), 10):
                            batch = needs_llm[i:i+10]
                            batch_num = i // 10 + 1
                            total_batches = (len(needs_llm) + 9) // 10
                            _cb("status", {"text": f"Tier 2 batch {batch_num}/{total_batches}: {len(batch)} signals..."})
                            result = synthesize_into_threads(conn, batch, progress_cb=_cb)
                            total_new += result.get("new_thread_count", 0)
                            total_llm_assigned += result.get("assigned_count", 0)

                    total_assigned = kw_assigned + total_llm_assigned
                    result_box[0] = {
                        "new_thread_count": total_new,
                        "assigned_count": total_assigned,
                        "keyword_assigned": kw_assigned,
                        "llm_assigned": total_llm_assigned,
                        "needs_review": len(needs_review),
                    }

                    # Commit and release between phases so other connections can write
                    conn.commit()
                    conn.close()

                    _cb("status", {"text": "Enriching articles..."})
                    conn = get_connection(db_path)
                    enrich_thread_signals(conn, progress_cb=_cb)
                    conn.commit()
                    conn.close()

                    _cb("status", {"text": "Extracting entities..."})
                    conn = get_connection(db_path)
                    newly_assigned = conn.execute(
                        """SELECT * FROM signals WHERE id IN (SELECT signal_id FROM signal_cluster_items) ORDER BY collected_at DESC LIMIT 200"""
                    ).fetchall()
                    extract_entities(conn, [dict(r) for r in newly_assigned], progress_cb=_cb)
                except Exception as exc:
                    import traceback
                    traceback.print_exc()
                    synth_q.put(("error", {"text": str(exc)}))
                finally:
                    try:
                        conn.close()
                    except Exception:
                        pass
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

            t.join(timeout=300)
            sr = result_box[0] or {}
            yield f"data: {json.dumps({'type': 'resynth_complete', 'new_patterns': sr.get('new_thread_count', 0), 'assigned': sr.get('assigned_count', 0), 'keyword_assigned': sr.get('keyword_assigned', 0), 'llm_assigned': sr.get('llm_assigned', 0), 'needs_review': sr.get('needs_review', 0)})}\n\n"

        return Response(generate(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.route("/api/signals/<int:signal_id>", methods=["PATCH"])
    def signals_update_api(signal_id):
        """Update a signal's title."""
        data = request.json or {}
        title = (data.get("title") or "").strip()
        if not title:
            return jsonify({"error": "title required"}), 400
        conn = get_connection(db_path)
        conn.execute("UPDATE signals SET title = ? WHERE id = ?", (title, signal_id))
        conn.commit()
        conn.close()
        return jsonify({"ok": True})

    @app.route("/api/signals/review-queue", methods=["GET"])
    def signals_review_queue_api():
        """Get unassigned signals with TF-IDF thread suggestions for user review."""
        from agents.signals_classify import score_signals, build_thread_profiles

        limit = int(request.args.get("limit", 50))
        offset = int(request.args.get("offset", 0))

        conn = get_connection(db_path)
        unassigned = conn.execute(
            """SELECT * FROM signals
               WHERE id NOT IN (SELECT signal_id FROM signal_cluster_items)
               AND COALESCE(signal_status, 'signal') != 'noise'
               ORDER BY collected_at DESC LIMIT ? OFFSET ?""",
            (limit, offset),
        ).fetchall()
        unassigned = [dict(r) for r in unassigned]

        total_unassigned = conn.execute(
            """SELECT COUNT(*) as c FROM signals
               WHERE id NOT IN (SELECT signal_id FROM signal_cluster_items)
               AND COALESCE(signal_status, 'signal') != 'noise'"""
        ).fetchone()["c"]

        if not unassigned:
            conn.close()
            return jsonify({"signals": [], "total": total_unassigned})

        profile = build_thread_profiles(conn)
        scored = score_signals(conn, unassigned, profile)

        # Pre-compute temporal outlier info for each suggestion
        from db import get_signal_effective_date, get_thread_date_range
        from datetime import datetime as _rqdt, timedelta as _rqtd
        _RQ_WINDOW = _rqtd(days=30)
        _thread_range_cache = {}

        def _rq_thread_range(tid):
            if tid not in _thread_range_cache:
                _thread_range_cache[tid] = get_thread_date_range(conn, tid)
            return _thread_range_cache[tid]

        items = []
        for sc in scored:
            sig = next((s for s in unassigned if s["id"] == sc["signal_id"]), {})
            sig_date = get_signal_effective_date(sig)

            suggestions_out = []
            for s in sc["scores"][:3]:
                outlier = False
                thread_range_str = None
                if sig_date:
                    try:
                        tmin, tmax, _ = _rq_thread_range(s["thread_id"])
                        if tmin and tmax:
                            _sd = _rqdt.strptime(sig_date, "%Y-%m-%d")
                            if (_sd < _rqdt.strptime(tmin, "%Y-%m-%d") - _RQ_WINDOW or
                                    _sd > _rqdt.strptime(tmax, "%Y-%m-%d") + _RQ_WINDOW):
                                outlier = True
                                thread_range_str = f"{tmin[:7]}–{tmax[:7]}"
                    except Exception:
                        pass
                suggestions_out.append({**s, "temporal_outlier": outlier,
                                         "thread_range": thread_range_str})

            items.append({
                "id": sc["signal_id"],
                "title": sc["signal_title"],
                "source_name": sig.get("source_name", sig.get("source", "")),
                "published_at": sig.get("published_at", ""),
                "domain": sig.get("domain", ""),
                "body": (sig.get("body") or "")[:500],
                "url": sig.get("url", ""),
                "confidence": sc["confidence"],
                "suggestions": suggestions_out,
                "temporal_outlier": bool(suggestions_out and suggestions_out[0]["temporal_outlier"]),
            })

        conn.close()
        return jsonify({"signals": items, "total": total_unassigned, "offset": offset, "limit": limit})

    @app.route("/api/signals/review-queue/assign", methods=["POST"])
    def signals_review_assign_api():
        """Assign a signal to a thread from the review queue."""
        from db import link_signal_to_cluster

        data = request.json or {}
        signal_id = data.get("signal_id")
        thread_id = data.get("thread_id")
        if not signal_id or not thread_id:
            return jsonify({"error": "signal_id and thread_id required"}), 400

        conn = get_connection(db_path)
        link_signal_to_cluster(conn, thread_id, signal_id)
        conn.execute(
            "UPDATE signal_clusters SET last_signal_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (thread_id,),
        )
        conn.commit()
        conn.close()
        _review_groups_cache["key"] = None  # invalidate groups cache
        return jsonify({"ok": True})

    @app.route("/api/signals/review-queue/dismiss", methods=["POST"])
    def signals_review_dismiss_api():
        """Mark a signal as noise (dismiss from review queue)."""
        data = request.json or {}
        signal_id = data.get("signal_id")
        if not signal_id:
            return jsonify({"error": "signal_id required"}), 400

        conn = get_connection(db_path)
        conn.execute("UPDATE signals SET signal_status = 'noise' WHERE id = ?", (signal_id,))
        conn.commit()
        conn.close()
        _review_groups_cache["key"] = None  # invalidate groups cache
        return jsonify({"ok": True})

    @app.route("/api/signals/review-queue/dismiss-all", methods=["POST"])
    def signals_review_dismiss_all_api():
        """Mark ALL remaining unassigned signals as noise."""
        conn = get_connection(db_path)
        conn.execute(
            """UPDATE signals SET signal_status = 'noise' 
               WHERE signal_status != 'noise' AND id NOT IN (SELECT signal_id FROM signal_cluster_items)"""
        )
        count = conn.execute("SELECT changes()").fetchone()[0]
        conn.commit()
        conn.close()
        _review_groups_cache["key"] = None  # invalidate groups cache
        return jsonify({"ok": True, "count": count})

    @app.route("/api/signals/review-queue/unassign", methods=["POST"])
    def signals_review_unassign_api():
        """Remove a signal from a thread (undo assignment)."""
        data = request.json or {}
        signal_id = data.get("signal_id")
        thread_id = data.get("thread_id")
        if not signal_id:
            return jsonify({"error": "signal_id required"}), 400

        conn = get_connection(db_path)
        if thread_id:
            conn.execute("DELETE FROM signal_cluster_items WHERE signal_id = ? AND cluster_id = ?", (signal_id, thread_id))
        else:
            conn.execute("DELETE FROM signal_cluster_items WHERE signal_id = ?", (signal_id,))
        conn.commit()
        conn.close()
        return jsonify({"ok": True})

    @app.route("/api/signals/review-queue/undismiss", methods=["POST"])
    def signals_review_undismiss_api():
        """Restore a dismissed signal (undo noise mark)."""
        data = request.json or {}
        signal_id = data.get("signal_id")
        if not signal_id:
            return jsonify({"error": "signal_id required"}), 400

        conn = get_connection(db_path)
        conn.execute("UPDATE signals SET signal_status = 'signal' WHERE id = ?", (signal_id,))
        conn.commit()
        conn.close()
        return jsonify({"ok": True})

    @app.route("/api/signals/noise-count", methods=["GET"])
    def signals_noise_count_api():
        conn = get_connection(db_path)
        count = conn.execute("SELECT COUNT(*) as c FROM signals WHERE signal_status = 'noise'").fetchone()["c"]
        conn.close()
        return jsonify({"count": count})

    @app.route("/api/signals/noise", methods=["GET"])
    def signals_noise_list_api():
        limit = int(request.args.get("limit", 50))
        conn = get_connection(db_path)
        rows = conn.execute(
            "SELECT id, title, source_name, published_at FROM signals WHERE signal_status = 'noise' ORDER BY collected_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        conn.close()
        return jsonify({"signals": [dict(r) for r in rows]})

    @app.route("/api/signals/noise", methods=["DELETE"])
    def signals_noise_delete_api():
        conn = get_connection(db_path)
        cur = conn.execute("DELETE FROM signals WHERE signal_status = 'noise'")
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "deleted": cur.rowcount})

    _review_groups_cache = {"key": None, "data": None}

    @app.route("/api/signals/review-queue/groups", methods=["GET"])
    def signals_review_queue_groups_api():
        """Cluster unassigned signals by title similarity, return grouped + ungrouped with TF-IDF suggestions.
        Results are cached in memory — only recomputed when the set of unassigned signals changes."""
        from difflib import SequenceMatcher
        from agents.signals_classify import score_signals, build_thread_profiles

        conn = get_connection(db_path)
        unassigned = conn.execute(
            """SELECT * FROM signals
               WHERE id NOT IN (SELECT signal_id FROM signal_cluster_items)
               AND COALESCE(signal_status, 'signal') != 'noise'
               ORDER BY collected_at DESC LIMIT 500"""
        ).fetchall()
        unassigned = [dict(r) for r in unassigned]
        total_unassigned = len(unassigned)

        if not unassigned:
            conn.close()
            return jsonify({"groups": [], "ungrouped": [], "total_unassigned": 0})

        # Check cache — return instantly if unassigned signal set hasn't changed
        cache_key = hash(tuple(sorted(s["id"] for s in unassigned)))
        if _review_groups_cache["key"] == cache_key and _review_groups_cache["data"]:
            conn.close()
            return jsonify(_review_groups_cache["data"])

        # Cluster by title similarity (0.65 threshold) — transitive grouping
        THRESHOLD = 0.65
        seen = set()
        groups = []
        ungrouped_signals = []

        for i in range(len(unassigned)):
            if unassigned[i]["id"] in seen:
                continue
            group = [unassigned[i]]
            group_titles = [(unassigned[i]["title"] or "").lower()]
            # Scan remaining signals; re-scan when group grows (transitive closure)
            changed = True
            while changed:
                changed = False
                for j in range(i + 1, len(unassigned)):
                    if unassigned[j]["id"] in seen:
                        continue
                    title_j = (unassigned[j]["title"] or "").lower()
                    # Match against ANY title already in the group
                    if any(SequenceMatcher(None, gt, title_j).ratio() >= THRESHOLD for gt in group_titles):
                        group.append(unassigned[j])
                        group_titles.append(title_j)
                        seen.add(unassigned[j]["id"])
                        changed = True
            if len(group) > 1:
                seen.add(unassigned[i]["id"])
                groups.append(group)
            else:
                ungrouped_signals.append(unassigned[i])

        # Build TF-IDF profile once for scoring
        try:
            profile = build_thread_profiles(conn)
        except Exception:
            profile = None

        # Score each group
        group_results = []
        for g in groups:
            representative = max(g, key=lambda s: len(s.get("title") or ""))
            top_suggestion = None
            all_suggestions = []
            if profile:
                try:
                    scored = score_signals(conn, [representative], profile)
                    if scored and scored[0].get("scores"):
                        all_suggestions = [{"thread_id": s["thread_id"], "thread_title": s["thread_title"], "score": round(s["score"], 3)} for s in scored[0]["scores"][:3]]
                        if all_suggestions:
                            top_suggestion = all_suggestions[0]
                except Exception:
                    pass
            group_results.append({
                "group_title": representative.get("title", ""),
                "signals": [{"id": s["id"], "title": s.get("title", ""), "source_name": s.get("source_name", s.get("source", "")), "published_at": s.get("published_at", ""), "domain": s.get("domain", "")} for s in g],
                "suggested_thread": top_suggestion,
                "all_suggestions": all_suggestions,
            })

        # Score ungrouped signals
        ungrouped_results = []
        if ungrouped_signals and profile:
            try:
                scored_all = score_signals(conn, ungrouped_signals, profile)
                for sc in scored_all:
                    sig = next((s for s in ungrouped_signals if s["id"] == sc["signal_id"]), {})
                    ungrouped_results.append({
                        "id": sc["signal_id"], "title": sc.get("signal_title", ""),
                        "source_name": sig.get("source_name", sig.get("source", "")),
                        "published_at": sig.get("published_at", ""), "domain": sig.get("domain", ""),
                        "confidence": sc.get("confidence", "low"),
                        "suggestions": [{"thread_id": s["thread_id"], "thread_title": s["thread_title"], "score": round(s["score"], 3)} for s in sc.get("scores", [])[:3]],
                    })
            except Exception:
                ungrouped_results = [{"id": s["id"], "title": s.get("title", ""), "source_name": s.get("source_name", ""), "published_at": s.get("published_at", ""), "domain": s.get("domain", ""), "confidence": "low", "suggestions": []} for s in ungrouped_signals]
        elif ungrouped_signals:
            ungrouped_results = [{"id": s["id"], "title": s.get("title", ""), "source_name": s.get("source_name", ""), "published_at": s.get("published_at", ""), "domain": s.get("domain", ""), "confidence": "low", "suggestions": []} for s in ungrouped_signals]

        conn.close()
        # Sort groups by size (largest first)
        group_results.sort(key=lambda g: len(g["signals"]), reverse=True)
        result = {"groups": group_results, "ungrouped": ungrouped_results, "total_unassigned": total_unassigned}
        _review_groups_cache["key"] = cache_key
        _review_groups_cache["data"] = result
        return jsonify(result)

    @app.route("/api/signals/review-queue/bulk-assign", methods=["POST"])
    def signals_review_bulk_assign_api():
        """Assign multiple signals to a thread at once."""
        from db import link_signal_to_cluster
        data = request.json or {}
        signal_ids = data.get("signal_ids", [])
        thread_id = data.get("thread_id")
        if not signal_ids or not thread_id:
            return jsonify({"error": "signal_ids and thread_id required"}), 400
        conn = get_connection(db_path)
        count = 0
        for sid in signal_ids:
            link_signal_to_cluster(conn, thread_id, sid)
            count += 1
        conn.execute("UPDATE signal_clusters SET last_signal_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (thread_id,))
        conn.commit()
        conn.close()
        _review_groups_cache["key"] = None  # invalidate groups cache
        return jsonify({"ok": True, "assigned": count})

    @app.route("/api/signals/prune", methods=["POST"])
    def signals_prune_api():
        """Deduplicate signals by title similarity (>=85%). Keeps earliest, marks rest as noise.
        Reassigns thread links from pruned signals to the primary."""
        from difflib import SequenceMatcher

        conn = get_connection(db_path)
        signals = conn.execute(
            "SELECT id, title, collected_at FROM signals WHERE signal_status != 'noise' ORDER BY collected_at ASC"
        ).fetchall()
        signals = [dict(s) for s in signals]

        # Build dupe groups
        seen = set()
        groups = []
        for i in range(len(signals)):
            if signals[i]["id"] in seen:
                continue
            group = [signals[i]]
            title_i = (signals[i]["title"] or "").lower()
            for j in range(i + 1, len(signals)):
                if signals[j]["id"] in seen:
                    continue
                title_j = (signals[j]["title"] or "").lower()
                if SequenceMatcher(None, title_i, title_j).ratio() >= 0.85:
                    group.append(signals[j])
                    seen.add(signals[j]["id"])
            if len(group) > 1:
                seen.add(signals[i]["id"])
                groups.append(group)

        # Consolidate: keep first (earliest), mark rest as noise, transfer thread links
        pruned = 0
        for group in groups:
            primary = group[0]  # earliest by collected_at
            for dup in group[1:]:
                # Transfer any thread assignments from dup to primary (if primary isn't already in that thread)
                dup_threads = conn.execute(
                    "SELECT cluster_id FROM signal_cluster_items WHERE signal_id = ?", (dup["id"],)
                ).fetchall()
                for row in dup_threads:
                    existing = conn.execute(
                        "SELECT 1 FROM signal_cluster_items WHERE signal_id = ? AND cluster_id = ?",
                        (primary["id"], row["cluster_id"]),
                    ).fetchone()
                    if not existing:
                        conn.execute(
                            "INSERT OR IGNORE INTO signal_cluster_items (signal_id, cluster_id) VALUES (?, ?)",
                            (primary["id"], row["cluster_id"]),
                        )
                    conn.execute(
                        "DELETE FROM signal_cluster_items WHERE signal_id = ? AND cluster_id = ?",
                        (dup["id"], row["cluster_id"]),
                    )
                # Mark as noise
                conn.execute("UPDATE signals SET signal_status = 'noise' WHERE id = ?", (dup["id"],))
                pruned += 1

        conn.commit()
        conn.close()
        return jsonify({"ok": True, "groups": len(groups), "pruned": pruned})

    @app.route("/api/signals/merge-threads", methods=["POST"])
    def signals_merge_threads_api():
        """Merge duplicate threads by title similarity. Keeps highest-signal thread per group."""
        from db import merge_duplicate_threads
        conn = get_connection(db_path)
        result = merge_duplicate_threads(conn)
        conn.close()
        return jsonify({"ok": True, **result})

    @app.route("/api/signals/threads/<int:thread_id>", methods=["DELETE"])
    def signals_delete_thread_api(thread_id):
        """Delete a thread — unlinks signals (they become unassigned), removes links."""
        conn = get_connection(db_path)
        # Unlink signals (they go back to unassigned pool)
        conn.execute("DELETE FROM signal_cluster_items WHERE cluster_id = ?", (thread_id,))
        # Remove thread links
        conn.execute("DELETE FROM thread_links WHERE thread_a_id = ? OR thread_b_id = ?", (thread_id, thread_id))
        conn.execute("DELETE FROM causal_links WHERE cause_thread_id = ? OR effect_thread_id = ?", (thread_id, thread_id))
        conn.execute("DELETE FROM board_positions WHERE node_type = 'thread' AND node_id = ?", (thread_id,))
        # Mark as deleted
        conn.execute("UPDATE signal_clusters SET status = 'deleted' WHERE id = ?", (thread_id,))
        conn.commit()
        conn.close()
        return jsonify({"ok": True})

    @app.route("/api/signals/threads/<int:thread_id>", methods=["PATCH"])
    def signals_rename_thread_api(thread_id):
        """Rename a thread."""
        data = request.json or {}
        title = data.get("title", "").strip()
        if not title:
            return jsonify({"error": "title required"}), 400
        conn = get_connection(db_path)
        conn.execute("UPDATE signal_clusters SET title = ? WHERE id = ?", (title, thread_id))
        conn.commit()
        conn.close()
        return jsonify({"ok": True})

    @app.route("/api/signals/threads/bulk-delete", methods=["POST"])
    def signals_bulk_delete_threads_api():
        """Delete multiple threads at once."""
        data = request.json or {}
        thread_ids = data.get("thread_ids", [])
        if not thread_ids:
            return jsonify({"error": "thread_ids required"}), 400
        conn = get_connection(db_path)
        for tid in thread_ids:
            conn.execute("DELETE FROM signal_cluster_items WHERE cluster_id = ?", (tid,))
            conn.execute("DELETE FROM thread_links WHERE thread_a_id = ? OR thread_b_id = ?", (tid, tid))
            conn.execute("DELETE FROM causal_links WHERE cause_thread_id = ? OR effect_thread_id = ?", (tid, tid))
            conn.execute("DELETE FROM board_positions WHERE node_type = 'thread' AND node_id = ?", (tid,))
            conn.execute("UPDATE signal_clusters SET status = 'deleted' WHERE id = ?", (tid,))
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "deleted": len(thread_ids)})

    @app.route("/api/signals/retitle-threads", methods=["POST"])
    def signals_retitle_threads_api():
        """Re-title all active threads using LLM to generate directional, specific titles."""
        from agents.llm import generate_json, CHEAP_CHAIN

        conn = get_connection(db_path)
        threads = conn.execute(
            """SELECT sc.id, sc.title, sc.domain, sc.synthesis,
                      GROUP_CONCAT(s.title, ' | ') as signal_titles
               FROM signal_clusters sc
               LEFT JOIN signal_cluster_items sci ON sci.cluster_id = sc.id
               LEFT JOIN signals s ON s.id = sci.signal_id
               WHERE sc.status = 'active' AND sc.domain != 'narrative'
               GROUP BY sc.id
               ORDER BY sc.id"""
        ).fetchall()

        updated = 0
        errors = 0
        for t in threads:
            t = dict(t)
            signals_preview = (t.get("signal_titles") or "")[:500]
            if not signals_preview:
                continue

            prompt = f"""Rewrite this thread title to be DIRECTIONAL and SPECIFIC.

Current title: {t['title']}
Current summary: {(t.get('synthesis') or '')[:200]}
Sample signals in this thread: {signals_preview}

Rules:
- Title MUST take a DIRECTION (something is going up, down, accelerating, declining, breaking, shifting)
- BAD: "Labor Market Trends" → GOOD: "US Job Market Holding Steady Despite Tech Layoffs"
- BAD: "Stock Market Rotation" → GOOD: "Investors Rotating from Tech into Defensive Sectors"
- BAD: "Supply Chain Disruptions" → GOOD: "Semiconductor Supply Chains Fracturing on US-China Tariffs"
- BAD: "Remote Work Trends" → GOOD: "Remote Work Expanding as Companies Cut Office Costs"
- Be specific about WHO and WHAT DIRECTION. No vague "mixed" or "divergence" or "trends".
- Keep it under 60 characters if possible.

Return JSON: {{"title": "New directional title", "summary": "Updated 1-2 sentence summary with specific direction and evidence"}}
Return ONLY the JSON."""

            try:
                result = generate_json(prompt, timeout=15, chain=CHEAP_CHAIN)
                if result and result.get("title"):
                    new_title = result["title"][:100]
                    new_summary = result.get("summary", t.get("synthesis", ""))[:500]
                    conn.execute(
                        "UPDATE signal_clusters SET title = ?, synthesis = ? WHERE id = ?",
                        (new_title, new_summary, t["id"])
                    )
                    updated += 1
                    print(f"[retitle] {t['title'][:40]} → {new_title[:40]}")
            except Exception as e:
                print(f"[retitle] Error on thread {t['id']}: {e}")
                errors += 1

        conn.commit()
        conn.close()
        return jsonify({"ok": True, "updated": updated, "errors": errors, "total": len(threads)})

    @app.route("/api/signals/timeline", methods=["GET"])
    def signals_timeline_api():
        """Signal timeline data — all signals with dates, grouped by thread."""
        days = int(request.args.get("days", 30))
        conn = get_connection(db_path)
        rows = conn.execute(
            """SELECT s.id, s.title, s.domain, s.source, s.published_at,
                      sci.cluster_id as thread_id, sc.title as thread_title
               FROM signals s
               LEFT JOIN signal_cluster_items sci ON sci.signal_id = s.id
               LEFT JOIN signal_clusters sc ON sc.id = sci.cluster_id AND sc.domain != 'narrative'
               WHERE s.published_at IS NOT NULL AND s.published_at != ''
                 AND s.published_at >= date('now', ?)
                 AND s.signal_status != 'noise'
               ORDER BY s.published_at""",
            (f"-{days} days",),
        ).fetchall()
        conn.close()

        signals = [dict(r) for r in rows]
        # Compute thread summary: first/last date, signal count
        thread_spans = {}
        for s in signals:
            tid = s.get("thread_id")
            if not tid:
                continue
            pub = s.get("published_at", "")[:10]
            if tid not in thread_spans:
                thread_spans[tid] = {"thread_id": tid, "title": s.get("thread_title", ""), "domain": s.get("domain", ""), "first": pub, "last": pub, "count": 0}
            thread_spans[tid]["count"] += 1
            if pub < thread_spans[tid]["first"]:
                thread_spans[tid]["first"] = pub
            if pub > thread_spans[tid]["last"]:
                thread_spans[tid]["last"] = pub

        return jsonify({
            "signals": signals,
            "thread_spans": list(thread_spans.values()),
            "days": days,
        })

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
        from db import get_signal_clusters, get_pattern_signal_noise_counts
        from agents.signals_synthesize import compute_thread_momentum

        status = request.args.get("status", "all")
        domain = request.args.get("domain") or None
        limit = int(request.args.get("limit", 200))
        min_signals = int(request.args.get("min_signals", 0))
        # Exclude narrative threads from graph by default (they belong in their narrative context)
        exclude_domain = None if domain else "narrative"

        conn = get_connection(db_path)
        threads = get_signal_clusters(conn, status=status, limit=limit, domain=domain, min_signals=min_signals, exclude_domain=exclude_domain)

        # Build nodes
        nodes = []
        for t in threads:
            t["momentum"] = compute_thread_momentum(conn, t["id"])
            sn = get_pattern_signal_noise_counts(conn, t["id"])
            nodes.append({
                "id": t["id"],
                "title": t["title"],
                "domain": t["domain"],
                "signal_count": sn["signal_count"],
                "noise_count": sn["noise_count"],
                "total_count": sn["total"],
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

        # Count unassigned signals
        total_signals = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
        assigned_signals = conn.execute("SELECT COUNT(DISTINCT signal_id) FROM signal_cluster_items").fetchone()[0]

        conn.close()
        return jsonify({
            "nodes": nodes,
            "edges": edges,
            "total_signals": total_signals,
            "assigned_signals": assigned_signals,
            "unassigned_signals": total_signals - assigned_signals,
        })

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
            # Persist brainstorm — collect titles at save time so they survive thread merges/deletes
            from db import save_brainstorm, insert_hypothesis, get_cluster_detail as _gcd
            thread_titles = []
            for tid in thread_ids:
                d = get_cluster_detail(conn, tid)
                thread_titles.append(d["title"] if d else f"Thread {tid}")
            brainstorm_id = save_brainstorm(conn, thread_ids, result, thread_titles=thread_titles)
            result["brainstorm_id"] = brainstorm_id

            # Auto-save hypotheses to the bank
            # Gather source entities from the threads
            placeholders = ",".join("?" * len(thread_ids))
            entities = conn.execute(
                f"""SELECT DISTINCT COALESCE(normalized_value, entity_value) as name
                    FROM signal_entities
                    WHERE cluster_id IN ({placeholders}) OR signal_id IN
                      (SELECT signal_id FROM signal_cluster_items WHERE cluster_id IN ({placeholders}))""",
                (*thread_ids, *thread_ids),
            ).fetchall()
            source_entities = [e["name"] for e in entities]

            saved_hyp_ids = []
            for h in result.get("hypotheses", []):
                hid = insert_hypothesis(conn, {
                    "title": h.get("title", ""),
                    "reasoning": h.get("reasoning", ""),
                    "confidence": h.get("confidence", "medium"),
                    "investigate_query": h.get("investigate", ""),
                    "source_thread_ids": thread_ids,
                    "source_entities": source_entities,
                    "brainstorm_id": brainstorm_id,
                })
                saved_hyp_ids.append(hid)
            result["saved_hypothesis_ids"] = saved_hyp_ids

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
        # Use stored titles (set at save time). For old rows without stored titles, fall back to live lookup.
        needs_live = any(not b.get("thread_titles") for b in brainstorms)
        if needs_live:
            all_threads = {t["id"]: t for t in get_signal_clusters(conn, status="all", limit=2000)}
        for b in brainstorms:
            if not b.get("thread_titles"):
                b["thread_titles"] = [all_threads.get(tid, {}).get("title", f"Thread {tid}") for tid in b.get("thread_ids", [])]
        conn.close()
        return jsonify({"brainstorms": brainstorms})

    @app.route("/api/signals/brainstorms/repair-titles", methods=["POST"])
    def signals_brainstorms_repair_titles_api():
        """Backfill thread_titles_json for old brainstorms that don't have stored titles."""
        from db import get_brainstorms, get_signal_clusters, get_cluster_detail
        conn = get_connection(db_path)
        brainstorms = get_brainstorms(conn, limit=500)
        all_threads = {t["id"]: t for t in get_signal_clusters(conn, status="all", limit=2000)}
        updated = 0
        for b in brainstorms:
            if b.get("thread_titles"):
                continue  # already has stored titles
            titles = []
            for tid in b.get("thread_ids", []):
                live = all_threads.get(tid)
                titles.append(live["title"] if live else None)
            if any(t is not None for t in titles):
                # Store what we could recover; keep None slots so index alignment is preserved
                filled = [t if t is not None else f"Thread {b['thread_ids'][i]}" for i, t in enumerate(titles)]
                import json as _json
                conn.execute(
                    "UPDATE brainstorms SET thread_titles_json = ? WHERE id = ?",
                    (_json.dumps(filled), b["id"])
                )
                updated += 1
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "updated": updated})

    @app.route("/api/signals/brainstorms/<int:brainstorm_id>", methods=["GET"])
    def signals_brainstorm_detail_api(brainstorm_id):
        """Fetch a single past brainstorm."""
        from db import get_brainstorm, get_signal_clusters
        conn = get_connection(db_path)
        b = get_brainstorm(conn, brainstorm_id)
        if not b:
            conn.close()
            return jsonify({"error": "Brainstorm not found"}), 404
        # Build threads list — use stored titles for deleted/merged threads, live data for domain/summary
        all_threads = {t["id"]: t for t in get_signal_clusters(conn, status="all", limit=2000)}
        stored_titles = b.get("thread_titles", [])
        threads_list = []
        for i, tid in enumerate(b.get("thread_ids", [])):
            live = all_threads.get(tid)
            if live:
                threads_list.append(live)
            else:
                fallback_title = stored_titles[i] if i < len(stored_titles) else f"Thread {tid}"
                threads_list.append({"id": tid, "title": fallback_title, "domain": "unknown"})
        b["threads"] = threads_list
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

    # ===================== NARRATIVES =====================

    @app.route("/api/narratives", methods=["GET"])
    def narratives_list_api():
        """List all narratives with thread/signal counts."""
        from db import get_narratives
        conn = get_connection(db_path)
        narratives = get_narratives(conn, status=request.args.get("status", "all"))
        conn.close()
        return jsonify({"narratives": narratives})

    @app.route("/api/narratives", methods=["POST"])
    def narratives_create_api():
        """Create a narrative from a hypothesis. LLM decomposes into sub-claims + queries."""
        from db import insert_narrative, insert_signal_cluster, link_thread_to_narrative
        from agents.llm import generate_json, FAST_CHAIN
        from prompts.narratives import build_narrative_decomposition_prompt

        data = request.json or {}
        thesis = data.get("thesis", "").strip()
        reasoning = data.get("reasoning", "").strip()
        if not thesis:
            return jsonify({"error": "thesis required"}), 400

        # LLM decomposes the hypothesis
        prompt = build_narrative_decomposition_prompt(thesis, reasoning)
        try:
            result = generate_json(prompt, timeout=30, chain=FAST_CHAIN)
        except Exception as e:
            return jsonify({"error": f"LLM error: {e}"}), 500

        if not result:
            return jsonify({"error": "LLM returned empty result"}), 500

        title = result.get("title", thesis[:60])
        sub_claims = result.get("sub_claims", [])
        # Flatten all queries
        all_queries = []
        for sc in sub_claims:
            all_queries.extend(sc.get("queries", []))

        conn = get_connection(db_path)
        narrative_id = insert_narrative(conn, {
            "title": title,
            "thesis": thesis,
            "reasoning": reasoning,
            "sub_claims": sub_claims,
            "search_queries": all_queries,
        })

        # Create a thread for each sub-claim
        for sc in sub_claims:
            cluster_id = insert_signal_cluster(conn, {
                "domain": "narrative",
                "title": sc["claim"],
                "synthesis": "",
            })
            link_thread_to_narrative(conn, cluster_id, narrative_id)

        conn.close()
        return jsonify({
            "ok": True,
            "narrative_id": narrative_id,
            "title": title,
            "sub_claims": sub_claims,
            "search_queries": all_queries,
        })

    @app.route("/api/narratives/<int:narrative_id>", methods=["GET"])
    def narratives_detail_api(narrative_id):
        """Get a narrative with its threads and evidence summary."""
        from db import get_narrative
        conn = get_connection(db_path)
        narrative = get_narrative(conn, narrative_id)
        conn.close()
        if not narrative:
            return jsonify({"error": "Not found"}), 404
        return jsonify(narrative)

    @app.route("/api/narratives/<int:narrative_id>", methods=["PATCH"])
    def narratives_update_api(narrative_id):
        """Update a narrative."""
        from db import update_narrative
        conn = get_connection(db_path)
        update_narrative(conn, narrative_id, request.json or {})
        conn.close()
        return jsonify({"ok": True})

    @app.route("/api/narratives/<int:narrative_id>", methods=["DELETE"])
    def narratives_delete_api(narrative_id):
        """Delete a narrative and unlink its threads."""
        from db import delete_narrative
        conn = get_connection(db_path)
        delete_narrative(conn, narrative_id)
        conn.close()
        return jsonify({"ok": True})

    # ===================== BOARD =====================

    @app.route("/api/board", methods=["GET"])
    def board_state_api():
        """Get full board state: positions, notes, threads, narratives, connections."""
        from db import get_board_state, get_signal_clusters, get_thread_links, get_narratives
        from agents.signals_synthesize import compute_thread_momentum

        conn = get_connection(db_path)
        board = get_board_state(conn)
        # Threads NOT in any narrative (active only — exclude merged/deleted)
        threads = get_signal_clusters(conn, status="active", limit=200, exclude_domain="narrative")
        orphan_threads = [t for t in threads if not t.get("narrative_id")]
        links = get_thread_links(conn)
        narratives = get_narratives(conn, status="all")

        from db import get_pattern_signal_noise_counts
        nodes = []

        # Narrative super-nodes
        for n in narratives:
            key = f"narrative:{n['id']}"
            pos = board["positions"].get(key)
            ev = {}
            # Get evidence counts across all narrative threads
            stance_rows = conn.execute(
                """SELECT sci.evidence_stance, COUNT(*) as cnt
                   FROM signal_cluster_items sci
                   JOIN signal_clusters sc ON sc.id = sci.cluster_id
                   WHERE sc.narrative_id = ? GROUP BY sci.evidence_stance""",
                (n["id"],),
            ).fetchall()
            for sr in stance_rows:
                ev[sr["evidence_stance"]] = sr["cnt"]
            nodes.append({
                "id": f"n:{n['id']}", "node_id": n["id"], "type": "narrative",
                "title": n["title"], "thesis": n.get("thesis", ""),
                "thread_count": n.get("thread_count", 0),
                "signal_count": n.get("signal_count", 0),
                "noise_count": n.get("noise_count", 0),
                "evidence": ev, "status": n.get("status", "active"),
                "x": pos["x"] if pos else None, "y": pos["y"] if pos else None,
                "pinned": bool(pos["pinned"]) if pos else False,
                # Child thread IDs for expand mode
                "child_thread_ids": [],  # populated after narrative_child_threads fetch
            })

        # Orphan thread nodes (not in a narrative, with at least 1 signal)
        for t in orphan_threads:
            sn = get_pattern_signal_noise_counts(conn, t["id"])
            if sn["signal_count"] == 0 and sn["noise_count"] == 0:
                continue  # skip empty threads
            t["momentum"] = compute_thread_momentum(conn, t["id"])
            key = f"thread:{t['id']}"
            pos = board["positions"].get(key)
            nodes.append({
                "id": t["id"], "type": "thread", "title": t["title"],
                "domain": t["domain"], "signal_count": sn["signal_count"],
                "noise_count": sn["noise_count"], "momentum": t["momentum"],
                "synthesis": t.get("synthesis", ""),
                "x": pos["x"] if pos else None, "y": pos["y"] if pos else None,
                "pinned": bool(pos["pinned"]) if pos else False,
            })

        # Narrative child threads (domain='narrative') — fetched separately since excluded above
        # Also backfill child_thread_ids on narrative nodes
        narrative_child_threads = get_signal_clusters(conn, status="active", limit=200, domain="narrative")
        for t in narrative_child_threads:
            sn = get_pattern_signal_noise_counts(conn, t["id"])
            key = f"thread:{t['id']}"
            pos = board["positions"].get(key)
            nodes.append({
                "id": t["id"], "type": "narrative_thread", "title": t["title"],
                "domain": t["domain"], "signal_count": sn["signal_count"],
                "narrative_id": t["narrative_id"],
                "x": pos["x"] if pos else None, "y": pos["y"] if pos else None,
                "pinned": bool(pos["pinned"]) if pos else False,
            })

        # Backfill child_thread_ids on narrative super-nodes
        for nd in nodes:
            if nd.get("type") == "narrative":
                nd["child_thread_ids"] = [t["id"] for t in narrative_child_threads if t.get("narrative_id") == nd["node_id"]]

        conn.close()
        return jsonify({
            "nodes": nodes,
            "edges": [{"source": l["thread_a_id"], "target": l["thread_b_id"],
                        "label": l.get("label", ""), "id": l["id"]} for l in links],
            "notes": board["notes"],
        })

    @app.route("/api/board/positions", methods=["POST"])
    def board_save_positions_api():
        """Save board node positions (batch)."""
        from db import save_board_positions_batch
        data = request.json or {}
        positions = data.get("positions", [])
        conn = get_connection(db_path)
        save_board_positions_batch(conn, positions)
        conn.close()
        return jsonify({"ok": True})

    @app.route("/api/board/notes", methods=["POST"])
    def board_create_note_api():
        """Create a sticky note."""
        from db import insert_board_note
        data = request.json or {}
        conn = get_connection(db_path)
        note_id = insert_board_note(conn, data.get("text", ""), data.get("x", 0), data.get("y", 0), data.get("color", "#eab308"))
        conn.close()
        return jsonify({"ok": True, "id": note_id})

    @app.route("/api/board/notes/<int:note_id>", methods=["PATCH"])
    def board_update_note_api(note_id):
        """Update a sticky note."""
        from db import update_board_note
        conn = get_connection(db_path)
        update_board_note(conn, note_id, **(request.json or {}))
        conn.close()
        return jsonify({"ok": True})

    @app.route("/api/board/notes/<int:note_id>", methods=["DELETE"])
    def board_delete_note_api(note_id):
        """Delete a sticky note."""
        from db import delete_board_note
        conn = get_connection(db_path)
        delete_board_note(conn, note_id)
        conn.close()
        return jsonify({"ok": True})

    @app.route("/api/board/connect", methods=["POST"])
    def board_connect_api():
        """Create a labeled connection between two threads. Optionally LLM-validates."""
        from db import add_thread_link, get_cluster_detail
        data = request.json or {}
        a, b = data.get("source"), data.get("target")
        if not a or not b:
            return jsonify({"error": "source and target required"}), 400

        conn = get_connection(db_path)

        # LLM validation — assess the connection and suggest a label
        llm_assessment = None
        try:
            from agents.llm import generate_json, CHEAP_CHAIN
            thread_a = get_cluster_detail(conn, a)
            thread_b = get_cluster_detail(conn, b)
            if thread_a and thread_b:
                sigs_a = ', '.join(s['title'] for s in (thread_a.get('signals') or [])[:5])
                sigs_b = ', '.join(s['title'] for s in (thread_b.get('signals') or [])[:5])
                prompt = f"""Two signal threads are being connected on an investigation board.

Thread A: "{thread_a['title']}"
{f'Signals: {sigs_a}' if sigs_a else ''}

Thread B: "{thread_b['title']}"
{f'Signals: {sigs_b}' if sigs_b else ''}

User's label: "{data.get('label', '') or 'none provided'}"

Return JSON:
{{
  "makes_sense": true/false,
  "suggested_label": "short relationship label (e.g. 'drives', 'contradicts', 'caused by', 'amplifies')",
  "reasoning": "one sentence explaining the connection"
}}"""
                llm_assessment = generate_json(prompt, timeout=15, chain=CHEAP_CHAIN)
        except Exception:
            pass

        label = data.get("label", "")
        if not label and llm_assessment and llm_assessment.get("suggested_label"):
            label = llm_assessment["suggested_label"]

        link_id = add_thread_link(conn, a, b, label)
        conn.close()

        result = {"ok": True, "id": link_id, "label": label}
        if llm_assessment:
            result["assessment"] = llm_assessment
        return jsonify(result)

    @app.route("/api/board/connect/<int:link_id>/label", methods=["PATCH"])
    def board_edit_label_api(link_id):
        """Edit a connection label."""
        data = request.json or {}
        conn = get_connection(db_path)
        conn.execute("UPDATE thread_links SET label = ? WHERE id = ?", (data.get("label", ""), link_id))
        conn.commit()
        conn.close()
        return jsonify({"ok": True})

    @app.route("/api/board/connect/<int:link_id>", methods=["DELETE"])
    def board_disconnect_api(link_id):
        """Remove a connection."""
        from db import delete_thread_link
        conn = get_connection(db_path)
        delete_thread_link(conn, link_id)
        conn.close()
        return jsonify({"ok": True})

    # ===================== HYPOTHESIS BANK =====================

    @app.route("/api/hypotheses", methods=["GET"])
    def hypotheses_list_api():
        """List hypotheses from the bank."""
        from db import get_hypotheses
        conn = get_connection(db_path)
        status = request.args.get("status", "all")
        hyps = get_hypotheses(conn, status=status)
        conn.close()
        return jsonify({"hypotheses": hyps})

    @app.route("/api/hypotheses", methods=["POST"])
    def hypotheses_create_api():
        """Save one or more hypotheses to the bank."""
        from db import insert_hypothesis
        data = request.json or {}
        hypotheses = data.get("hypotheses", [data] if data.get("title") else [])
        conn = get_connection(db_path)
        ids = []
        for h in hypotheses:
            hid = insert_hypothesis(conn, h)
            ids.append(hid)
        conn.close()
        return jsonify({"ok": True, "ids": ids})

    @app.route("/api/hypotheses/<int:hyp_id>/promote", methods=["POST"])
    def hypotheses_promote_api(hyp_id):
        """Promote a hypothesis to a narrative."""
        from db import update_hypothesis_status
        # The frontend will handle creating the narrative and passing back the ID
        data = request.json or {}
        narrative_id = data.get("narrative_id")
        conn = get_connection(db_path)
        update_hypothesis_status(conn, hyp_id, "promoted", narrative_id=narrative_id)
        conn.close()
        return jsonify({"ok": True})

    @app.route("/api/hypotheses/<int:hyp_id>", methods=["DELETE"])
    def hypotheses_delete_api(hyp_id):
        """Dismiss/delete a hypothesis."""
        from db import update_hypothesis_status
        conn = get_connection(db_path)
        update_hypothesis_status(conn, hyp_id, "dismissed")
        conn.close()
        return jsonify({"ok": True})

    @app.route("/api/hypotheses/related", methods=["POST"])
    def hypotheses_related_api():
        """Find hypotheses related to given thread IDs via entity + keyword overlap."""
        from db import find_related_hypotheses
        data = request.json or {}
        thread_ids = data.get("thread_ids", [])
        conn = get_connection(db_path)
        related = find_related_hypotheses(conn, thread_ids)
        conn.close()
        return jsonify({"hypotheses": related})

    @app.route("/api/hypotheses/merge", methods=["POST"])
    def hypotheses_merge_api():
        """Merge 2-3 hypotheses into one stronger hypothesis via LLM."""
        from db import get_hypotheses, insert_hypothesis, update_hypothesis_status
        from agents.llm import generate_json, CHEAP_CHAIN
        from prompts.signals import build_hypothesis_merge_prompt
        data = request.json or {}
        hyp_ids = data.get("hypothesis_ids", [])
        if len(hyp_ids) < 2 or len(hyp_ids) > 4:
            return jsonify({"error": "Need 2-4 hypothesis IDs"}), 400

        conn = get_connection(db_path)
        # Fetch the hypotheses
        all_hyps = get_hypotheses(conn, status="all", limit=200)
        hyps = [h for h in all_hyps if h["id"] in hyp_ids]
        if len(hyps) < 2:
            conn.close()
            return jsonify({"error": "Hypotheses not found"}), 404

        # LLM merge
        prompt = build_hypothesis_merge_prompt(hyps)
        try:
            result = generate_json(prompt, timeout=20, chain=CHEAP_CHAIN)
        except Exception as e:
            conn.close()
            return jsonify({"error": f"LLM merge failed: {e}"}), 500

        if not result or not result.get("title"):
            conn.close()
            return jsonify({"error": "LLM returned empty result"}), 500

        # Combine source data from all originals
        all_thread_ids = []
        all_entities = []
        seen_entities = set()
        for h in hyps:
            all_thread_ids.extend(h.get("source_thread_ids") or [])
            for e in (h.get("source_entities") or []):
                key = str(e.get("name") or e.get("entity_value") or e)
                if key not in seen_entities:
                    seen_entities.add(key)
                    all_entities.append(e)

        # Create merged hypothesis
        merged_id = insert_hypothesis(conn, {
            "title": result["title"],
            "reasoning": result.get("reasoning", ""),
            "confidence": result.get("confidence", "medium"),
            "source_thread_ids": list(set(all_thread_ids)),
            "source_entities": all_entities,
        })

        # Mark originals as merged
        for h in hyps:
            update_hypothesis_status(conn, h["id"], "merged")

        conn.commit()
        conn.close()
        return jsonify({
            "ok": True,
            "merged_hypothesis": {
                "id": merged_id,
                "title": result["title"],
                "reasoning": result.get("reasoning", ""),
                "confidence": result.get("confidence", "medium"),
            },
            "merged_ids": hyp_ids,
        })

    @app.route("/api/hypotheses/concepts", methods=["GET"])
    def hypotheses_concepts_api():
        """Get concept overlap graph for all captured hypotheses."""
        from db import get_hypothesis_concept_graph
        conn = get_connection(db_path)
        graph = get_hypothesis_concept_graph(conn)
        conn.close()
        return jsonify(graph)

    # ── Causal Links API ─────────────────────────────────────────────────

    @app.route("/api/causal-links", methods=["GET"])
    def causal_links_list_api():
        from db import get_causal_links
        conn = get_connection(db_path)
        thread_id = request.args.get("thread_id", type=int)
        status = request.args.get("status")
        links = get_causal_links(conn, thread_id=thread_id, status=status)
        conn.close()
        return jsonify({"links": links})

    @app.route("/api/causal-links", methods=["POST"])
    def causal_link_create_api():
        from db import add_causal_link
        data = request.json or {}
        cause = data.get("cause_thread_id")
        effect = data.get("effect_thread_id")
        if not cause or not effect:
            return jsonify({"error": "cause_thread_id and effect_thread_id required"}), 400
        if cause == effect:
            return jsonify({"error": "Thread cannot cause itself"}), 400
        conn = get_connection(db_path)
        link_id = add_causal_link(conn, cause, effect,
                                  label=data.get("label"),
                                  hypothesis_id=data.get("hypothesis_id"),
                                  confidence=data.get("confidence", "medium"),
                                  reasoning=data.get("reasoning"),
                                  brainstorm_id=data.get("brainstorm_id"))
        conn.close()
        if link_id:
            return jsonify({"ok": True, "id": link_id})
        return jsonify({"ok": False, "error": "Link already exists"})

    @app.route("/api/causal-links/<int:link_id>", methods=["PATCH"])
    def causal_link_update_api(link_id):
        from db import update_causal_link
        conn = get_connection(db_path)
        update_causal_link(conn, link_id, **(request.json or {}))
        conn.close()
        return jsonify({"ok": True})

    @app.route("/api/causal-links/<int:link_id>", methods=["DELETE"])
    def causal_link_delete_api(link_id):
        from db import delete_causal_link
        conn = get_connection(db_path)
        delete_causal_link(conn, link_id)
        conn.close()
        return jsonify({"ok": True})

    @app.route("/api/causal-graph", methods=["GET"])
    def causal_graph_api():
        from db import get_causal_graph
        conn = get_connection(db_path)
        graph = get_causal_graph(conn)
        conn.close()
        return jsonify(graph)

    @app.route("/api/causal-links/from-brainstorm", methods=["POST"])
    def causal_links_from_brainstorm_api():
        from db import add_causal_link
        data = request.json or {}
        brainstorm_id = data.get("brainstorm_id")
        links = data.get("links", [])
        conn = get_connection(db_path)
        created = []
        for link in links:
            lid = add_causal_link(conn, link["cause_thread_id"], link["effect_thread_id"],
                                  label=link.get("label"), brainstorm_id=brainstorm_id,
                                  reasoning=link.get("reasoning"))
            if lid:
                created.append(lid)
        conn.close()
        return jsonify({"ok": True, "created_count": len(created), "ids": created})

    # ── Causal Paths API ────────────────────────────────────────────────

    @app.route("/api/causal-paths", methods=["GET"])
    def causal_paths_list_api():
        from db import get_causal_paths
        conn = get_connection(db_path)
        paths = get_causal_paths(conn)
        conn.close()
        return jsonify({"paths": paths})

    @app.route("/api/causal-paths", methods=["POST"])
    def causal_path_create_api():
        from db import create_causal_path
        data = request.json or {}
        name = data.get("name", "").strip()
        thread_ids = data.get("thread_ids", [])
        if not name:
            return jsonify({"error": "name required"}), 400
        conn = get_connection(db_path)
        path_id = create_causal_path(conn, name, thread_ids)
        conn.close()
        return jsonify({"ok": True, "id": path_id})

    @app.route("/api/causal-paths/<int:path_id>", methods=["PATCH"])
    def causal_path_update_api(path_id):
        from db import update_causal_path
        data = request.json or {}
        conn = get_connection(db_path)
        update_causal_path(conn, path_id, name=data.get("name"), thread_ids=data.get("thread_ids"))
        conn.close()
        return jsonify({"ok": True})

    @app.route("/api/causal-paths/<int:path_id>", methods=["DELETE"])
    def causal_path_delete_api(path_id):
        from db import delete_causal_path
        conn = get_connection(db_path)
        delete_causal_path(conn, path_id)
        conn.close()
        return jsonify({"ok": True})

    @app.route("/api/causal-paths/<int:path_id>/temporal-audit", methods=["GET"])
    def causal_path_temporal_audit_api(path_id):
        from db import get_temporal_audit
        conn = get_connection(db_path)
        audit = get_temporal_audit(conn, path_id)
        conn.close()
        if audit is None:
            return jsonify({"error": "Path not found"}), 404
        return jsonify(audit)

    # ── Causal Discovery ──────────────────────────────────────────────

    @app.route("/api/causal-suggestions", methods=["GET"])
    def causal_suggestions_api():
        """Discover potential causal links via heuristics (temporal, entity, brainstorm)."""
        from db import get_causal_suggestions
        limit = request.args.get("limit", 20, type=int)
        conn = get_connection(db_path)
        suggestions = get_causal_suggestions(conn, limit=limit)
        conn.close()
        return jsonify({"suggestions": suggestions})

    @app.route("/api/causal-links/<int:link_id>/validate", methods=["POST"])
    def causal_link_validate_api(link_id):
        """Devil's advocate validation: challenge the causal claim, surface alternatives."""
        from db import get_cluster_detail, get_causal_links, update_causal_link
        from agents.llm import generate_json, FAST_CHAIN
        from prompts.signals import build_causal_validation_prompt
        conn = get_connection(db_path)
        link = conn.execute("SELECT * FROM causal_links WHERE id = ?", (link_id,)).fetchone()
        if not link:
            conn.close()
            return jsonify({"error": "Link not found"}), 404
        cause = get_cluster_detail(conn, link["cause_thread_id"])
        effect = get_cluster_detail(conn, link["effect_thread_id"])
        if not cause or not effect:
            conn.close()
            return jsonify({"error": "Thread not found"}), 404
        prompt = build_causal_validation_prompt(cause, effect)
        try:
            result = generate_json(prompt, timeout=20, chain=FAST_CHAIN)
        except Exception as e:
            conn.close()
            return jsonify({"error": str(e)}), 500
        # Persist alternatives on the link
        import json as _json
        if result and result.get("alternatives"):
            update_causal_link(conn, link_id,
                               alternatives_json=_json.dumps(result["alternatives"]))
        conn.close()
        return jsonify({"ok": True, "assessment": result or {}})

    @app.route("/api/causal-links/validate", methods=["POST"])
    def causal_link_validate_legacy_api():
        """Legacy validation endpoint (by thread IDs, not link ID)."""
        from db import get_cluster_detail
        from agents.llm import generate_json, FAST_CHAIN
        from prompts.signals import build_causal_validation_prompt
        data = request.json or {}
        cause_id = data.get("cause_thread_id")
        effect_id = data.get("effect_thread_id")
        if not cause_id or not effect_id:
            return jsonify({"error": "cause_thread_id and effect_thread_id required"}), 400
        conn = get_connection(db_path)
        cause = get_cluster_detail(conn, cause_id)
        effect = get_cluster_detail(conn, effect_id)
        conn.close()
        if not cause or not effect:
            return jsonify({"error": "Thread not found"}), 404
        prompt = build_causal_validation_prompt(cause, effect)
        try:
            result = generate_json(prompt, timeout=20, chain=FAST_CHAIN)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        return jsonify({"ok": True, "assessment": result or {}})

    @app.route("/api/causal-paths/<int:path_id>/promote", methods=["POST"])
    def causal_path_promote_api(path_id):
        """Promote a causal chain to a narrative."""
        from db import promote_chain_to_narrative
        conn = get_connection(db_path)
        narrative_id = promote_chain_to_narrative(conn, path_id)
        conn.close()
        if narrative_id:
            return jsonify({"ok": True, "narrative_id": narrative_id})
        return jsonify({"error": "Chain not found or too short (need >= 2 threads)"}), 400

    @app.route("/api/narratives/<int:narrative_id>/link-thread", methods=["POST"])
    def narratives_link_thread_api(narrative_id):
        """Link an existing thread to a narrative."""
        from db import link_thread_to_narrative
        data = request.json or {}
        thread_id = data.get("thread_id")
        if not thread_id:
            return jsonify({"error": "thread_id required"}), 400
        conn = get_connection(db_path)
        link_thread_to_narrative(conn, thread_id, narrative_id)
        conn.close()
        return jsonify({"ok": True})

    @app.route("/api/narratives/<int:narrative_id>/add-subclaim", methods=["POST"])
    def narratives_add_subclaim_api(narrative_id):
        """Add a hypothesis as a sub-claim to an existing narrative."""
        from db import get_narrative, update_narrative, insert_signal_cluster, link_thread_to_narrative, update_hypothesis_status
        data = request.json or {}
        claim = data.get("claim", "").strip()
        hypothesis_id = data.get("hypothesis_id")
        if not claim:
            return jsonify({"error": "claim required"}), 400

        conn = get_connection(db_path)
        narrative = get_narrative(conn, narrative_id)
        if not narrative:
            conn.close()
            return jsonify({"error": "Narrative not found"}), 404

        # Append to sub_claims
        sub_claims = narrative.get("sub_claims", [])
        sub_claims.append({"claim": claim, "queries": []})

        # Create a thread for this sub-claim
        thread_id = insert_signal_cluster(conn, {
            "domain": "narrative",
            "title": claim[:100],
            "synthesis": "",
        })
        link_thread_to_narrative(conn, thread_id, narrative_id)

        # Update narrative's sub_claims_json
        update_narrative(conn, narrative_id, {"sub_claims": sub_claims})

        # Mark hypothesis as promoted if provided
        if hypothesis_id:
            update_hypothesis_status(conn, hypothesis_id, "promoted", narrative_id=narrative_id)

        conn.commit()
        conn.close()
        return jsonify({"ok": True, "thread_id": thread_id})

    @app.route("/api/narratives/<int:narrative_id>/search", methods=["POST"])
    @app.route("/api/narratives/<int:narrative_id>/scan-internal", methods=["POST"])
    def narratives_scan_internal_api(narrative_id):
        """Phase 1: Search existing signals for each sub-claim. No external API calls."""
        from db import get_narrative, link_signal_to_cluster

        conn = get_connection(db_path)
        narrative = get_narrative(conn, narrative_id)
        if not narrative:
            conn.close()
            return jsonify({"error": "Not found"}), 404

        sub_claims = narrative.get("sub_claims", [])
        threads = narrative.get("threads", [])
        thesis = narrative.get("thesis", "")

        results = []
        total_linked = 0

        for i, sc in enumerate(sub_claims):
            claim = sc.get("claim", "")
            # Build search terms: claim text + queries
            search_terms = [claim] + sc.get("queries", [])
            search_text = " ".join(search_terms).lower()
            # Extract key words (4+ chars, skip stopwords)
            stopwords = {'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 'can', 'had', 'her', 'was', 'one', 'our', 'out', 'has', 'have', 'been', 'will', 'with', 'that', 'this', 'from', 'they', 'were', 'said', 'each', 'which', 'their', 'what', 'about', 'would', 'there', 'could', 'other', 'into', 'more', 'some', 'than', 'them', 'very', 'when', 'come', 'made', 'after', 'back', 'only', 'also',
                         'does', 'over', 'such', 'like', 'just', 'most', 'much', 'between', 'during', 'before',
                         'lead', 'leads', 'including', 'particularly', 'increased', 'higher', 'overall',
                         'experiences', 'major', 'periods', 'amplifies'}
            keywords = list(dict.fromkeys(w for w in search_text.split() if len(w) >= 4 and w not in stopwords))[:10]

            if not keywords:
                results.append({"claim": claim, "matches": [], "linked": 0})
                continue

            # Fetch candidate signals matching ANY keyword, then score by overlap count
            like_clauses = " OR ".join(["(s.title LIKE ? COLLATE NOCASE OR s.body LIKE ? COLLATE NOCASE)"] * min(len(keywords), 5))
            params = []
            for kw in keywords[:5]:
                params.extend([f"%{kw}%", f"%{kw}%"])

            candidates = conn.execute(
                f"""SELECT s.id, s.title, s.body, s.source_name, s.published_at
                    FROM signals s
                    WHERE s.signal_status != 'noise' AND ({like_clauses})
                    ORDER BY s.published_at DESC LIMIT 100""",
                params,
            ).fetchall()

            # Score each candidate by how many keywords it matches (title weighted 2x)
            min_hits = max(2, len(keywords) // 3)  # require at least 2 keyword hits
            scored = []
            seen_ids = set()
            for c in candidates:
                if c["id"] in seen_ids:
                    continue
                seen_ids.add(c["id"])
                title_lower = (c["title"] or "").lower()
                body_lower = (c["body"] or "").lower()
                hits = sum(1 for kw in keywords if kw in title_lower) * 2 + \
                       sum(1 for kw in keywords if kw in body_lower)
                if hits >= min_hits:
                    scored.append((hits, c))

            scored.sort(key=lambda x: x[0], reverse=True)
            top_matches = [c for _, c in scored[:20]]

            # Classify evidence stance for top matches in a single LLM batch
            stances = {}
            if top_matches and thesis:
                try:
                    from agents.llm import generate_json
                    from agents.llm import CHEAP_CHAIN
                    signals_block = "\n".join(
                        f"[{m['id']}] {(m['title'] or '')[:100]}"
                        for m in top_matches[:15]
                    )
                    cls_prompt = f"""Given this hypothesis:
"{thesis}"

And this specific sub-claim:
"{claim}"

Classify each signal as supporting, contradicting, or neutral:
{signals_block}

Return JSON: {{"classifications": [{{"id": signal_id, "stance": "supporting"|"contradicting"|"neutral"}}]}}
Be honest — if a signal contradicts the claim, say so. Neutral means related but unclear."""
                    cls_result = generate_json(cls_prompt, timeout=20, chain=CHEAP_CHAIN)
                    if cls_result and cls_result.get("classifications"):
                        for c in cls_result["classifications"]:
                            stances[c.get("id")] = c.get("stance", "neutral")
                except Exception as e:
                    print(f"[narrative_scan] Evidence classification failed: {e}")

            # Look up thread assignment for top matches
            thread_id = threads[i]["id"] if i < len(threads) else None
            linked = 0
            match_list = []
            for m in top_matches:
                sig_thread = conn.execute(
                    "SELECT cluster_id FROM signal_cluster_items WHERE signal_id = ? LIMIT 1",
                    (m["id"],)
                ).fetchone()
                sig_thread_id = sig_thread["cluster_id"] if sig_thread else None
                stance = stances.get(m["id"], "neutral")

                match_list.append({
                    "id": m["id"], "title": m["title"],
                    "source_name": m["source_name"] or "",
                    "published_at": (m["published_at"] or "")[:10],
                    "already_in_thread": sig_thread_id == thread_id if thread_id else False,
                    "stance": stance,
                })
                # Auto-link only high-relevance matches (top 5)
                if thread_id and sig_thread_id != thread_id and linked < 5:
                    try:
                        link_signal_to_cluster(conn, thread_id, m["id"])
                        conn.execute(
                            "UPDATE signal_cluster_items SET evidence_stance = ? WHERE cluster_id = ? AND signal_id = ?",
                            (stance, thread_id, m["id"]),
                        )
                        linked += 1
                    except Exception:
                        pass  # already linked

            total_linked += linked
            results.append({"claim": claim, "matches": match_list, "linked": linked, "total": len(match_list)})

        if total_linked > 0:
            conn.commit()

        conn.close()
        return jsonify({
            "ok": True,
            "narrative_id": narrative_id,
            "sub_claims": results,
            "total_linked": total_linked,
        })

    @app.route("/api/narratives/<int:narrative_id>/search", methods=["POST"])
    def narratives_search_api(narrative_id):
        """Phase 2: Run targeted external searches for a narrative's queries. SSE-streamed."""
        from db import get_narrative

        conn = get_connection(db_path)
        narrative = get_narrative(conn, narrative_id)
        conn.close()
        if not narrative:
            return jsonify({"error": "Not found"}), 404

        data = request.json or {}
        queries = data.get("queries") or narrative.get("search_queries", [])
        if not queries:
            return jsonify({"error": "No search queries"}), 400

        def generate():
            from db import link_signal_to_cluster, insert_signal
            from scraper.google_news import search_google_news
            from scraper.hackernews import search_stories
            from agents.signals_collect import _normalize_signal
            from agents.llm import generate_json, CHEAP_CHAIN
            from prompts.narratives import build_evidence_classification_prompt
            from datetime import datetime, timedelta

            conn = get_connection(db_path)
            narr = get_narrative(conn, narrative_id)
            threads = narr.get("threads", [])
            sub_claims = narr.get("sub_claims", [])
            cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

            # Build query → thread mapping: each sub-claim's queries route to its thread
            query_to_thread = {}
            for i, sc in enumerate(sub_claims):
                thread_id = threads[i]["id"] if i < len(threads) else (threads[0]["id"] if threads else None)
                for q in sc.get("queries", []):
                    query_to_thread[q] = thread_id

            capped = queries[:15]
            total_found = 0
            total_new = 0
            total_classified = 0

            yield f"data: {json.dumps({'type': 'start', 'total_queries': len(capped)})}\n\n"

            for qi, query in enumerate(capped):
                target_thread = query_to_thread.get(query, threads[0]["id"] if threads else None)
                yield f"data: {json.dumps({'type': 'query_start', 'index': qi + 1, 'total': len(capped), 'query': query})}\n\n"

                news = search_google_news(query, max_results=8, days_back=30)
                hn = search_stories(query, max_results=5, sort="date")
                q_found = 0

                for item in news + hn:
                    source = "google_news" if item in news else "hackernews"
                    sig = _normalize_signal(item, source, "narrative")
                    if not sig:
                        continue
                    pub = sig.get("published_at", "")
                    if pub and pub[:10] < cutoff:
                        continue

                    total_found += 1
                    q_found += 1
                    sig_id = insert_signal(conn, sig)
                    if not sig_id:
                        existing = conn.execute(
                            "SELECT id FROM signals WHERE content_hash = ?", (sig.get("content_hash"),)
                        ).fetchone()
                        sig_id = existing["id"] if existing else None
                        if not sig_id:
                            continue

                    total_new += 1

                    # Classify evidence stance
                    stance = "neutral"
                    try:
                        cls_prompt = build_evidence_classification_prompt(
                            narr["thesis"], sig.get("title", ""), sig.get("body", "")
                        )
                        cls_result = generate_json(cls_prompt, timeout=15, chain=CHEAP_CHAIN)
                        if cls_result:
                            stance = cls_result.get("stance", "neutral")
                            total_classified += 1
                    except Exception:
                        pass

                    if target_thread:
                        link_signal_to_cluster(conn, target_thread, sig_id)
                        conn.execute(
                            "UPDATE signal_cluster_items SET evidence_stance = ? WHERE cluster_id = ? AND signal_id = ?",
                            (stance, target_thread, sig_id),
                        )
                        conn.execute(
                            "UPDATE signal_clusters SET last_signal_at = CURRENT_TIMESTAMP WHERE id = ?",
                            (target_thread,),
                        )

                    yield f"data: {json.dumps({'type': 'signal', 'title': sig.get('title', '')[:80], 'stance': stance, 'source': source})}\n\n"

                yield f"data: {json.dumps({'type': 'query_done', 'index': qi + 1, 'query': query, 'found': q_found})}\n\n"

            conn.execute(
                "UPDATE narratives SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (narrative_id,),
            )
            conn.commit()
            conn.close()

            yield f"data: {json.dumps({'type': 'complete', 'total_found': total_found, 'total_new': total_new, 'total_classified': total_classified})}\n\n"

        return Response(generate(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, port=5001, threaded=True)
