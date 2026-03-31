"""Agent: Intelligence Briefing Generator — consulting-ready dossier with lens-parameterized scoring."""

import json
from datetime import datetime, timezone
from pathlib import Path

from agents.llm import generate_json, BRIEFING_CHAIN
from agents.scoring import compute_dms_scores, compute_anomaly_signals
from db import (get_connection, get_dossier_by_company, get_latest_key_facts,
                get_company_id, compute_hiring_stats, get_hiring_snapshots,
                get_recent_changes, get_lens, get_lens_by_slug, DT_LENS_SLUG)
from prompts.briefing import build_briefing_prompt

# All possible analysis types for tracking what's missing
ALL_ANALYSIS_TYPES = [
    "hiring", "financial", "competitors", "sentiment", "patents",
    "techstack", "seo", "pricing", "profile", "compare", "landscape",
]


def _get_report_summaries(analyses):
    """Read and truncate report files for each analysis type.

    Returns dict of {analysis_type: truncated_text}. Caps total at ~20K chars.
    """
    summaries = {}
    total_chars = 0
    max_per_report = 2000
    max_total = 20000

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


def _build_data_confidence(hiring_stats, analyses, company_name, conn):
    """Build data confidence metadata for the briefing."""
    analyses_available = list({a["analysis_type"] for a in analyses})
    analyses_missing = [t for t in ALL_ANALYSIS_TYPES if t not in analyses_available]

    jobs_analyzed = hiring_stats.get("total_roles", 0) if hiring_stats else 0

    # Determine scrape coverage from company ATS type
    scrape_coverage = "unknown"
    company_id = get_company_id(conn, company_name)
    if company_id:
        row = conn.execute("SELECT ats_type FROM companies WHERE id = ?", (company_id,)).fetchone()
        if row and row["ats_type"]:
            ats = row["ats_type"]
            if ats in ("greenhouse", "lever", "ashby", "workday"):
                scrape_coverage = f"{ats.title()} API (full board — all open roles captured)"
            elif ats == "linkedin":
                scrape_coverage = f"LinkedIn guest API (found {jobs_analyzed} — scans up to 100)"
            else:
                scrape_coverage = f"{ats} (coverage unknown)"

    # Confidence level
    if jobs_analyzed >= 100 and len(analyses_available) >= 4:
        confidence = "high"
    elif jobs_analyzed >= 30 and len(analyses_available) >= 2:
        confidence = "medium"
    else:
        confidence = "low"

    # Caveats
    caveats = []
    if jobs_analyzed < 30:
        caveats.append(f"Only {jobs_analyzed} roles analyzed — hiring signals may not be representative")
    if "hiring" not in analyses_available:
        caveats.append("No hiring analysis — scoring and hiring trajectory based on public signals only.")
    if "techstack" not in analyses_available:
        caveats.append("No tech stack analysis — tech-related scores rely on hiring data only")
    if "financial" not in analyses_available:
        caveats.append("No financial analysis — budget signals based on hiring volume and public info only")
    if "patents" not in analyses_available:
        caveats.append("No patent analysis — innovation scores exclude IP signals")
    if "sentiment" not in analyses_available:
        caveats.append("No sentiment analysis — org/culture scores exclude employee sentiment")
    if "linkedin" in scrape_coverage.lower():
        caveats.append("LinkedIn sample may not capture all open roles — consider running ATS scrape if available")

    # Check if classification used heuristic-only (fast mode)
    classification_mode = "comprehensive"
    if company_id:
        heuristic_row = conn.execute(
            """SELECT COUNT(*) as cnt FROM classifications c
               JOIN jobs j ON c.job_id = j.id
               WHERE j.company_id = ? AND c.model_used = 'heuristic'""",
            (company_id,),
        ).fetchone()
        total_cls_row = conn.execute(
            """SELECT COUNT(*) as cnt FROM classifications c
               JOIN jobs j ON c.job_id = j.id
               WHERE j.company_id = ?""",
            (company_id,),
        ).fetchone()
        if heuristic_row and total_cls_row and total_cls_row["cnt"] > 0:
            if heuristic_row["cnt"] == total_cls_row["cnt"]:
                classification_mode = "fast"
                caveats.append("Fast (heuristic) classification — department subcategories, skills, and strategic tags not available.")

    return {
        "jobs_analyzed": jobs_analyzed,
        "scrape_coverage": scrape_coverage,
        "classification_mode": classification_mode,
        "analyses_available": sorted(analyses_available),
        "analyses_missing": sorted(analyses_missing),
        "overall_confidence": confidence,
        "caveats": caveats,
    }


def generate_briefing(company_name, db_path="intel.db", lens_id=None):
    """Generate a consulting-ready intelligence briefing for a company.

    Synthesizes all available dossier data (key facts, report summaries, hiring stats,
    temporal snapshots) into a structured JSON briefing. The scoring section is driven
    by the specified lens (defaults to Digital Transformation if none specified).

    Args:
        company_name: Target company name
        db_path: Path to SQLite database
        lens_id: Optional lens ID to use for scoring. Defaults to DT lens.

    Returns the briefing dict (also saved to dossiers.briefing_json), or None on failure.
    """
    print(f"\n{'='*60}")
    print(f"  Generating Intelligence Briefing: {company_name}")
    print(f"{'='*60}\n")

    conn = get_connection(db_path)

    # Load lens config
    if lens_id:
        lens = get_lens(conn, lens_id)
        if not lens:
            msg = f"Lens id={lens_id} not found"
            print(f"[briefing] {msg}")
            conn.close()
            raise ValueError(msg)
    else:
        lens = get_lens_by_slug(conn, DT_LENS_SLUG)
        if not lens:
            msg = f"Default lens '{DT_LENS_SLUG}' not found — run init_db"
            print(f"[briefing] {msg}")
            conn.close()
            raise ValueError(msg)

    lens_config = lens["config"]
    lens_dimensions = lens_config.get("dimensions", [])
    lens_labels = lens_config.get("labels", [])
    use_algo = lens["slug"] == DT_LENS_SLUG
    score_label = lens_config.get("score_label", "Score")

    print(f"[briefing] Lens: {lens['name']} (slug={lens['slug']}, {len(lens_dimensions)} dims, algo={'yes' if use_algo else 'no'})")

    # Load dossier
    dossier = get_dossier_by_company(conn, company_name)
    if not dossier:
        msg = f"No dossier found for {company_name}"
        print(f"[briefing] {msg}")
        conn.close()
        raise ValueError(msg)

    analyses = dossier.get("analyses", [])

    if len(analyses) < 2:
        msg = f"Only {len(analyses)} analysis(es) for {company_name} — need at least 2 for a meaningful briefing"
        print(f"[briefing] {msg}")
        conn.close()
        raise ValueError(msg)

    # 1. Gather all key facts by analysis type
    raw_facts = get_latest_key_facts(conn, dossier["id"])
    all_key_facts = {atype: info["data"] for atype, info in raw_facts.items() if info.get("data")}
    print(f"[briefing] Key facts available from: {list(all_key_facts.keys())}")

    # 2. Get hiring stats using shared function
    company_id = get_company_id(conn, company_name)
    hiring_stats = compute_hiring_stats(conn, company_id) if company_id else None
    if hiring_stats and hiring_stats["total_roles"] < 10:
        print(f"[briefing] Only {hiring_stats['total_roles']} roles — insufficient for scoring, treating as no hiring data")
        hiring_stats = None
    if hiring_stats:
        print(f"[briefing] Hiring data: {hiring_stats['total_roles']} roles, "
              f"{hiring_stats['ai_ml_role_count']} AI/ML")
    else:
        print("[briefing] No hiring data available")

    # 3. Get hiring snapshots for temporal analysis
    hiring_snapshots = None
    if company_id:
        hiring_snapshots = get_hiring_snapshots(conn, company_id, limit=10)
        if hiring_snapshots and len(hiring_snapshots) > 1:
            print(f"[briefing] Hiring snapshots: {len(hiring_snapshots)} data points "
                  f"({hiring_snapshots[-1]['snapshot_date']} → {hiring_snapshots[0]['snapshot_date']})")
        elif hiring_snapshots:
            print(f"[briefing] Single hiring snapshot available ({hiring_snapshots[0]['snapshot_date']})")
        else:
            print("[briefing] No hiring snapshots available")

    # 4. Get report summaries
    report_summaries = _get_report_summaries(analyses)
    print(f"[briefing] Report summaries from: {list(report_summaries.keys())}")

    # 5. Build data confidence
    data_confidence = _build_data_confidence(hiring_stats, analyses, company_name, conn)
    print(f"[briefing] Data confidence: {data_confidence['overall_confidence']} "
          f"({len(data_confidence['analyses_available'])} analyses, "
          f"{data_confidence['jobs_analyzed']} jobs)")

    # 5.5. Compute algorithmic DMS base scores (only for DT lens)
    algo_scores = None
    if use_algo:
        algo_scores = compute_dms_scores(hiring_stats, all_key_facts)
        print(f"[briefing] Algorithmic DMS: {algo_scores['weighted_algorithmic_score']}/100 "
              f"(confidence: {algo_scores['overall_confidence']:.0%})")
        for dim_key in ("tech_modernity", "data_analytics", "ai_readiness", "org_readiness"):
            d = algo_scores[dim_key]
            print(f"[briefing]   {dim_key}: {d['algorithmic_score']}/100 "
                  f"(confidence: {d['confidence']:.0%}, {len(d['signals_used'])} signals)")
    else:
        print(f"[briefing] Skipping algorithmic scoring (DT-lens-specific)")

    # 5.6. Detect structural anomalies (lens-agnostic — always run)
    anomaly_signals = compute_anomaly_signals(hiring_stats, all_key_facts)
    if anomaly_signals:
        print(f"[briefing] Structural anomalies detected: {len(anomaly_signals)}")
        for a in anomaly_signals:
            print(f"[briefing]   [{a['severity']}] {a['type']}: {a['consulting_angle']}")

    # 6. Get recent change events for temporal context
    recent_changes = get_recent_changes(conn, dossier["id"], limit=15)
    if recent_changes:
        print(f"[briefing] {len(recent_changes)} recent change events to incorporate")

    # 7. Build prompt and generate
    print("[briefing] Generating briefing via LLM (this may take 30-60 seconds)...")
    prompt = build_briefing_prompt(
        company_name, all_key_facts, report_summaries,
        hiring_stats=hiring_stats,
        hiring_snapshots=hiring_snapshots,
        data_confidence=data_confidence,
        algo_scores=algo_scores,
        anomaly_signals=anomaly_signals,
        lens_config=lens_config,
    )
    if recent_changes:
        changes_text = "\n".join([
            f"- [{c['event_date']}] {c['title']}: {c['description']}"
            for c in recent_changes
        ])
        prompt += (
            f"\n\n## Recent Changes Detected Between Analysis Runs\n{changes_text}\n\n"
            f"Incorporate these trends into your Strategic Outlook and Key Opportunities sections. "
            f"Highlight which changes are most strategically significant."
        )
    briefing = generate_json(prompt, timeout=90, chain=BRIEFING_CHAIN)

    if not isinstance(briefing, dict):
        msg = "LLM did not return valid JSON — all providers may be rate-limited or down"
        print(f"[briefing] {msg}")
        conn.close()
        raise RuntimeError(msg)

    # 7.5. Normalize schema key — LLM may return "digital_maturity" or "scoring"
    if "digital_maturity" in briefing and "scoring" not in briefing:
        briefing["scoring"] = briefing.pop("digital_maturity")

    # 8. Post-process scoring section
    if "scoring" in briefing:
        scoring = briefing["scoring"]
        sub = scoring.get("sub_scores", {})

        # Build weight map from lens dimensions
        weights = {dim["key"]: dim["weight"] for dim in lens_dimensions}

        # If DT lens: inject algorithmic metadata for info-icon audit trail
        if use_algo and algo_scores:
            # Map dimension keys — handle both org_readiness and organizational_readiness
            _DIM_MAP = {
                "tech_modernity": "tech_modernity",
                "data_analytics": "data_analytics",
                "ai_readiness": "ai_readiness",
                "org_readiness": "org_readiness",
                "organizational_readiness": "org_readiness",
            }
            for schema_key in list(sub.keys()):
                scoring_key = _DIM_MAP.get(schema_key)
                if scoring_key and scoring_key in algo_scores:
                    dim_data = algo_scores[scoring_key]
                    sub[schema_key]["algorithmic_score"] = dim_data.get("algorithmic_score", 50)
                    sub[schema_key]["algorithmic_confidence"] = dim_data.get("confidence", 0.0)
                    sub[schema_key]["signals_used"] = dim_data.get("signals_used", [])

            scoring["algorithmic_weighted_score"] = algo_scores["weighted_algorithmic_score"]
            scoring["overall_algorithmic_confidence"] = algo_scores["overall_confidence"]

        # Recompute overall_score from LLM sub-scores (never trust LLM arithmetic)
        computed_overall = sum(
            sub.get(k, {}).get("score", 50) * w
            for k, w in weights.items()
        )
        scoring["overall_score"] = round(computed_overall)

        # Compute label from lens labels
        score_val = scoring["overall_score"]
        scoring["overall_label"] = "Unknown"
        for tier in lens_labels:
            if score_val >= tier["min_score"]:
                scoring["overall_label"] = tier["label"]
                break

        # Inject lens metadata for frontend rendering
        scoring["_lens"] = {
            "id": lens["id"],
            "name": lens["name"],
            "slug": lens["slug"],
            "score_label": score_label,
        }
        scoring["_dimensions"] = [
            {"key": d["key"], "label": d["label"], "weight": d["weight"]}
            for d in lens_dimensions
        ]
        scoring["_lens_labels"] = lens_labels

        if use_algo and algo_scores:
            ref_str = f" [algo reference: {algo_scores['weighted_algorithmic_score']}/100]"
        else:
            ref_str = ""
        print(f"[briefing] {score_label}: {scoring['overall_score']}/100 ({scoring['overall_label']}){ref_str}")

    # 9. Store on dossier
    now = datetime.now(timezone.utc).isoformat()
    model_used = "unknown"
    conn.execute(
        """UPDATE dossiers
           SET briefing_json = ?, briefing_generated_at = ?, briefing_model = ?,
               briefing_lens_id = ?, updated_at = ?
           WHERE id = ?""",
        (json.dumps(briefing), now, model_used, lens["id"], now, dossier["id"]),
    )
    conn.commit()
    conn.close()

    # Summary
    scoring = briefing.get("scoring", {})
    opps = briefing.get("engagement_opportunities", [])
    conf = briefing.get("data_confidence", {})
    print(f"\n[briefing] {score_label}: {scoring.get('overall_score', '?')}/100 "
          f"({scoring.get('overall_label', '?')})")
    print(f"[briefing] Confidence: {conf.get('overall_confidence', '?')}")
    print(f"[briefing] Engagement opportunities: {len(opps)}")
    for opp in opps[:3]:
        sources = opp.get("source_analyses", [])
        src_str = f" [{', '.join(sources)}]" if sources else ""
        print(f"[briefing]   [{opp.get('priority', '?').upper()}] {opp.get('service', '?')} "
              f"— {opp.get('estimated_scope', '?')}{src_str}")

    traj = briefing.get("hiring_trajectory")
    if traj:
        print(f"[briefing] Hiring trajectory: {traj.get('trend', '?')} ({traj.get('velocity', '')})")

    print(f"\n{'='*60}")
    print(f"  Briefing complete for {company_name}")
    print(f"{'='*60}")

    return briefing
