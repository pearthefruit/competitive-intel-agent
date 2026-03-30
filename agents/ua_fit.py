"""Agent: Prospect Fit Scoring — evaluates a company's suitability for Universal Ads (premium video).

Pipeline per company:
  1. Validate website (HTTP check + parked domain detection)
  2. Run research analyses sequentially: techstack -> financial -> brand_ad
     (sequential because ddgs uses ThreadPoolExecutor internally — nesting causes deadlocks)
  3. Score from actual analysis reports using a fixed 5-dimension rubric
  4. Save to dossier (visible in Research module too)

Across companies, scoring runs in parallel (ThreadPoolExecutor with max_workers=3).
"""

import json
import httpx
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from agents.llm import generate_json, save_to_dossier, unique_report_path, BRIEFING_CHAIN
from agents.financial import financial_analysis
from agents.techstack import techstack_analysis
from agents.brand_ad import brand_ad_intelligence
from prompts.ua_fit import build_ua_fit_prompt
from db import get_connection, get_or_create_dossier


# ---- Fixed scoring dimensions — no ICP config ----

DIMENSIONS = {
    "financial_capacity":      {"label": "Financial Capacity",      "weight": 0.25},
    "advertising_maturity":    {"label": "Paid Media Footprint",     "weight": 0.20},
    "growth_trajectory":       {"label": "Growth Trajectory",        "weight": 0.20},
    "creative_readiness":      {"label": "Video Asset Readiness",    "weight": 0.20},
    "channel_expansion_intent":{"label": "Channel Expansion Intent", "weight": 0.15},
}

_LABELS = [
    (80, "Prime Prospect"),
    (60, "Strong Candidate"),
    (40, "Possible Fit"),
    (20, "Weak Fit"),
    (0,  "Not a Fit"),
]

REPORT_FRESHNESS_DAYS = 7

_PARKED_INDICATORS = [
    "domain for sale", "buy this domain", "this domain is parked",
    "domain parking", "hugedomains", "dan.com", "sedo.com", "afternic",
    "this page is under construction", "website coming soon",
    "godaddy.com/domains", "namecheap.com", "domain expired",
]


def _get_label(score):
    for threshold, label in _LABELS:
        if score >= threshold:
            return label
    return "Not a Fit"


# ---- Website Validation ----

def validate_websites(companies, timeout=5, progress_cb=None):
    """Validate company websites — HTTP check + parked domain detection.

    Companies without a website URL are kept (they skip techstack but still
    get financial + sentiment analysis).

    Returns (valid_companies, validation_results).
    """
    if progress_cb:
        progress_cb("validating", {"total": len(companies)})

    valid = []
    results = []

    for company in companies:
        name = company.get("name", "?")
        website = company.get("website")

        if not website:
            results.append({"name": name, "website": None, "valid": True,
                             "reason": "No website — will skip techstack"})
            valid.append(company)
            if progress_cb:
                progress_cb("validated", {"company": name, "valid": True,
                                          "reason": "No website provided"})
            continue

        url = website if website.startswith("http") else f"https://{website}"

        try:
            resp = httpx.get(url, timeout=timeout, follow_redirects=True,
                             headers={"User-Agent": "Mozilla/5.0 (compatible; SignalVault/1.0)"})

            if resp.status_code >= 400:
                reason = f"HTTP {resp.status_code} — website protected"
                company["_website_accessible"] = False
                results.append({"name": name, "website": website, "valid": True,
                                 "reason": reason, "limited": True})
                valid.append(company)
                if progress_cb:
                    progress_cb("validated", {"company": name, "valid": True,
                                              "reason": reason, "limited": True})
                continue

            body_lower = resp.text[:5000].lower()
            parked = False
            for indicator in _PARKED_INDICATORS:
                if indicator in body_lower:
                    reason = f"Parked domain ('{indicator}') — will skip techstack"
                    company["_website_accessible"] = False
                    results.append({"name": name, "website": website, "valid": True,
                                     "reason": reason, "limited": True})
                    valid.append(company)
                    if progress_cb:
                        progress_cb("validated", {"company": name, "valid": True,
                                                  "reason": reason, "limited": True})
                    parked = True
                    break

            if not parked:
                # Store resolved URL in case it redirected
                company["website"] = str(resp.url)
                results.append({"name": name, "website": str(resp.url), "valid": True, "reason": "OK"})
                valid.append(company)
                if progress_cb:
                    progress_cb("validated", {"company": name, "valid": True, "reason": "OK"})

        except Exception as e:
            reason = f"Connection failed ({type(e).__name__})"
            company["_website_accessible"] = False
            results.append({"name": name, "website": website, "valid": True,
                             "reason": reason, "limited": True})
            valid.append(company)
            if progress_cb:
                progress_cb("validated", {"company": name, "valid": True,
                                          "reason": reason, "limited": True})

    valid_count = len(valid)
    rejected_count = len(companies) - valid_count
    limited_count = sum(1 for r in results if r.get("limited"))
    print(f"[validate] {valid_count} valid ({limited_count} limited data), {rejected_count} rejected")
    return valid, results


# ---- Report Caching ----

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
        print(f"[ua-fit] Could not check for recent {analysis_type} report for {company}: {e}")
    return None


def _summarize_report(report_path, max_chars=120):
    """Extract a one-line summary from a report for SSE progress events."""
    try:
        text = Path(report_path).read_text(encoding="utf-8")
        for line in text.split("\n"):
            line = line.strip()
            if line and not line.startswith("#") and len(line) > 20:
                return line[:max_chars]
    except Exception:
        pass
    return "Analysis complete"


# ---- Analysis Orchestration ----

def _run_analyses_for_company(company_name, website_url=None, db_path="intel.db", progress_cb=None):
    """Run techstack, financial, and brand_ad analyses SEQUENTIALLY for one company.

    Sequential execution is required because ddgs (DuckDuckGo) uses ThreadPoolExecutor
    internally — nesting threadpools causes deadlocks.

    Returns dict of {analysis_type: report_path_or_None}.
    """
    # Build ordered analysis list: techstack first (fast), then financial, then brand_ad
    analyses = []
    if website_url:
        analyses.append((
            "techstack", "Tech Stack",
            lambda: techstack_analysis(website_url, max_pages=3,
                                       company_name=company_name, db_path=db_path)
        ))
    analyses.append(("financial", "Financial", lambda: financial_analysis(company_name)))
    analyses.append(("brand_ad", "Brand & Ad Intel", lambda: brand_ad_intelligence(company_name)))

    report_paths = {}

    for analysis_type, label, run_fn in analyses:
        if progress_cb:
            progress_cb("analysis_start", {
                "company": company_name,
                "analysis_type": analysis_type,
                "label": f"Running {label.lower()} analysis...",
            })

        # Check for a recent cached report first
        recent = _find_recent_report(company_name, analysis_type, db_path=db_path)
        if recent:
            print(f"[ua-fit] {company_name}/{analysis_type}: reusing recent report → {recent}")
            report_paths[analysis_type] = recent
            if progress_cb:
                progress_cb("analysis_done", {
                    "company": company_name,
                    "analysis_type": analysis_type,
                    "report_path": recent,
                    "key_facts": f"↩ Reused cached report ({REPORT_FRESHNESS_DAYS}d window)",
                    "reused": True,
                })
            continue

        try:
            print(f"[ua-fit] {company_name}/{analysis_type}: running fresh...")
            path = run_fn()
            if path:
                report_paths[analysis_type] = path
                key_facts = _summarize_report(path)
                print(f"[ua-fit] {company_name}/{analysis_type}: done → {path}")
                if progress_cb:
                    progress_cb("analysis_done", {
                        "company": company_name,
                        "analysis_type": analysis_type,
                        "report_path": path,
                        "key_facts": key_facts,
                        "reused": False,
                    })
            else:
                print(f"[ua-fit] {company_name}/{analysis_type}: no results")
                if progress_cb:
                    progress_cb("analysis_done", {
                        "company": company_name,
                        "analysis_type": analysis_type,
                        "report_path": None,
                        "key_facts": "No data returned",
                        "reused": False,
                    })
        except Exception as e:
            print(f"[ua-fit] {company_name}/{analysis_type} failed: {e}")
            if progress_cb:
                progress_cb("analysis_done", {
                    "company": company_name,
                    "analysis_type": analysis_type,
                    "report_path": None,
                    "key_facts": f"Error: {str(e)[:100]}",
                    "reused": False,
                })

    return report_paths


def _read_and_truncate_reports(report_paths, max_chars_per_report=2500):
    """Read report files and truncate to fit LLM context window.

    Returns dict of {analysis_type: truncated_text}.
    """
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
            print(f"[ua-fit] Could not read {analysis_type} report at {path}: {e}")
    return reports


# ---- Main Scoring Function ----

def score_ua_fit(company_name, website_url=None, db_path="intel.db", progress_cb=None):
    """Score a company's prospect fit using research analysis reports.

    Runs techstack, financial, and brand_ad analyses (reusing cached reports when
    available), then scores against 5 fixed dimensions.

    Returns the fit score dict or None.
    """
    print(f"\n[ua-fit] Scoring prospect fit for {company_name}...")

    # Emit BEFORE analyses start so the UI can create the card + analysis step badges
    if progress_cb:
        progress_cb("analyzing", {
            "company": company_name,
            "has_website": bool(website_url),
        })

    # Step 1: Run analyses sequentially
    report_paths = _run_analyses_for_company(
        company_name, website_url=website_url, db_path=db_path, progress_cb=progress_cb
    )

    if not report_paths:
        print(f"[ua-fit] No analyses completed for {company_name} — cannot score")
        return None

    # Step 2: Read and truncate for LLM context
    reports = _read_and_truncate_reports(report_paths)

    # Step 3: Score with LLM
    if progress_cb:
        progress_cb("scoring", {"company": company_name})

    prompt = build_ua_fit_prompt(company_name, reports, website_url)

    print(f"[ua-fit] Generating prospect fit score for {company_name}...")
    fit_data = generate_json(prompt, timeout=90, chain=BRIEFING_CHAIN)

    if not isinstance(fit_data, dict) or "sub_scores" not in fit_data:
        print(f"[ua-fit] LLM did not return valid fit data. Retrying...")
        fit_data = generate_json(prompt, timeout=90, chain=BRIEFING_CHAIN)
        if not isinstance(fit_data, dict) or "sub_scores" not in fit_data:
            print(f"[ua-fit] Failed to generate prospect fit score for {company_name}.")
            return None

    # Step 4: Recompute overall score — never trust LLM arithmetic
    sub_scores = fit_data.get("sub_scores", {})
    computed_overall = 0.0
    for dim_key, dim_info in DIMENSIONS.items():
        dim_data = sub_scores.get(dim_key, {})
        score = dim_data.get("score", 50)
        try:
            score = int(score)
        except (ValueError, TypeError):
            score = 50
        score = max(0, min(100, score))
        computed_overall += score * dim_info["weight"]

    fit_data["overall_score"] = round(computed_overall)
    fit_data["overall_label"] = _get_label(fit_data["overall_score"])

    # Step 5: Set signal coverage from analyses actually run
    n_analyses = len(report_paths)
    n_total = 3  # techstack, financial, brand_ad
    confidence = "high" if n_analyses >= 2 else ("moderate" if n_analyses == 1 else "low")
    fit_data["signal_coverage"] = {
        "categories_with_data": n_analyses,
        "categories_total": n_total,
        "confidence": confidence,
    }

    # Step 6: Store dimension metadata + analysis provenance
    fit_data["_dimensions"] = [
        {"key": k, "label": v["label"], "weight": v["weight"]}
        for k, v in DIMENSIONS.items()
    ]
    fit_data["_analyses_used"] = {
        atype: path for atype, path in report_paths.items()
    }

    print(f"[ua-fit] {company_name}: {fit_data['overall_score']}/100 — {fit_data['overall_label']}")

    # Step 7: Save to dossier
    conn = get_connection(db_path)
    dossier_id = get_or_create_dossier(conn, company_name)
    conn.execute(
        "UPDATE dossiers SET ua_fit_json = ?, ua_fit_generated_at = ? WHERE id = ?",
        (json.dumps(fit_data), datetime.now(timezone.utc).isoformat(), dossier_id),
    )
    conn.commit()
    conn.close()

    # Save as standalone report and register in dossier_analyses
    report = _build_fit_report(company_name, fit_data, website_url)
    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    safe_name = company_name.lower().replace(" ", "_").replace(".", "_")[:40]
    filename = unique_report_path(reports_dir, f"{safe_name}_prospect_fit_{today}.md")
    filename.write_text(report, encoding="utf-8")
    print(f"[ua-fit] Report saved to {filename}")

    save_to_dossier(company_name, "ua_fit", report_file=str(filename),
                    report_text=report, model_used="llm-scored", db_path=db_path)

    return fit_data


def _build_fit_report(company_name, fit_data, website_url=None):
    """Build a markdown report from the fit score data."""
    today = datetime.now().strftime("%Y-%m-%d")
    overall = fit_data.get("overall_score", "?")
    label = fit_data.get("overall_label", "?")
    angle = fit_data.get("recommended_angle", "N/A")
    snapshot = fit_data.get("company_snapshot", {})
    sub_scores = fit_data.get("sub_scores", {})
    risks = fit_data.get("key_risks", [])
    coverage = fit_data.get("signal_coverage", {})
    analyses_used = fit_data.get("_analyses_used", {})

    lines = [
        f"# Prospect Fit Score: {company_name}",
        f"",
        f"**Date:** {today}",
        f"**Overall Score:** {overall}/100 — **{label}**",
        f"**Confidence:** {coverage.get('confidence', '?')} "
        f"({coverage.get('categories_with_data', '?')}/{coverage.get('categories_total', '?')} analyses)",
        f"**Analyses used:** {', '.join(analyses_used.keys()) or 'none'}",
        f"",
        f"---",
        f"",
        f"## Recommended Sales Angle",
        f"",
        f"{angle}",
        f"",
        f"## Score Breakdown",
        f"",
        f"| Dimension | Score | Weight |",
        f"|-----------|-------|--------|",
    ]

    for dim_key, dim_info in DIMENSIONS.items():
        dim = sub_scores.get(dim_key, {})
        score = dim.get("score", "?")
        weight_pct = f"{int(dim_info['weight'] * 100)}%"
        lines.append(f"| {dim_info['label']} | {score}/100 | {weight_pct} |")

    lines.extend(["", "## Detailed Analysis", ""])

    for dim_key, dim_info in DIMENSIONS.items():
        dim = sub_scores.get(dim_key, {})
        rationale = dim.get("rationale", "No data")
        dim_signals = dim.get("signals", [])
        lines.append(f"### {dim_info['label']} — {dim.get('score', '?')}/100")
        lines.append(f"")
        lines.append(rationale)
        if dim_signals:
            lines.append(f"")
            lines.append("**Key signals:**")
            for s in dim_signals:
                lines.append(f"- {s}")
        lines.append("")

    if risks:
        lines.extend(["## Key Risks & Objections", ""])
        for r in risks:
            lines.append(f"- {r}")
        lines.append("")

    if snapshot:
        lines.extend(["## Company Snapshot", ""])
        for k, v in snapshot.items():
            if v:
                label_k = k.replace("_", " ").title()
                if isinstance(v, list):
                    v = ", ".join(str(x) for x in v)
                lines.append(f"- **{label_k}:** {v}")
        lines.append("")

    if analyses_used:
        lines.extend(["## Analysis Sources", ""])
        for atype, path in analyses_used.items():
            lines.append(f"- **{atype.title()}:** `{path}`")

    return "\n".join(lines)


# ---- Batch / Pipeline ----

def batch_score(companies, db_path="intel.db", max_workers=3, progress_cb=None):
    """Score multiple companies in parallel (max_workers at a time).

    Per company, analyses run SEQUENTIALLY (techstack -> financial -> brand_ad).
    Parallelism is strictly ACROSS companies to avoid nested threadpool deadlocks.

    Returns list of (name, score_dict_or_None) in original order.
    """
    results = {}

    def _score_one(company):
        name = company.get("name") if isinstance(company, dict) else company
        website = company.get("website") if isinstance(company, dict) else None
        # Skip techstack if website is inaccessible (403, connection failed)
        if isinstance(company, dict) and not company.get("_website_accessible", True):
            website = None
        try:
            fit = score_ua_fit(name, website_url=website, db_path=db_path,
                               progress_cb=progress_cb)
            return (name, fit)
        except Exception as e:
            print(f"[ua-fit] Error scoring {name}: {e}")
            return (name, None)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_score_one, c): c for c in companies}
        for future in as_completed(futures):
            name, fit = future.result()
            results[name] = fit

    # Return in original discovery order
    ordered = []
    for company in companies:
        name = company.get("name") if isinstance(company, dict) else company
        ordered.append((name, results.get(name)))
    return ordered


def run_pipeline(niche, top_n=15, db_path="intel.db", progress_cb=None):
    """Full pipeline: discover -> validate -> analyze+score.

    Returns (companies, scored_results, report_path).
    """
    from agents.ua_discover import discover_prospects

    # Step 1: Discover
    companies = discover_prospects(niche, top_n=top_n, db_path=db_path)
    if not companies:
        print("[pipeline] No companies discovered. Aborting.")
        return [], [], None

    # Step 2: Validate websites
    valid_companies, validation_results = validate_websites(companies, progress_cb=progress_cb)
    rejected = [v for v in validation_results if not v["valid"]]
    if rejected:
        print(f"[pipeline] Rejected {len(rejected)} companies:")
        for r in rejected:
            print(f"[pipeline]   ✗ {r['name']} — {r['reason']}")

    if not valid_companies:
        print("[pipeline] No valid companies after validation. Aborting.")
        return companies, [], None

    # Step 3: Score in parallel (sequential per company)
    print(f"\n{'='*60}")
    print(f"  Scoring {len(valid_companies)} companies")
    print(f"{'='*60}")
    results = batch_score(valid_companies, db_path=db_path, progress_cb=progress_cb)

    # Step 4: Build ranked report
    scored = [(name, fit) for name, fit in results if fit]
    scored.sort(key=lambda x: x[1].get("overall_score", 0), reverse=True)

    today = datetime.now().strftime("%Y-%m-%d")
    safe_niche = niche.lower().replace(" ", "_").replace("/", "_")[:40]

    lines = [
        f"# Prospecting Report: {niche}",
        f"",
        f"**Date:** {today}",
        f"**Companies scored:** {len(scored)}/{len(valid_companies)} valid "
        f"({len(companies) - len(valid_companies)} rejected at validation)",
        f"",
        f"---",
        f"",
        f"## Ranked Prospects",
        f"",
        f"| Rank | Company | Score | Label | Confidence | Angle |",
        f"|------|---------|-------|-------|------------|-------|",
    ]

    for i, (name, fit) in enumerate(scored, 1):
        score = fit.get("overall_score", "?")
        lbl = fit.get("overall_label", "?")
        confidence = fit.get("signal_coverage", {}).get("confidence", "?")
        angle = fit.get("recommended_angle", "N/A")
        if len(angle) > 80:
            angle = angle[:77] + "..."
        lines.append(f"| {i} | **{name}** | {score} | {lbl} | {confidence} | {angle} |")

    lines.extend(["", "## Detailed Scores", ""])

    for i, (name, fit) in enumerate(scored, 1):
        score = fit.get("overall_score", "?")
        lbl = fit.get("overall_label", "?")
        angle = fit.get("recommended_angle", "N/A")
        risks = fit.get("key_risks", [])
        sub_scores = fit.get("sub_scores", {})

        lines.append(f"### {i}. {name} — {score}/100 ({lbl})")
        lines.append(f"")
        lines.append(f"**Angle:** {angle}")
        lines.append(f"")

        for dim_key, dim_info in DIMENSIONS.items():
            dim = sub_scores.get(dim_key, {})
            dim_score = dim.get("score", "?")
            lines.append(f"- {dim_info['label']}: {dim_score}/100")

        if risks:
            lines.append(f"")
            lines.append("**Risks:**")
            for r in risks:
                lines.append(f"- {r}")
        lines.append("")

    report = "\n".join(lines)
    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    filename = unique_report_path(reports_dir, f"prospecting_{safe_niche}_{today}.md")
    filename.write_text(report, encoding="utf-8")
    print(f"\n[pipeline] Ranked report saved to {filename}")

    return companies, results, str(filename)


# ---- Vertical Insight Generation ----

def generate_vertical_insight(campaign_id, db_path="intel.db"):
    """Generate a vertical insight for a campaign from its scored prospects.

    Reads all scored prospects, builds a summary, calls LLM, saves to campaigns.insight_json.
    Returns the insight dict or None.
    """
    from prompts.ua_fit import build_vertical_insight_prompt
    from db import get_campaign_detail, get_connection

    conn = get_connection(db_path)
    campaign = get_campaign_detail(conn, campaign_id)
    conn.close()

    if not campaign:
        print(f"[insight] Campaign {campaign_id} not found")
        return None

    niche = campaign.get("niche", "unknown")
    prospects = campaign.get("prospects", [])

    # Build summaries from scored prospects only
    summaries = []
    for p in prospects:
        fit = p.get("ua_fit")
        if not fit:
            continue
        summaries.append({
            "company_name": p.get("company_name", "?"),
            "overall_score": fit.get("overall_score", 0),
            "overall_label": fit.get("overall_label", "?"),
            "sub_scores": fit.get("sub_scores", {}),
            "recommended_angle": fit.get("recommended_angle", ""),
            "key_risks": fit.get("key_risks", []),
            "company_snapshot": fit.get("company_snapshot", {}),
        })

    if not summaries:
        print(f"[insight] No scored prospects in campaign {campaign_id}")
        return None

    print(f"[insight] Generating vertical insight for '{niche}' ({len(summaries)} prospects)...")
    prompt = build_vertical_insight_prompt(niche, summaries)
    insight = generate_json(prompt, timeout=90, chain=BRIEFING_CHAIN)

    if not insight:
        print("[insight] LLM returned no insight")
        return None

    # Save to DB
    conn = get_connection(db_path)
    conn.execute(
        "UPDATE campaigns SET insight_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (json.dumps(insight), campaign_id),
    )
    conn.commit()
    conn.close()

    print(f"[insight] Vertical insight saved for campaign {campaign_id}")
    return insight


# ---- Outreach Brief Generation ----

def generate_outreach_brief(company_name, campaign_id, db_path="intel.db"):
    """Generate an outreach brief for a prospect within a campaign.

    Reads the prospect's fit data + actual report files + campaign vertical insight,
    calls LLM, saves to campaign_prospects.brief_json.
    Returns the brief dict or None.
    """
    from prompts.ua_fit import build_outreach_brief_prompt
    from db import get_campaign_detail, get_connection

    conn = get_connection(db_path)
    campaign = get_campaign_detail(conn, campaign_id)
    conn.close()

    if not campaign:
        print(f"[brief] Campaign {campaign_id} not found")
        return None

    # Find the prospect in this campaign
    prospect = None
    for p in campaign.get("prospects", []):
        if p.get("company_name") == company_name:
            prospect = p
            break

    if not prospect:
        print(f"[brief] {company_name} not found in campaign {campaign_id}")
        return None

    fit = prospect.get("ua_fit")
    if not fit:
        print(f"[brief] No fit data for {company_name}")
        return None

    # Read and truncate the analysis reports that backed the score
    reports = {}
    analyses_used = fit.get("_analyses_used", {})
    for atype, path in analyses_used.items():
        if path:
            try:
                text = Path(path).read_text(encoding="utf-8")
                reports[atype] = text[:3000]  # slightly more context for briefs
            except Exception:
                pass

    # Get vertical insight if available
    vertical_insight = campaign.get("insight")

    print(f"[brief] Generating outreach brief for {company_name}...")
    prompt = build_outreach_brief_prompt(company_name, fit, reports, vertical_insight)
    brief = generate_json(prompt, timeout=90, chain=BRIEFING_CHAIN)

    if not brief:
        print("[brief] LLM returned no brief")
        return None

    # Save to campaign_prospects
    conn = get_connection(db_path)
    conn.execute(
        """UPDATE campaign_prospects SET brief_json = ?, prospect_status = 'brief_ready'
           WHERE campaign_id = ? AND dossier_id = (
               SELECT id FROM dossiers WHERE company_name = ? LIMIT 1
           )""",
        (json.dumps(brief), campaign_id, company_name),
    )
    conn.commit()
    conn.close()

    print(f"[brief] Outreach brief saved for {company_name} in campaign {campaign_id}")
    return brief
