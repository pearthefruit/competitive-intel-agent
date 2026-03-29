"""Agent: Lead Discovery — discover prospective companies in a niche/vertical."""

from datetime import datetime
from pathlib import Path

from agents.llm import generate_json, unique_report_path
from scraper.web_search import search_web, search_news, search_reddit, format_search_results
from prompts.ua_discover import build_discovery_prompt
from db import get_connection, get_or_create_dossier


def discover_prospects(niche, top_n=15, db_path="intel.db"):
    """Discover companies in a niche via multi-source web search.

    Returns list of dicts: [{name, website, description, estimated_size, why_included}, ...]
    Also creates dossier stubs for each discovered company.
    """
    print(f"\n[discover] Searching for companies in: {niche}")

    queries = [
        f"top {niche} 2026",
        f"fastest growing {niche}",
        f"best {niche} companies brands",
        f"{niche} emerging brands to watch",
    ]

    all_results = []
    for query in queries:
        print(f"[discover]   Searching: {query}")
        results = search_web(query, max_results=8, fetch_content=True)
        all_results.extend(results)

    # News — recent brand coverage
    print(f"[discover]   Searching news...")
    news = search_news(f"{niche} brands companies", max_results=5, fetch_content=True)
    all_results.extend(news)

    # Reddit — community mentions
    print(f"[discover]   Searching Reddit...")
    reddit = search_reddit(f"{niche} recommendations favorites", max_results=5)
    all_results.extend(reddit)

    if not all_results:
        print("[discover] No search results found. Try a different niche description.")
        return []

    # Deduplicate by title
    seen = set()
    unique = []
    for r in all_results:
        title = r.get("title", "")
        if title and title not in seen:
            seen.add(title)
            unique.append(r)

    print(f"[discover] {len(unique)} unique results from {len(all_results)} total")

    search_text = format_search_results(unique)
    prompt = build_discovery_prompt(niche, search_text)
    companies = generate_json(prompt, timeout=60)

    if not isinstance(companies, list):
        print("[discover] LLM did not return a valid list. Retrying...")
        companies = generate_json(prompt, timeout=60)
        if not isinstance(companies, list):
            print("[discover] Failed to extract companies from search results.")
            return []

    # Filter and limit
    companies = [c for c in companies if isinstance(c, dict) and c.get("name")]
    companies = companies[:top_n]

    print(f"[discover] Found {len(companies)} companies")

    # Create dossier stubs
    conn = get_connection(db_path)
    for company in companies:
        name = company["name"]
        desc = company.get("description", "")
        get_or_create_dossier(conn, name, description=desc)
        print(f"[discover]   \u2713 {name} \u2014 {company.get('estimated_size', '?')}")
    conn.close()

    # Save discovery report
    today = datetime.now().strftime("%Y-%m-%d")
    safe_niche = niche.lower().replace(" ", "_").replace("/", "_")[:40]

    report_lines = [
        f"# Lead Discovery: {niche}",
        f"",
        f"**Date:** {today}",
        f"**Sources:** Web Search, News, Reddit",
        f"**Companies found:** {len(companies)}",
        f"",
        f"---",
        f"",
        f"| # | Company | Size | Description |",
        f"|---|---------|------|-------------|",
    ]
    for i, c in enumerate(companies, 1):
        name = c.get("name", "?")
        size = c.get("estimated_size", "?")
        desc = c.get("description", "")
        website = c.get("website", "")
        name_cell = f"[{name}]({website})" if website else name
        report_lines.append(f"| {i} | {name_cell} | {size} | {desc} |")

    report_lines.extend([f"", f"## Why These Companies", f""])
    for c in companies:
        why = c.get("why_included", "")
        if why:
            report_lines.append(f"- **{c['name']}**: {why}")

    report = "\n".join(report_lines)
    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    filename = unique_report_path(reports_dir, f"discovery_{safe_niche}_{today}.md")
    filename.write_text(report, encoding="utf-8")
    print(f"[discover] Report saved to {filename}")

    return companies
