"""Agent: Company Comparison & Landscape — side-by-side analysis and auto-discovery."""

import json
from datetime import datetime
from pathlib import Path

from agents.llm import generate_text, save_to_dossier, get_temporal_context, FAST_CHAIN
from agents.financial import financial_analysis
from agents.competitors import competitor_analysis
from agents.sentiment import sentiment_analysis
from agents.patents import patent_analysis
from scraper.web_search import search_web, format_search_results
from prompts.compare import build_comparison_prompt, build_landscape_prompt, build_extract_competitors_prompt, build_profile_lookup_prompt

DEFAULT_ANALYSES = ["financial", "sentiment", "competitors", "patents"]

ANALYSIS_FNS = {
    "financial": financial_analysis,
    "competitors": competitor_analysis,
    "sentiment": sentiment_analysis,
    "patents": patent_analysis,
}


def _run_analyses(company, analyses):
    """Run selected analyses for a company sequentially. Returns {type: path}.

    Runs sequentially to avoid nested ThreadPoolExecutor issues — ddgs (web search)
    uses threading internally, so nesting pools causes 'cannot schedule new futures
    after interpreter shutdown' errors.
    """
    report_paths = {}
    for atype in analyses:
        fn = ANALYSIS_FNS.get(atype)
        if not fn:
            continue
        try:
            print(f"[compare] {company} / {atype}: running...")
            path = fn(company)
            if path:
                report_paths[atype] = path
                print(f"[compare] {company} / {atype}: {path}")
            else:
                print(f"[compare] {company} / {atype}: no results")
        except Exception as e:
            print(f"[compare] {company} / {atype} failed: {e}")

    return report_paths


def _read_reports(report_paths):
    """Read report files into a dict of {type: content}."""
    contents = {}
    for atype, path in report_paths.items():
        try:
            contents[atype] = Path(path).read_text(encoding="utf-8")
        except Exception:
            pass
    return contents


def compare_companies(company_a, company_b, analyses=None):
    """Compare two companies side by side. Returns report path or None."""
    analyses = analyses or DEFAULT_ANALYSES

    print(f"\n{'='*60}")
    print(f"  Comparison: {company_a} vs {company_b}")
    print(f"  Analyses: {', '.join(analyses)}")
    print(f"{'='*60}\n")

    # Run analyses sequentially to avoid threading issues with ddgs
    print(f"[compare] Gathering data for {company_a} ({len(analyses)} analyses)...")
    paths_a = _run_analyses(company_a, analyses)

    print(f"\n[compare] Gathering data for {company_b} ({len(analyses)} analyses)...")
    paths_b = _run_analyses(company_b, analyses)

    # Report gaps per company
    missing_a = set(analyses) - set(paths_a.keys())
    missing_b = set(analyses) - set(paths_b.keys())
    if missing_a:
        print(f"[compare] Gaps for {company_a}: missing {', '.join(missing_a)} — comparison will be uneven in these areas")
    if missing_b:
        print(f"[compare] Gaps for {company_b}: missing {', '.join(missing_b)} — comparison will be uneven in these areas")

    if not paths_a and not paths_b:
        print("[compare] No analyses completed for either company — cannot generate comparison")
        return None

    # Read reports
    reports_a = _read_reports(paths_a)
    reports_b = _read_reports(paths_b)

    if not reports_a and not reports_b:
        print("[compare] Reports were generated but could not be read from disk")
        return None

    # Generate comparison
    print(f"\n[compare] Generating comparison report...")
    prompt = build_comparison_prompt(company_a, company_b, reports_a, reports_b)
    prompt += get_temporal_context(company_a, "comparison")
    text, model = generate_text(prompt)

    # Save
    today = datetime.now().strftime("%Y-%m-%d")
    safe_a = company_a.lower().replace(" ", "_").replace(".", "_")
    safe_b = company_b.lower().replace(" ", "_").replace(".", "_")

    header = f"""# Company Comparison: {company_a} vs {company_b}

**Date:** {today} | **Model:** {model}
**Analyses:** {', '.join(analyses)}

---

"""
    report = header + text

    # Append links to individual reports
    report += "\n\n---\n\n## Individual Reports\n\n"
    report += f"### {company_a}\n"
    for atype, path in sorted(paths_a.items()):
        report += f"- **{atype.title()}**: [{path}]({path})\n"
    report += f"\n### {company_b}\n"
    for atype, path in sorted(paths_b.items()):
        report += f"- **{atype.title()}**: [{path}]({path})\n"

    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    filename = reports_dir / f"{safe_a}_vs_{safe_b}_{today}.md"
    filename.write_text(report, encoding="utf-8")

    print(f"\n{'='*60}")
    print(f"  Comparison complete! Report: {filename}")
    print(f"{'='*60}")

    save_to_dossier(company_a, "comparison", report_file=str(filename), report_text=report, model_used=model)
    save_to_dossier(company_b, "comparison", report_file=str(filename), report_text=report, model_used=model)
    return str(filename)


def _parse_json_response(text):
    """Parse a JSON response from LLM, handling markdown code blocks."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        text = text.rsplit("```", 1)[0]
    return text.strip()


def _profile_lookup(company):
    """Quick web search + LLM to understand what a company does. Returns profile dict or None."""
    print(f"[landscape] Looking up profile for {company}...")

    results = search_web(f"{company} company what they do services", max_results=5)
    if not results:
        print(f"[landscape] No search results for {company} profile lookup")
        return None

    search_text = format_search_results(results)
    prompt = build_profile_lookup_prompt(company, search_text)
    text, _ = generate_text(prompt, timeout=30, chain=FAST_CHAIN)

    text = _parse_json_response(text)
    try:
        profile = json.loads(text)
        if isinstance(profile, dict):
            print(f"[landscape] Profile: {profile.get('industry', '?')} | {profile.get('scale', '?')} | serves {profile.get('client_type', '?')}")
            return profile
    except json.JSONDecodeError:
        print(f"[landscape] Could not parse profile response")

    return None


def _extract_competitor_names(company, top_n=3):
    """Profile-aware competitor discovery. Looks up what the company does first,
    then searches for competitors matching service focus, scale, and client type."""
    print(f"[landscape] Discovering competitors for {company}...")

    # Step 1: Profile lookup — understand what this company actually does
    profile = _profile_lookup(company)

    # Step 2: Build targeted search queries using profile context
    queries = [f"{company} top competitors"]
    if profile:
        industry = profile.get("industry", "")
        services = profile.get("services", [])
        if industry:
            queries.append(f"{company} competitors {industry}")
        if services:
            top_service = services[0] if services else ""
            if top_service:
                queries.append(f"top {industry or top_service} companies like {company}")

    # Run searches and deduplicate results
    all_results = []
    seen_urls = set()
    for query in queries:
        results = search_web(query, max_results=6)
        for r in (results or []):
            url = r.get("url") or r.get("href", "")
            if url not in seen_urls:
                seen_urls.add(url)
                all_results.append(r)

    if not all_results:
        print("[landscape] No search results for competitor discovery — company may be too niche or use a generic name that confuses search")
        return []

    search_text = format_search_results(all_results)
    prompt = build_extract_competitors_prompt(company, search_text, company_profile=profile)

    text, _ = generate_text(prompt, timeout=30, chain=FAST_CHAIN)

    # Parse JSON from response
    text = _parse_json_response(text)

    try:
        names = json.loads(text)
        if isinstance(names, list):
            # Filter out the target company and limit
            names = [n for n in names if n.lower() != company.lower()][:top_n]
            print(f"[landscape] Found competitors: {', '.join(names)}")
            return names
    except json.JSONDecodeError:
        print(f"[landscape] Could not parse competitor names from LLM response")
        return []

    return []


def landscape_analysis(company, top_n=3):
    """Auto-discover competitors and generate landscape report. Returns report path or None."""
    print(f"\n{'='*60}")
    print(f"  Competitive Landscape: {company}")
    print(f"{'='*60}\n")

    # Step 1: Discover competitors
    competitors = _extract_competitor_names(company, top_n)
    if not competitors:
        print("[landscape] Could not identify competitors. Try using 'compare' with specific companies instead.")
        return None

    # Step 2: Run analyses for all companies (target + competitors)
    all_companies = [company] + competitors
    analyses = ["financial", "sentiment"]  # Keep it focused to avoid rate limits

    all_reports = {}
    for comp in all_companies:
        print(f"\n[landscape] Analyzing {comp}...")
        paths = _run_analyses(comp, analyses)
        reports = _read_reports(paths)
        if reports:
            all_reports[comp] = reports

    if len(all_reports) < 2:
        print(f"[landscape] Only gathered data for {len(all_reports)} company — need at least 2 to generate a comparative landscape")
        print("[landscape] Some competitors may be too small/private for data collection. Try specifying known competitors with 'compare' instead.")
        return None

    # Step 3: Generate landscape report
    print(f"\n[landscape] Generating landscape report...")
    prompt = build_landscape_prompt(company, competitors, all_reports)
    prompt += get_temporal_context(company, "landscape")
    text, model = generate_text(prompt)

    # Save
    today = datetime.now().strftime("%Y-%m-%d")
    safe_name = company.lower().replace(" ", "_").replace(".", "_")

    comp_list = ", ".join(competitors)
    header = f"""# Competitive Landscape: {company}

**Date:** {today} | **Model:** {model}
**Competitors analyzed:** {comp_list}

---

"""
    report = header + text

    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    filename = reports_dir / f"{safe_name}_landscape_{today}.md"
    filename.write_text(report, encoding="utf-8")

    print(f"\n{'='*60}")
    print(f"  Landscape analysis complete! Report: {filename}")
    print(f"{'='*60}")

    save_to_dossier(company, "landscape", report_file=str(filename), report_text=report, model_used=model)
    return str(filename)
