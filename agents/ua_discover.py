"""Agent: Lead Discovery — discover prospective companies in a niche/vertical.

Generates targeted search queries from structured niche context (vertical, size,
geography, business model, qualifiers) to surface relevant companies via web,
news, and Reddit search.  An LLM extracts and filters company data from the
combined search results.
"""

from datetime import datetime
from pathlib import Path

from agents.llm import generate_json, unique_report_path
from scraper.web_search import search_web, search_news, search_reddit, format_search_results
from prompts.ua_discover import build_discovery_prompt
from db import get_connection, get_or_create_dossier


_SOURCE_LABELS = {"web": "Web Search", "news": "News", "reddit": "Reddit"}


# ---------------------------------------------------------------------------
# Query generation — build targeted queries from structured context
# ---------------------------------------------------------------------------

def _build_queries(niche, context):
    """Generate search queries tailored to the niche and structured context.

    Uses vertical, size, geography, business_model, and qualifiers to craft
    queries that surface the right kinds of companies rather than blasting
    the whole concatenated string at DuckDuckGo.
    """
    vertical = context.get("vertical", "").strip()
    size = context.get("company_size", "").strip()
    geo = context.get("geography", "").strip()
    model = context.get("business_model", "").strip()
    qualifiers = context.get("qualifiers", "").strip()

    # Core search term — prefer the vertical alone (cleaner queries)
    core = vertical or niche

    # Size keywords for search
    size_terms = {
        "Startup": ["startup", "seed funded", "early stage"],
        "SMB": ["small business", "SMB", "growing"],
        "Midmarket": ["midmarket", "mid-market", "fast growing"],
        "Enterprise": ["enterprise", "large"],
    }
    size_kws = size_terms.get(size, [])

    # Geography qualifier
    geo_q = f" in {geo}" if geo and geo not in ("Global", "") else ""

    queries = []

    # --- Web search queries (targeted by dimension) ---

    # 1. Core vertical discovery
    queries.append(("web", f"top {core} companies{geo_q} 2026"))
    queries.append(("web", f"fastest growing {core} companies{geo_q}"))

    # 2. Size-aware queries
    if size_kws:
        queries.append(("web", f"{size_kws[0]} {core} companies{geo_q}"))
    else:
        queries.append(("web", f"best {core} companies brands{geo_q}"))

    # 3. Funding / investment signals (great for finding real companies)
    if size in ("Startup", "SMB"):
        queries.append(("web", f"{core} companies funding raised{geo_q} 2025 2026"))
        queries.append(("web", f"crunchbase {core}{geo_q} startups"))
    elif size == "Midmarket":
        queries.append(("web", f"{core} series B series C companies{geo_q}"))
    else:
        queries.append(("web", f"{core} emerging brands to watch{geo_q}"))

    # 4. Business model specific
    if model == "B2B":
        queries.append(("web", f"B2B {core} vendors platforms{geo_q}"))
    elif model == "B2C":
        queries.append(("web", f"DTC {core} brands consumers love{geo_q}"))
    elif model == "B2B/B2C":
        queries.append(("web", f"{core} brands platforms{geo_q}"))

    # 5. Qualifier-driven queries (user-specified signals like "VC-backed", "DTC only")
    if qualifiers:
        queries.append(("web", f"{core} {qualifiers}{geo_q}"))

    # 6. Industry lists / directories
    queries.append(("web", f"list of {core} companies{geo_q}"))

    # --- News queries (recent coverage = active companies) ---
    queries.append(("news", f"{core} companies{geo_q} funding growth 2026"))
    queries.append(("news", f"{core}{geo_q} brands expansion"))

    # --- Reddit queries (community signals) ---
    queries.append(("reddit", f"{core} companies recommendations{geo_q}"))
    if model == "B2C":
        queries.append(("reddit", f"best {core} brands favorites"))

    return queries


# ---------------------------------------------------------------------------
# Main discovery function
# ---------------------------------------------------------------------------

def discover_prospects(niche, top_n=15, db_path="intel.db", context=None, progress_cb=None):
    """Discover companies in a niche via multi-source web search.

    Args:
        niche: Free-text niche string (e.g. "SMB B2B skincare US")
        top_n: Max companies to return
        db_path: SQLite database path
        context: Optional structured fields from Niche Builder:
            {vertical, company_size, geography, business_model, qualifiers}
        progress_cb: Optional callback(event_type, event_data) for streaming progress

    Returns list of dicts: [{name, website, description, estimated_size, why_included}, ...]
    Also creates dossier stubs for each discovered company.
    """
    context = context or {}
    _cb = progress_cb or (lambda *a: None)

    print(f"\n[discover] Searching for companies in: {niche}")
    if context:
        print(f"[discover] Context: {context}")

    queries = _build_queries(niche, context)
    total_queries = len(queries)
    print(f"[discover] Generated {total_queries} targeted queries")

    _cb("discovery_plan", {
        "total_queries": total_queries,
        "web": len([q for q in queries if q[0] == "web"]),
        "news": len([q for q in queries if q[0] == "news"]),
        "reddit": len([q for q in queries if q[0] == "reddit"]),
    })

    all_results = []
    for i, (source, query) in enumerate(queries):
        label = _SOURCE_LABELS.get(source, source)
        print(f"[discover]   [{source}] {query}")
        _cb("search_start", {
            "index": i + 1,
            "total": total_queries,
            "source": source,
            "source_label": label,
            "query": query,
        })

        if source == "web":
            results = search_web(query, max_results=8, fetch_content=True)
        elif source == "news":
            results = search_news(query, max_results=5, fetch_content=True)
        elif source == "reddit":
            results = search_reddit(query, max_results=5)
        else:
            continue

        all_results.extend(results)
        _cb("search_done", {
            "index": i + 1,
            "total": total_queries,
            "source": source,
            "source_label": label,
            "query": query,
            "results_count": len(results),
            "cumulative_count": len(all_results),
        })

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
    _cb("search_complete", {
        "total_results": len(all_results),
        "unique_results": len(unique),
    })

    # LLM extraction
    _cb("extracting", {
        "text": f"Analyzing {len(unique)} search results with AI...",
    })

    search_text = format_search_results(unique)
    prompt = build_discovery_prompt(niche, search_text, context=context)
    companies = generate_json(prompt, timeout=60)

    if not isinstance(companies, list):
        print("[discover] LLM did not return a valid list. Retrying...")
        _cb("extracting", {"text": "Retrying extraction..."})
        companies = generate_json(prompt, timeout=60)
        if not isinstance(companies, list):
            print("[discover] Failed to extract companies from search results.")
            return []

    # Filter and limit
    companies = [c for c in companies if isinstance(c, dict) and c.get("name")]
    companies = companies[:top_n]

    print(f"[discover] Found {len(companies)} companies")
    _cb("extracted", {
        "count": len(companies),
        "companies": [c.get("name", "?") for c in companies],
    })

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
        f"**Sources:** Web Search ({len([q for q in queries if q[0] == 'web'])} queries), "
        f"News ({len([q for q in queries if q[0] == 'news'])} queries), "
        f"Reddit ({len([q for q in queries if q[0] == 'reddit'])} queries)",
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
