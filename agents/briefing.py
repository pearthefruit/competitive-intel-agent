"""Agent: Intelligence Briefing Generator — consulting-ready dossier with Digital Maturity Score."""

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from agents.llm import generate_json
from db import get_connection, get_dossier_by_company, get_latest_key_facts
from prompts.briefing import build_briefing_prompt


def _get_hiring_stats(conn, company_name):
    """Query aggregate hiring stats from classifications table.

    Returns dict with dept_counts, seniority_counts, strategic_tag_counts,
    ai_ml_role_count, total_roles, growth_signal_ratio — or None if no data.
    """
    # Find company in companies table
    row = conn.execute(
        "SELECT id FROM companies WHERE name = ? COLLATE NOCASE", (company_name,)
    ).fetchone()
    if not row:
        return None

    company_id = row["id"]

    # Get all classified jobs
    rows = conn.execute(
        """SELECT c.department_category, c.department_subcategory, c.seniority_level,
                  c.strategic_tags, c.growth_signal
           FROM classifications c
           JOIN jobs j ON c.job_id = j.id
           WHERE j.company_id = ?""",
        (company_id,),
    ).fetchall()

    if not rows:
        return None

    dept_counts = Counter()
    seniority_counts = Counter()
    strategic_tag_counts = Counter()
    growth_counts = Counter()
    ai_ml_count = 0

    for r in rows:
        dept = r["department_category"] or "Other"
        dept_counts[dept] += 1

        seniority_counts[r["seniority_level"] or "Unknown"] += 1

        growth_counts[r["growth_signal"] or "unclear"] += 1

        # Parse strategic tags
        tags_raw = r["strategic_tags"]
        if tags_raw:
            try:
                tags = json.loads(tags_raw)
                for tag in tags:
                    strategic_tag_counts[tag] += 1
                    if "AI" in tag or "ML" in tag:
                        ai_ml_count += 1
            except (json.JSONDecodeError, TypeError):
                pass

        # Count AI/ML department roles
        subcat = r["department_subcategory"] or ""
        if "AI" in subcat or "ML" in subcat or "Machine Learning" in subcat:
            ai_ml_count += 1

    total = len(rows)
    new_roles = growth_counts.get("likely new role", 0)
    growth_ratio = f"{round(new_roles * 100 / total)}% new roles" if total else "unknown"

    return {
        "total_roles": total,
        "dept_counts": dict(dept_counts),
        "seniority_counts": dict(seniority_counts),
        "strategic_tag_counts": dict(strategic_tag_counts),
        "ai_ml_role_count": ai_ml_count,
        "growth_signal_ratio": growth_ratio,
    }


def _get_report_summaries(analyses):
    """Read and truncate report files for each analysis type.

    Returns dict of {analysis_type: truncated_text}. Caps total at ~15K chars.
    """
    summaries = {}
    total_chars = 0
    max_per_report = 1500
    max_total = 15000

    # Group by type, take latest per type
    seen_types = set()
    for a in sorted(analyses, key=lambda x: x.get("created_at", ""), reverse=True):
        atype = a["analysis_type"]
        if atype in seen_types:
            continue
        seen_types.add(atype)

        report_file = a.get("report_file")
        if not report_file:
            continue

        try:
            text = Path(report_file).read_text(encoding="utf-8")
            truncated = text[:max_per_report]
            if len(text) > max_per_report:
                truncated += "\n\n... (truncated)"
            summaries[atype] = truncated
            total_chars += len(truncated)
            if total_chars >= max_total:
                break
        except Exception:
            pass

    return summaries


def generate_briefing(company_name, db_path="intel.db"):
    """Generate a consulting-ready intelligence briefing for a company.

    Synthesizes all available dossier data (key facts, report summaries, hiring stats)
    into a structured JSON briefing with Digital Maturity Score and engagement opportunities.

    Returns the briefing dict (also saved to dossiers.briefing_json), or None on failure.
    """
    print(f"\n{'='*60}")
    print(f"  Generating Intelligence Briefing: {company_name}")
    print(f"{'='*60}\n")

    conn = get_connection(db_path)

    # Load dossier
    dossier = get_dossier_by_company(conn, company_name)
    if not dossier:
        print(f"[briefing] No dossier found for {company_name}")
        conn.close()
        return None

    analyses = dossier.get("analyses", [])
    if len(analyses) < 2:
        print(f"[briefing] Only {len(analyses)} analysis(es) — need at least 2 for a meaningful briefing")
        conn.close()
        return None

    # 1. Gather all key facts by analysis type
    raw_facts = get_latest_key_facts(conn, dossier["id"])
    # get_latest_key_facts returns {type: {"data": {...}, "as_of": ...}} — unwrap to {type: {...}}
    all_key_facts = {atype: info["data"] for atype, info in raw_facts.items() if info.get("data")}
    print(f"[briefing] Key facts available from: {list(all_key_facts.keys())}")

    # 2. Get hiring stats
    hiring_stats = _get_hiring_stats(conn, company_name)
    if hiring_stats:
        print(f"[briefing] Hiring data: {hiring_stats['total_roles']} roles, "
              f"{hiring_stats['ai_ml_role_count']} AI/ML")
    else:
        print("[briefing] No hiring data available")

    # 3. Get report summaries
    report_summaries = _get_report_summaries(analyses)
    print(f"[briefing] Report summaries from: {list(report_summaries.keys())}")

    # 4. Build prompt and generate
    print("[briefing] Generating briefing via LLM (this may take 30-60 seconds)...")
    prompt = build_briefing_prompt(company_name, all_key_facts, report_summaries, hiring_stats)
    briefing = generate_json(prompt, timeout=90)

    if not isinstance(briefing, dict):
        print("[briefing] LLM did not return valid JSON — briefing generation failed")
        conn.close()
        return None

    # 5. Store on dossier
    now = datetime.now(timezone.utc).isoformat()
    model_used = "unknown"  # generate_json doesn't return model — could enhance later
    conn.execute(
        """UPDATE dossiers
           SET briefing_json = ?, briefing_generated_at = ?, briefing_model = ?, updated_at = ?
           WHERE id = ?""",
        (json.dumps(briefing), now, model_used, now, dossier["id"]),
    )
    conn.commit()
    conn.close()

    # Summary
    dm = briefing.get("digital_maturity", {})
    opps = briefing.get("engagement_opportunities", [])
    print(f"\n[briefing] Digital Maturity Score: {dm.get('overall_score', '?')}/100 "
          f"({dm.get('overall_label', '?')})")
    print(f"[briefing] Engagement opportunities: {len(opps)}")
    for opp in opps[:3]:
        print(f"[briefing]   [{opp.get('priority', '?').upper()}] {opp.get('service', '?')} "
              f"— {opp.get('estimated_scope', '?')}")

    print(f"\n{'='*60}")
    print(f"  Briefing complete for {company_name}")
    print(f"{'='*60}")

    return briefing
