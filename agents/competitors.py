"""Agent: Competitor Mapping — discover and map competitive landscape via web search."""

from datetime import datetime
from pathlib import Path

from agents.llm import generate_text, save_to_dossier, get_temporal_context, unique_report_path
from scraper.web_search import search_web, search_news, search_reddit, search_youtube, format_search_results, dedup_results
from scraper.google_news import search_google_news
from scraper.hackernews import search_hackernews
from prompts.competitors import build_competitor_prompt


def _result_titles(results, max_items=5):
    """Extract titles from search results for progress detail."""
    titles = [r.get('title', r.get('href', ''))[:100] for r in results[:max_items]]
    return '\n'.join(f'• {t}' for t in titles) if titles else ''


def competitor_analysis(company, progress_cb=None):
    """Map the competitive landscape for a company. Returns report path or None."""
    _cb = progress_cb or (lambda *a: None)
    print(f"\n[competitors] Mapping competitive landscape for {company}...")

    # --- Phase 1: Web Search ---
    _cb('analysis_start', {'analysis_type': 'web_search', 'label': 'Web Search'})

    queries = [
        f"{company} competitors",
        f"{company} alternatives",
        f"{company} vs",
    ]

    all_results = []
    for i, query in enumerate(queries):
        _cb('source_start', {'source': f'web_{i}', 'label': f'"{query}"', 'detail': f'Query {i+1} of {len(queries)}'})
        results = search_web(query, max_results=5)
        all_results.extend(results)
        _cb('source_done', {'source': f'web_{i}', 'status': 'done' if results else 'skipped',
             'summary': f'{len(results)} results', 'detail': _result_titles(results)})

    web_count = len(all_results)

    if web_count < 3:
        print(f"[competitors] Only {web_count} web results — company may operate in a niche market, be a subsidiary, or use a name that's hard to search for")
        print(f"[competitors] Expanding search to Reddit, YouTube, and Hacker News for community-sourced competitive data...")

    _cb('analysis_done', {'analysis_type': 'web_search'})

    # --- Phase 2: Deep Sources ---
    _cb('analysis_start', {'analysis_type': 'deep_sources', 'label': 'Deep Sources'})

    _cb('source_start', {'source': 'ddg_news', 'label': 'DDG News', 'detail': f'"{company} competition market"'})
    news = search_news(f"{company} competition market", max_results=3)
    all_results.extend(news)
    _cb('source_done', {'source': 'ddg_news', 'status': 'done' if news else 'skipped',
         'summary': f'{len(news)} results', 'detail': _result_titles(news)})

    print("[competitors] Searching Google News for competitive news...")
    _cb('source_start', {'source': 'google_news', 'label': 'Google News', 'detail': f'"{company} competition market share"'})
    gnews = search_google_news(f"{company} competition market share", max_results=5, days_back=30)
    all_results.extend(gnews)
    _cb('source_done', {'source': 'google_news', 'status': 'done' if gnews else 'skipped',
         'summary': f'{len(gnews)} results', 'detail': _result_titles(gnews)})

    print("[competitors] Searching Reddit for community competitor mentions...")
    _cb('source_start', {'source': 'reddit', 'label': 'Reddit', 'detail': f'"{company} vs alternatives competitors"'})
    reddit = search_reddit(f"{company} vs alternatives competitors", max_results=3)
    all_results.extend(reddit)
    _cb('source_done', {'source': 'reddit', 'status': 'done' if reddit else 'skipped',
         'summary': f'{len(reddit)} results', 'detail': _result_titles(reddit)})

    print("[competitors] Searching YouTube for analyst comparisons...")
    _cb('source_start', {'source': 'youtube', 'label': 'YouTube', 'detail': f'"{company} vs competitors comparison"'})
    yt = search_youtube(f"{company} vs competitors comparison", max_results=2)
    all_results.extend(yt)
    _cb('source_done', {'source': 'youtube', 'status': 'done' if yt else 'skipped',
         'summary': f'{len(yt)} results', 'detail': _result_titles(yt)})

    print("[competitors] Searching Hacker News for tech community perspective...")
    _cb('source_start', {'source': 'hackernews', 'label': 'Hacker News', 'detail': f'"{company} vs alternatives"'})
    hn = search_hackernews(f"{company} vs alternatives", max_results=3)
    all_results.extend(hn)
    _cb('source_done', {'source': 'hackernews', 'status': 'done' if hn else 'skipped',
         'summary': f'{len(hn)} results', 'detail': _result_titles(hn)})

    _cb('analysis_done', {'analysis_type': 'deep_sources'})

    if not all_results:
        print("[competitors] No competitive data found from any source — company may be too niche or newly launched")
        print("[competitors] Try searching with the company's product category instead of its name (e.g., 'CRM software competitors' instead of 'Acme competitors')")
        return None

    # Deduplicate (normalized title matching, keeps highest-quality source)
    unique = dedup_results(all_results)
    search_text = format_search_results(unique)

    # --- Phase 3: Report Generation ---
    _cb('analysis_start', {'analysis_type': 'report', 'label': 'Report Generation'})

    prompt = build_competitor_prompt(company, search_text)
    prompt += get_temporal_context(company, "competitors")

    print("[competitors] Generating report...")
    _cb('source_start', {'source': 'llm', 'label': 'LLM Synthesis', 'detail': f'Analyzing {len(unique)} unique sources'})
    text, model = generate_text(prompt)
    _cb('source_done', {'source': 'llm', 'status': 'done', 'summary': f'Generated via {model}'})

    # Save report
    today = datetime.now().strftime("%Y-%m-%d")
    safe_name = company.lower().replace(" ", "_").replace(".", "_")

    header = f"""# Competitor Analysis: {company}

**Date:** {today}
**Source:** Web Search | **Model:** {model}

---

"""
    report = header + text

    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    filename = unique_report_path(reports_dir, f"{safe_name}_competitors_{today}.md")
    filename.write_text(report, encoding="utf-8")

    print(f"[competitors] Report saved to {filename}")
    _cb('report_saved', {'path': str(filename)})
    _cb('analysis_done', {'analysis_type': 'report'})

    save_to_dossier(company, "competitors", report_file=str(filename), report_text=report, model_used=model, progress_cb=_cb)
    return str(filename)
