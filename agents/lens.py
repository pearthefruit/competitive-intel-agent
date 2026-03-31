"""Agent: Lens Scoring — evaluate a company through a configurable evaluation framework.

Generalizes the ua_fit.py scoring pattern with dynamic dimensions from lens config.
Analyses run sequentially per company (ddgs deadlock prevention), leveraging 7-day cache.
"""

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from agents.llm import generate_json, save_to_dossier, unique_report_path, BRIEFING_CHAIN
from prompts.lens import build_lens_scoring_prompt
from db import (
    get_connection, get_or_create_dossier, get_lens, get_lens_by_slug,
    save_lens_score,
)

REPORT_FRESHNESS_DAYS = 7


# ---- Analysis dispatch ----
# Lazy imports to avoid circular dependencies — each entry is
# (module_path, function_name, human_label, needs_website)

_DISPATCH_REGISTRY = {
    "techstack":   ("agents.techstack",   "techstack_analysis",   "Tech Stack",       True),
    "financial":   ("agents.financial",    "financial_analysis",   "Financial",         False),
    "brand_ad":    ("agents.brand_ad",     "brand_ad_intelligence","Brand & Ad Intel",  False),
    "sentiment":   ("agents.sentiment",    "sentiment_analysis",   "Sentiment",         False),
    "competitors": ("agents.competitors",  "competitor_analysis",  "Competitors",       False),
    "hiring":      ("agents.analyze",      "analyze",              "Hiring Analysis",   False),
    "patents":     ("agents.patents",      "patent_analysis",      "Patents",           False),
    "seo":         ("agents.seo",          "seo_audit",            "SEO Audit",         True),
    "pricing":     ("agents.pricing",      "pricing_analysis",     "Pricing",           True),
}


def _get_analysis_fn(analysis_type):
    """Lazy-import and return the analysis function."""
    entry = _DISPATCH_REGISTRY.get(analysis_type)
    if not entry:
        return None, None, False
    module_path, fn_name, label, needs_website = entry
    import importlib
    mod = importlib.import_module(module_path)
    return getattr(mod, fn_name), label, needs_website


def _run_analysis(analysis_type, company_name, website_url=None, db_path="intel.db", progress_cb=None):
    """Run a single analysis, handling the different function signatures."""
    fn, label, needs_website = _get_analysis_fn(analysis_type)
    if fn is None:
        print(f"[lens] Unknown analysis type: {analysis_type}")
        return None

    if needs_website and not website_url:
        print(f"[lens] Skipping {analysis_type} — no website URL")
        return None

    if analysis_type == "techstack":
        return fn(website_url, max_pages=3, company_name=company_name, db_path=db_path, progress_cb=progress_cb)
    elif analysis_type == "seo":
        return fn(website_url, max_pages=5, company_name=company_name)
    elif analysis_type == "pricing":
        return fn(website_url, company_name=company_name)
    elif analysis_type == "hiring":
        return fn(company_name, db_path=db_path)
    elif analysis_type in ("financial", "sentiment"):
        return fn(company_name, progress_cb=progress_cb)
    else:
        # brand_ad, competitors, patents — no progress_cb yet
        return fn(company_name)


# ---- Report caching (reused from ua_fit pattern) ----

def _find_recent_report(company, analysis_type, max_age_days=REPORT_FRESHNESS_DAYS, db_path="intel.db"):
    """Check dossier_analyses for a recent report of this type. Returns file path or None."""
    try:
        conn = get_connection(db_path)
        row = conn.execute(
            """SELECT da.report_file, da.created_at FROM dossier_analyses da
               JOIN dossiers d ON da.dossier_id = d.id
               WHERE d.company_name = ? COLLATE NOCASE
                 AND da.analysis_type = ?
                 AND da.report_file IS NOT NULL
               ORDER BY da.created_at DESC LIMIT 1""",
            (company, analysis_type),
        ).fetchone()
        conn.close()

        if not row:
            return None

        created = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
        age_days = (datetime.now(timezone.utc) - created).days
        if age_days > max_age_days:
            return None

        path = Path(row["report_file"])
        if path.exists():
            return str(path)
    except Exception as e:
        print(f"[lens] Could not check for recent {analysis_type} report for {company}: {e}")
    return None


def _read_and_truncate_reports(report_paths, max_chars_per_report=2500):
    """Read report files and truncate to fit LLM context window."""
    reports = {}
    for analysis_type, path in report_paths.items():
        if not path:
            continue
        try:
            text = Path(path).read_text(encoding="utf-8")
            if len(text) > max_chars_per_report:
                text = text[:max_chars_per_report] + "\n\n[... report truncated for context ...]"
            reports[analysis_type] = text
        except Exception as e:
            print(f"[lens] Could not read {analysis_type} report at {path}: {e}")
    return reports


def _summarize_report(report_path, max_chars=120):
    """Extract a one-line summary from a report for progress events."""
    try:
        text = Path(report_path).read_text(encoding="utf-8")
        for line in text.split("\n"):
            line = line.strip()
            if line and not line.startswith("#") and len(line) > 20:
                return line[:max_chars]
    except Exception:
        pass
    return "Analysis complete"


# ---- Scoring ----

def _get_label(score, labels):
    """Get the tier label for a score using the lens label config."""
    for tier in labels:
        if score >= tier["min_score"]:
            return tier["label"]
    return labels[-1]["label"] if labels else "Unknown"


def score_with_lens(company_name, lens_id, db_path="intel.db", website_url=None, progress_cb=None):
    """Score a company through a specific lens.

    1. Load lens config from DB
    2. Determine required analyses from dimensions' sources
    3. Run analyses sequentially (reusing 7-day cache)
    4. Read + truncate reports
    5. Build dynamic prompt from lens rubric
    6. LLM score → recompute weighted overall in Python
    7. Save to lens_scores table + generate markdown report

    Returns score_data dict or None.
    """
    conn = get_connection(db_path)
    lens = get_lens(conn, lens_id)
    conn.close()

    if not lens:
        print(f"[lens] Lens id={lens_id} not found")
        return None

    config = lens["config"]
    dimensions = config.get("dimensions", [])
    labels = config.get("labels", [])
    lens_name = lens["name"]

    print(f"\n[lens] Scoring {company_name} through '{lens_name}' lens...")

    if progress_cb:
        progress_cb("analyzing", {
            "company": company_name,
            "lens": lens_name,
            "analyses": list(_get_required_analyses(dimensions, website_url)),
        })

    # Collect required analyses from all dimensions
    required = _get_required_analyses(dimensions, website_url)

    # Run analyses sequentially
    report_paths = {}
    for analysis_type in required:
        _, label, _ = _get_analysis_fn(analysis_type)
        if not label:
            continue

        if progress_cb:
            progress_cb("analysis_start", {
                "company": company_name,
                "analysis_type": analysis_type,
                "label": f"Running {label.lower()} analysis...",
            })

        # Check 7-day cache
        recent = _find_recent_report(company_name, analysis_type, db_path=db_path)
        if recent:
            print(f"[lens] {company_name}/{analysis_type}: reusing cached report")
            report_paths[analysis_type] = recent
            if progress_cb:
                progress_cb("analysis_done", {
                    "company": company_name,
                    "analysis_type": analysis_type,
                    "report_path": recent,
                    "reused": True,
                })
            continue

        try:
            print(f"[lens] {company_name}/{analysis_type}: running fresh...")
            path = _run_analysis(analysis_type, company_name, website_url, db_path, progress_cb=progress_cb)
            if path:
                report_paths[analysis_type] = path
                print(f"[lens] {company_name}/{analysis_type}: done → {path}")
            if progress_cb:
                progress_cb("analysis_done", {
                    "company": company_name,
                    "analysis_type": analysis_type,
                    "report_path": path,
                    "reused": False,
                })
        except Exception as e:
            print(f"[lens] {company_name}/{analysis_type} failed: {e}")
            if progress_cb:
                progress_cb("analysis_done", {
                    "company": company_name,
                    "analysis_type": analysis_type,
                    "report_path": None,
                    "reused": False,
                })

    if not report_paths:
        print(f"[lens] No analyses completed for {company_name} — cannot score")
        return None

    # Read and truncate reports
    reports = _read_and_truncate_reports(report_paths)

    # Score with LLM
    if progress_cb:
        progress_cb("scoring", {"company": company_name, "lens": lens_name})

    prompt = build_lens_scoring_prompt(company_name, config, reports, website_url)

    print(f"[lens] Generating {lens_name} score for {company_name}...")
    score_data = generate_json(prompt, timeout=90, chain=BRIEFING_CHAIN)

    if not isinstance(score_data, dict) or "sub_scores" not in score_data:
        print(f"[lens] Invalid LLM response. Retrying...")
        score_data = generate_json(prompt, timeout=90, chain=BRIEFING_CHAIN)
        if not isinstance(score_data, dict) or "sub_scores" not in score_data:
            print(f"[lens] Failed to generate score for {company_name}")
            return None

    # Recompute overall score — never trust LLM arithmetic
    sub_scores = score_data.get("sub_scores", {})
    computed_overall = 0.0
    for dim in dimensions:
        dim_data = sub_scores.get(dim["key"], {})
        score = dim_data.get("score", 50)
        try:
            score = int(score)
        except (ValueError, TypeError):
            score = 50
        score = max(0, min(100, score))
        computed_overall += score * dim["weight"]

    score_data["overall_score"] = round(computed_overall)
    score_data["overall_label"] = _get_label(score_data["overall_score"], labels)

    # Soft-validate extended sections (backward compat — don't fail if absent)
    score_data.setdefault("engagement_opportunities", [])
    score_data.setdefault("risk_profile", [])
    score_data.setdefault("strategic_assessment", "")

    # Signal coverage
    n_analyses = len(report_paths)
    n_required = len(required)
    confidence = "high" if n_analyses >= max(2, n_required - 1) else ("moderate" if n_analyses >= 1 else "low")
    score_data["signal_coverage"] = {
        "categories_with_data": n_analyses,
        "categories_total": n_required,
        "confidence": confidence,
    }

    # Dimension metadata + analysis provenance
    score_data["_dimensions"] = [
        {"key": d["key"], "label": d["label"], "weight": d["weight"]}
        for d in dimensions
    ]
    score_data["_analyses_used"] = {atype: path for atype, path in report_paths.items()}
    score_data["_lens"] = {"id": lens["id"], "name": lens_name, "slug": lens["slug"], "score_label": config.get("score_label", "Lens Score")}
    score_data["_lens_labels"] = labels

    print(f"[lens] {company_name} [{lens_name}]: {score_data['overall_score']}/100 — {score_data['overall_label']}")

    # Save to lens_scores table
    conn = get_connection(db_path)
    dossier_id = get_or_create_dossier(conn, company_name)
    save_lens_score(
        conn, dossier_id, lens["id"],
        score_data["overall_score"], score_data["overall_label"],
        score_data, score_data["_analyses_used"],
    )
    conn.close()

    # Save markdown report
    report_md = _build_lens_report(company_name, lens, score_data, website_url)
    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    safe_name = company_name.lower().replace(" ", "_").replace(".", "_")[:40]
    safe_lens = lens["slug"].replace("-", "_")
    filename = unique_report_path(reports_dir, f"{safe_name}_{safe_lens}_{today}.md")
    filename.write_text(report_md, encoding="utf-8")
    print(f"[lens] Report saved to {filename}")

    save_to_dossier(company_name, f"lens_{lens['slug']}",
                    report_file=str(filename), report_text=report_md,
                    model_used="llm-scored", db_path=db_path)

    score_data["_report_file"] = str(filename)
    return score_data


def _get_required_analyses(dimensions, website_url=None):
    """Collect unique required analysis types from lens dimensions."""
    required = []
    seen = set()
    for dim in dimensions:
        for source in dim.get("sources", []):
            if source not in seen:
                # Skip website-dependent analyses if no URL
                entry = _DISPATCH_REGISTRY.get(source)
                if entry and entry[3] and not website_url:
                    continue
                seen.add(source)
                required.append(source)
    return required


def _build_lens_report(company_name, lens, score_data, website_url=None):
    """Build a markdown report from lens score data."""
    config = lens["config"]
    dimensions = config.get("dimensions", [])
    today = datetime.now().strftime("%Y-%m-%d")
    overall = score_data.get("overall_score", "?")
    label = score_data.get("overall_label", "?")
    angle = score_data.get("recommended_angle", "N/A")
    sub_scores = score_data.get("sub_scores", {})
    risks = score_data.get("key_risks", [])
    coverage = score_data.get("signal_coverage", {})
    analyses_used = score_data.get("_analyses_used", {})

    score_label = config.get("score_label", "Lens Score")

    lines = [
        f"# {score_label}: {company_name}",
        f"",
        f"**Lens:** {lens['name']}",
        f"**Date:** {today}",
        f"**Overall Score:** {overall}/100 — **{label}**",
        f"**Confidence:** {coverage.get('confidence', '?')} "
        f"({coverage.get('categories_with_data', '?')}/{coverage.get('categories_total', '?')} analyses)",
        f"**Analyses used:** {', '.join(analyses_used.keys()) or 'none'}",
        f"",
        f"---",
        f"",
        f"## Recommended Approach",
        f"",
        f"{angle}",
        f"",
        f"## Score Breakdown",
        f"",
        f"| Dimension | Score | Weight |",
        f"|-----------|-------|--------|",
    ]

    for dim in dimensions:
        dim_data = sub_scores.get(dim["key"], {})
        score = dim_data.get("score", "?")
        weight_pct = f"{int(dim['weight'] * 100)}%"
        lines.append(f"| {dim['label']} | {score}/100 | {weight_pct} |")

    lines.extend(["", "## Detailed Analysis", ""])

    for dim in dimensions:
        dim_data = sub_scores.get(dim["key"], {})
        rationale = dim_data.get("rationale", "No data")
        signals = dim_data.get("signals", [])
        lines.append(f"### {dim['label']} — {dim_data.get('score', '?')}/100")
        lines.append(f"")
        lines.append(rationale)
        if signals:
            lines.append(f"")
            lines.append("**Key signals:**")
            for s in signals:
                lines.append(f"- {s}")
        lines.append("")

    if risks:
        lines.extend(["## Key Risks", ""])
        for r in risks:
            lines.append(f"- {r}")
        lines.append("")

    # Engagement opportunities
    opps = score_data.get("engagement_opportunities", [])
    if opps:
        lines.extend(["## Consulting Opportunities", ""])
        for opp in opps:
            svc = opp.get("service", "Unknown")
            priority = opp.get("priority", "medium")
            evidence = opp.get("evidence", "")
            detail = opp.get("detail", "")
            scope = opp.get("estimated_scope", "")
            lines.append(f"### {svc} ({priority.upper()})")
            lines.append(f"")
            if evidence:
                lines.append(f"**Evidence:** {evidence}")
            if detail:
                lines.append(f"{detail}")
            if scope:
                lines.append(f"**Estimated scope:** {scope}")
            lines.append("")

    # Risk profile
    risk_profile = score_data.get("risk_profile", [])
    if risk_profile:
        lines.extend(["## Risk Profile", ""])
        for rp in risk_profile:
            cat = rp.get("category", "Unknown")
            desc = rp.get("description", "")
            sev = rp.get("severity", "medium")
            lines.append(f"- **{cat}** ({sev}): {desc}")
        lines.append("")

    # Strategic assessment
    strat = score_data.get("strategic_assessment", "")
    if strat:
        lines.extend(["## Strategic Assessment", "", strat, ""])

    snapshot = score_data.get("company_snapshot", {})
    if snapshot:
        lines.extend(["## Company Snapshot", ""])
        for k, v in snapshot.items():
            if v:
                label_k = k.replace("_", " ").title()
                if isinstance(v, list):
                    v = ", ".join(str(x) for x in v)
                lines.append(f"- **{label_k}:** {v}")
        lines.append("")

    return "\n".join(lines)


# ---- Batch scoring ----

def batch_score_lens(companies, lens_id, db_path="intel.db", max_workers=3, progress_cb=None):
    """Score multiple companies through a lens in parallel.

    Sequential analyses within each company, parallel across companies.
    Returns list of (name, score_data_or_None) in original order.
    """
    results = {}

    def _score_one(company):
        name = company.get("name", "?")
        website = company.get("website")
        try:
            score_data = score_with_lens(
                name, lens_id, db_path=db_path,
                website_url=website, progress_cb=progress_cb,
            )
            return name, score_data
        except Exception as e:
            print(f"[lens] Error scoring {name}: {e}")
            return name, None

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_score_one, c): c.get("name", "?") for c in companies}
        for future in as_completed(futures):
            name, score_data = future.result()
            results[name] = score_data

    # Return in original order
    return [(c.get("name", "?"), results.get(c.get("name", "?"))) for c in companies]
