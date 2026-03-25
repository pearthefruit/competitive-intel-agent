"""Agent: Competitor Mapping — discover and map competitive landscape via web search."""

from datetime import datetime
from pathlib import Path

from agents.llm import generate_text, save_to_dossier, get_temporal_context, unique_report_path
from scraper.web_search import search_web, search_news, search_reddit, search_youtube, format_search_results
from scraper.hackernews import search_hackernews
from prompts.competitors import build_competitor_prompt


def competitor_analysis(company):
    """Map the competitive landscape for a company. Returns report path or None."""
    print(f"\n[competitors] Mapping competitive landscape for {company}...")

    # Multiple targeted searches
    queries = [
        f"{company} competitors",
        f"{company} alternatives",
        f"{company} vs",
    ]

    all_results = []
    for query in queries:
        results = search_web(query, max_results=5)
        all_results.extend(results)

    web_count = len(all_results)
    if web_count < 3:
        print(f"[competitors] Only {web_count} web results — company may operate in a niche market, be a subsidiary, or use a name that's hard to search for")
        print(f"[competitors] Expanding search to Reddit, YouTube, and Hacker News for community-sourced competitive data...")

    # Also check news
    news = search_news(f"{company} competition market", max_results=3)
    all_results.extend(news)

    # Reddit discussions (often mention competitors by name)
    print("[competitors] Searching Reddit for community competitor mentions...")
    reddit = search_reddit(f"{company} vs alternatives competitors", max_results=3)
    all_results.extend(reddit)

    # YouTube (analyst videos, comparisons)
    print("[competitors] Searching YouTube for analyst comparisons...")
    yt = search_youtube(f"{company} vs competitors comparison", max_results=2)
    all_results.extend(yt)

    # Hacker News (tech community perspective)
    print("[competitors] Searching Hacker News for tech community perspective...")
    hn = search_hackernews(f"{company} vs alternatives", max_results=3)
    all_results.extend(hn)

    if not all_results:
        print("[competitors] No competitive data found from any source — company may be too niche or newly launched")
        print("[competitors] Try searching with the company's product category instead of its name (e.g., 'CRM software competitors' instead of 'Acme competitors')")
        return None

    # Deduplicate
    seen = set()
    unique = []
    for r in all_results:
        title = r.get("title", "")
        if title not in seen:
            seen.add(title)
            unique.append(r)

    search_text = format_search_results(unique)

    # Generate report
    prompt = build_competitor_prompt(company, search_text)
    prompt += get_temporal_context(company, "competitors")

    print("[competitors] Generating report...")
    text, model = generate_text(prompt)

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
    save_to_dossier(company, "competitors", report_file=str(filename), report_text=report, model_used=model)
    return str(filename)
