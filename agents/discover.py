"""Agent: Lead Discovery — discover prospective companies in a niche/vertical.

Generates targeted search queries from structured niche context (vertical, size,
geography, business model, qualifiers) to surface relevant companies via web,
news, and Reddit search.  An LLM extracts and filters company data from the
combined search results.
"""

from datetime import datetime
from pathlib import Path

from agents.llm import generate_json, unique_report_path, FAST_CHAIN
from scraper.web_search import search_web, search_news, search_reddit, format_search_results, dedup_results
from scraper.google_news import search_google_news
from prompts.discover import build_discovery_prompt, build_similar_discovery_prompt, build_query_generation_prompt
from db import get_connection, get_or_create_dossier
from agents.compare import _profile_lookup


_SOURCE_LABELS = {"web": "Web Search", "news": "News", "reddit": "Reddit", "gnews": "Google News"}


def _result_items(results):
    """Extract lightweight metadata from search results for execution log auditability."""
    items = []
    for r in results:
        item = {"title": (r.get("title") or "")[:120]}
        item["url"] = r.get("href") or r.get("url") or ""
        if r.get("source"):
            item["source"] = r["source"]
        if r.get("date"):
            item["date"] = str(r["date"])[:20]
        items.append(item)
    return items


import re

# Geography patterns for auto-extraction from free-text niche input
_GEO_PATTERNS = [
    (r'\bbased in (?:the )?(.+?)(?:\s*$|\s+(?:that|who|which|and|with))', None),
    (r'\bin (?:the )?(US|USA|United States|UK|United Kingdom|Canada|Europe|EU|APAC|Asia|India|Germany|France|Japan|Australia|Brazil|LATAM|EMEA)\b', None),
    (r'\b(US|USA|UK|EU)\b[- ]based\b', None),
    (r'\b(American|British|Canadian|European|Indian|German|French|Japanese|Australian|Korean|Chinese)\s+(?:companies|brands|makers|firms)', {
        "American": "US", "British": "UK", "Canadian": "Canada", "European": "Europe",
        "Indian": "India", "German": "Germany", "French": "France", "Japanese": "Japan",
        "Australian": "Australia", "Korean": "South Korea", "Chinese": "China",
    }),
]


def _extract_geography(niche):
    """Extract geography from free-text niche string. Returns geo string or None."""
    text = niche.strip()
    for pattern, mapping in _GEO_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            raw = m.group(1).strip().rstrip('.,;')
            if mapping:
                return mapping.get(raw, raw)
            # Normalize common abbreviations
            norm = {"us": "US", "usa": "US", "united states": "US", "uk": "UK",
                    "united kingdom": "UK", "eu": "Europe"}
            return norm.get(raw.lower(), raw)
    return None


# ---------------------------------------------------------------------------
# Query generation — LLM-powered with template fallback
# ---------------------------------------------------------------------------

_VALID_SOURCES = {"web", "news", "gnews", "reddit"}


def _build_queries_llm(niche, context):
    """Use a fast LLM to generate targeted search queries from the niche description.

    Returns list of (source, query) tuples, or None if the LLM call fails.
    """
    prompt = build_query_generation_prompt(niche, context)
    try:
        result = generate_json(prompt, timeout=20, chain=FAST_CHAIN)
    except Exception as e:
        print(f"[discover] LLM query generation failed: {e}")
        return None

    if result is None:
        return None

    # Normalize response — LLMs may return either:
    #   1. Flat array: [{"source": "web", "query": "..."}, ...]
    #   2. Grouped dict: {"web": [{"query": "..."}, ...], "news": [...], ...}
    queries = []
    if isinstance(result, dict):
        for source, items in result.items():
            if source not in _VALID_SOURCES:
                continue
            if not isinstance(items, list):
                continue
            for item in items:
                query = item.get("query", "").strip() if isinstance(item, dict) else str(item).strip()
                if query and len(query) < 150:
                    queries.append((source, query))
    elif isinstance(result, list):
        for item in result:
            if not isinstance(item, dict):
                continue
            source = item.get("source", "web")
            query = item.get("query", "").strip()
            if source not in _VALID_SOURCES:
                source = "web"
            if query and len(query) < 150:
                queries.append((source, query))

    if len(queries) < 4:
        print(f"[discover] LLM query generation produced too few valid queries ({len(queries)})")
        return None

    print(f"[discover] LLM generated {len(queries)} targeted queries")
    return queries


def _build_queries_template(niche, context):
    """Template-based query generation (fallback when LLM is unavailable)."""
    vertical = context.get("vertical", "").strip()
    size = context.get("company_size", "").strip()
    geo = context.get("geography", "").strip()
    model = context.get("business_model", "").strip()
    qualifiers = context.get("qualifiers", "").strip()

    core = vertical or niche

    size_terms = {
        "Startup": ["startup", "seed funded", "early stage"],
        "SMB": ["small business", "SMB", "growing"],
        "Midmarket": ["midmarket", "mid-market", "fast growing"],
        "Enterprise": ["enterprise", "large"],
    }
    size_kws = size_terms.get(size, [])
    geo_q = f" in {geo}" if geo and geo not in ("Global", "") else ""

    queries = []
    queries.append(("web", f"top {core} companies{geo_q} 2026"))
    queries.append(("web", f"fastest growing {core} companies{geo_q}"))

    if size_kws:
        queries.append(("web", f"{size_kws[0]} {core} companies{geo_q}"))
    else:
        queries.append(("web", f"best {core} companies brands{geo_q}"))

    if size in ("Startup", "SMB"):
        queries.append(("web", f"{core} companies funding raised{geo_q} 2025 2026"))
        queries.append(("web", f"crunchbase {core}{geo_q} startups"))
    elif size == "Midmarket":
        queries.append(("web", f"{core} series B series C companies{geo_q}"))
    else:
        queries.append(("web", f"{core} emerging brands to watch{geo_q}"))

    if model == "B2B":
        queries.append(("web", f"B2B {core} vendors platforms{geo_q}"))
    elif model == "B2C":
        queries.append(("web", f"DTC {core} brands consumers love{geo_q}"))
    elif model == "B2B/B2C":
        queries.append(("web", f"{core} brands platforms{geo_q}"))

    if qualifiers:
        queries.append(("web", f"{core} {qualifiers}{geo_q}"))

    queries.append(("web", f"list of {core} companies{geo_q}"))
    queries.append(("news", f"{core} companies{geo_q} funding growth 2026"))
    queries.append(("news", f"{core}{geo_q} brands expansion"))
    queries.append(("gnews", f"{core} companies{geo_q} funding growth 2026"))
    queries.append(("gnews", f"{core}{geo_q} acquisition expansion"))
    queries.append(("reddit", f"{core} companies recommendations{geo_q}"))
    if model == "B2C":
        queries.append(("reddit", f"best {core} brands favorites"))

    return queries


def _build_queries(niche, context):
    """Generate search queries — LLM-powered with template fallback."""
    llm_queries = _build_queries_llm(niche, context)
    if llm_queries:
        return llm_queries
    print("[discover] Falling back to template-based queries")
    return _build_queries_template(niche, context)


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

    # Auto-extract geography from niche string if not in context
    if not context.get("geography"):
        _geo = _extract_geography(niche)
        if _geo:
            context = dict(context)  # don't mutate original
            context["geography"] = _geo
            print(f"[discover] Auto-detected geography from niche: {_geo}")

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
        "gnews": len([q for q in queries if q[0] == "gnews"]),
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
        elif source == "gnews":
            results = search_google_news(query, max_results=5, days_back=30)
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
            "results": _result_items(results),
        })

    if not all_results:
        print("[discover] No search results found. Try a different niche description.")
        return []

    # Deduplicate (normalized title matching, keeps highest-quality source)
    unique = dedup_results(all_results)

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
    prompt = build_discovery_prompt(niche, search_text, context=context, top_n=top_n)
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
        "company_details": [
            {k: v for k, v in c.items() if k != "body" and v}
            for c in companies
        ],
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
    safe_niche = re.sub(r'[^\w\-]', '_', niche.lower())[:40].strip('_')

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


# ---------------------------------------------------------------------------
# Similar-company query generation
# ---------------------------------------------------------------------------

def _build_similar_queries(seed_company, profile):
    """Generate targeted queries to find companies similar to *seed_company*.

    Uses the profile (from ``_profile_lookup``) to build context-aware queries
    so results stay in the right industry/scale/client-type lane.
    """
    queries = []

    # Direct competitor queries (always)
    queries.append(("web", f"{seed_company} competitors alternatives"))
    queries.append(("web", f"companies like {seed_company}"))
    queries.append(("web", f"{seed_company} top competitors 2026"))

    # Profile-aware queries
    if profile:
        industry = profile.get("industry", "")
        services = profile.get("services", [])
        scale = profile.get("scale", "")
        client_type = profile.get("client_type", "")

        if industry:
            queries.append(("web", f"top {industry} companies like {seed_company}"))
            queries.append(("web", f"{industry} competitors to {seed_company}"))
        if services:
            top_service = services[0] if isinstance(services, list) and services else ""
            if top_service:
                queries.append(("web", f"best {top_service} companies alternatives to {seed_company}"))
        if client_type and industry:
            queries.append(("web", f"{client_type} {industry} brands like {seed_company}"))
        if scale:
            queries.append(("web", f"{scale} companies similar to {seed_company}"))
    else:
        queries.append(("web", f"best alternatives to {seed_company}"))
        queries.append(("web", f"{seed_company} similar companies"))

    # News & Google News (recent coverage of competitors)
    queries.append(("news", f"{seed_company} competitors 2026"))
    queries.append(("gnews", f"companies competing with {seed_company}"))

    # Reddit (community recommendations)
    queries.append(("reddit", f"alternatives to {seed_company} recommendations"))

    return queries


# ---------------------------------------------------------------------------
# Company-anchored discovery ("Find Similar")
# ---------------------------------------------------------------------------

def discover_similar(seed_company, top_n=10, db_path="intel.db", progress_cb=None):
    """Discover companies similar to *seed_company* via profile-aware search.

    Uses ``_profile_lookup`` from the landscape analysis module to understand
    what the seed company does, then builds targeted queries to find peers.
    Returns structured results in the same format as ``discover_prospects()``.

    Args:
        seed_company: Company name to anchor the search on
        top_n: Max companies to return
        db_path: SQLite database path
        progress_cb: Optional callback(event_type, event_data) for streaming progress

    Returns list of dicts: [{name, website, description, estimated_size,
                             why_included, evidence}, ...]
    Also creates dossier stubs for each discovered company.
    """
    _cb = progress_cb or (lambda *a: None)

    print(f"\n[discover_similar] Finding companies similar to: {seed_company}")

    # Phase 1 — profile lookup
    _cb("discovery_plan", {
        "total_queries": 0,
        "mode": "similar",
        "seed": seed_company,
        "web": 0, "news": 0, "gnews": 0, "reddit": 0,
    })

    _cb("extracting", {"text": f"Looking up profile for {seed_company}..."})
    profile = _profile_lookup(seed_company)
    if profile:
        print(f"[discover_similar] Profile: {profile.get('industry', '?')} | {profile.get('scale', '?')}")
    _cb("seed_profile", {
        "company": seed_company,
        "profile": profile,
    })

    # Phase 2 — build queries
    queries = _build_similar_queries(seed_company, profile)
    total_queries = len(queries)
    print(f"[discover_similar] Generated {total_queries} targeted queries")

    _cb("discovery_plan", {
        "total_queries": total_queries,
        "mode": "similar",
        "seed": seed_company,
        "web": len([q for q in queries if q[0] == "web"]),
        "news": len([q for q in queries if q[0] == "news"]),
        "gnews": len([q for q in queries if q[0] == "gnews"]),
        "reddit": len([q for q in queries if q[0] == "reddit"]),
    })

    # Phase 3 — execute searches (same pattern as discover_prospects)
    all_results = []
    for i, (source, query) in enumerate(queries):
        label = _SOURCE_LABELS.get(source, source)
        print(f"[discover_similar]   [{source}] {query}")
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
        elif source == "gnews":
            results = search_google_news(query, max_results=5, days_back=30)
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
            "results": _result_items(results),
        })

    if not all_results:
        print("[discover_similar] No search results found.")
        return []

    unique = dedup_results(all_results)
    print(f"[discover_similar] {len(unique)} unique results from {len(all_results)} total")
    _cb("search_complete", {
        "total_results": len(all_results),
        "unique_results": len(unique),
    })

    # Phase 4 — LLM extraction
    _cb("extracting", {
        "text": f"Finding companies similar to {seed_company}...",
    })

    search_text = format_search_results(unique)
    prompt = build_similar_discovery_prompt(seed_company, search_text, profile=profile, top_n=top_n)
    companies = generate_json(prompt, timeout=60)

    if not isinstance(companies, list):
        print("[discover_similar] LLM did not return a valid list. Retrying...")
        _cb("extracting", {"text": "Retrying extraction..."})
        companies = generate_json(prompt, timeout=60)
        if not isinstance(companies, list):
            print("[discover_similar] Failed to extract companies from search results.")
            return []

    # Filter out seed company and limit
    companies = [c for c in companies if isinstance(c, dict) and c.get("name")]
    companies = [c for c in companies if c["name"].strip().lower() != seed_company.strip().lower()]
    companies = companies[:top_n]

    print(f"[discover_similar] Found {len(companies)} similar companies")
    _cb("extracted", {
        "count": len(companies),
        "companies": [c.get("name", "?") for c in companies],
        "company_details": [
            {k: v for k, v in c.items() if k != "body" and v}
            for c in companies
        ],
    })

    # Create dossier stubs
    conn = get_connection(db_path)
    for company in companies:
        name = company["name"]
        desc = company.get("description", "")
        get_or_create_dossier(conn, name, description=desc)
        print(f"[discover_similar]   \u2713 {name} \u2014 {company.get('estimated_size', '?')}")
    conn.close()

    # Save discovery report
    today = datetime.now().strftime("%Y-%m-%d")
    safe_seed = re.sub(r'[^\w\-]', '_', seed_company.lower())[:40].strip('_')

    report_lines = [
        f"# Similar Companies: {seed_company}",
        f"",
        f"**Date:** {today}",
        f"**Anchored on:** {seed_company}",
        f"**Profile:** {profile or 'N/A'}",
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
    filename = unique_report_path(reports_dir, f"similar_to_{safe_seed}_{today}.md")
    filename.write_text(report, encoding="utf-8")
    print(f"[discover_similar] Report saved to {filename}")

    return companies
