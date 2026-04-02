"""Agent: Executive Hiring Signals — detect C-suite and VP-level hires as indicators of organizational commitment.

Combines multiple data sources:
1. SEC 8-K filings (Item 5.02 — officer/director changes) for public companies
2. Classified executive job openings from ATS boards (VP, C-Suite seniority)
3. Google News, DuckDuckGo, Hacker News for appointment announcements
"""

from datetime import datetime
from pathlib import Path

from agents.llm import generate_text, save_to_dossier, get_temporal_context, unique_report_path
from scraper.web_search import search_web, search_news, format_search_results, dedup_results
from scraper.google_news import search_google_news
from scraper.hackernews import search_hackernews
from prompts.executive_signals import build_executive_signals_prompt


EXEC_SENIORITIES = ("VP", "C-Suite", "Director")
EXEC_DEPT = "Executive"

# Keywords that flag an 8-K filing as potentially containing executive changes
_8K_EXEC_KEYWORDS = (
    "5.02", "officer", "director", "appointed", "resigned",
    "retirement", "departure", "principal", "executive",
)


def _result_detail(results, max_items=10):
    """Format search results as detail lines for progress events."""
    lines = []
    for r in results[:max_items]:
        title = r.get("title", "")[:80]
        url = r.get("href", r.get("url", ""))
        if title:
            lines.append(f"• {title}" + (f"  ({url})" if url else ""))
    return "\n".join(lines) if lines else ""


def _get_executive_openings(company, db_path):
    """Query classified jobs for VP/C-Suite/Director openings.

    Returns formatted text section or None.
    """
    try:
        from db import get_connection, get_company_id, get_all_classified_jobs

        conn = get_connection(db_path)
        company_id = get_company_id(conn, company)
        if not company_id:
            conn.close()
            return None

        jobs = get_all_classified_jobs(conn, company_id)
        conn.close()

        exec_jobs = [
            j for j in jobs
            if (j.get("seniority_level") in EXEC_SENIORITIES
                or j.get("department_category") == EXEC_DEPT)
        ]

        if not exec_jobs:
            return None

        lines = [f"### Open Executive Positions ({len(exec_jobs)} roles)"]
        for j in exec_jobs[:20]:
            title = j.get("title", "Unknown")
            dept = j.get("department_category", "")
            seniority = j.get("seniority_level", "")
            location = j.get("location", "")
            growth = j.get("growth_signal", "")
            parts = [f"**{title}**"]
            if dept:
                parts.append(f"Dept: {dept}")
            if seniority:
                parts.append(f"Level: {seniority}")
            if location:
                parts.append(f"Location: {location}")
            if growth:
                parts.append(f"Signal: {growth}")
            lines.append("  - " + " | ".join(parts))

        return "\n".join(lines)

    except Exception as e:
        print(f"[exec-signals] Warning: Could not load executive openings: {e}")
        return None


def _collect_sec_8k(company, _cb):
    """Collect SEC 8-K filings related to executive changes. Returns formatted text or None."""
    _cb("source_start", {"source": "sec_8k", "label": "SEC 8-K Filings", "detail": "Looking up executive change disclosures"})

    try:
        from scraper.sec_edgar import lookup_cik, get_8k_filings, fetch_8k_content

        cik_result = lookup_cik(company)
        if not cik_result or isinstance(cik_result, list):
            print(f"[exec-signals] No SEC CIK found for '{company}' — skipping 8-K filings (company may be private)")
            _cb("source_done", {"source": "sec_8k", "status": "skipped", "summary": f"No SEC match for '{company}'"})
            return None

        cik = cik_result["cik"]
        filings = get_8k_filings(cik, max_filings=20)
        if not filings:
            _cb("source_done", {"source": "sec_8k", "status": "skipped", "summary": "No 8-K filings found"})
            return None

        # Filter for filings likely to contain executive changes
        exec_filings = []
        for f in filings:
            desc = (f.get("description") or "").lower()
            if any(kw in desc for kw in _8K_EXEC_KEYWORDS):
                exec_filings.append(f)

        if not exec_filings:
            # Still report all 8-K filings as context, but note no explicit exec filings
            print(f"[exec-signals] {len(filings)} 8-K filings found, but none explicitly mention executive changes")
            _cb("source_done", {"source": "sec_8k", "status": "done", "summary": f"{len(filings)} 8-K filings (none explicitly executive-related)"})
            # Return basic listing so LLM can still look for signals
            lines = [f"### SEC 8-K Filings ({len(filings)} recent filings, none explicitly tagged as executive changes)"]
            for f in filings[:10]:
                lines.append(f"  - {f['date']}: {f.get('description', 'No description')} — {f.get('url', '')}")
            return "\n".join(lines)

        # Fetch content for executive-related filings (up to 5 to avoid too many requests)
        print(f"[exec-signals] Found {len(exec_filings)} executive-related 8-K filings, fetching content...")
        lines = [f"### SEC 8-K Executive Filings ({len(exec_filings)} filings)"]
        for f in exec_filings[:5]:
            content = fetch_8k_content(f.get("url"), max_chars=3000)
            lines.append(f"\n**{f['date']}: {f.get('description', '8-K Filing')}**")
            if f.get("url"):
                lines.append(f"URL: {f['url']}")
            if content:
                lines.append(content)
            else:
                lines.append("(Could not fetch filing content)")

        detail = "\n".join(f"• {f['date']}: {f.get('description', '')}" for f in exec_filings[:10])
        _cb("source_done", {"source": "sec_8k", "status": "done", "summary": f"{len(exec_filings)} executive-related filings", "detail": detail})
        return "\n".join(lines)

    except Exception as e:
        print(f"[exec-signals] SEC 8-K collection failed: {e}")
        _cb("source_done", {"source": "sec_8k", "status": "error", "summary": str(e)})
        return None


def executive_signals_analysis(company, db_path="intel.db", progress_cb=None):
    """Analyze executive hiring signals for a company. Returns report path or None.

    Detects C-suite and VP-level hires as indicators of organizational commitment.
    Uses SEC 8-K filings (public), news, and classified job data.

    Args:
        company: Company name
        db_path: Path to SQLite DB for executive job opening data
        progress_cb: Optional callback(event_type, event_data) for structured progress.
            Events emitted: source_start, source_done, generating, report_saved
    """
    _cb = progress_cb or (lambda *a: None)
    print(f"\n[exec-signals] Analyzing executive hiring signals for {company}...")

    all_results = []

    # --- Source 1: SEC 8-K filings (public companies) ---
    sec_text = _collect_sec_8k(company, _cb)

    # --- Source 2: Executive job openings from classified data ---
    _cb("source_start", {"source": "exec_openings", "label": "Executive Openings", "detail": f"Checking classified jobs for VP/C-Suite openings"})
    exec_openings_text = _get_executive_openings(company, db_path)
    if exec_openings_text:
        print(f"[exec-signals] Found executive openings in classified data")
        _cb("source_done", {"source": "exec_openings", "status": "done", "summary": "Executive openings found"})
    else:
        print(f"[exec-signals] No executive openings in classified data (no jobs collected or no VP/C-Suite roles)")
        _cb("source_done", {"source": "exec_openings", "status": "skipped", "summary": "No executive openings found"})

    # --- Source 3: Google News RSS ---
    _cb("source_start", {"source": "google_news", "label": "Google News", "detail": "Searching for executive appointment announcements"})
    print("[exec-signals] Searching Google News for executive appointments...")
    gnews1 = search_google_news(
        f'"{company}" CEO OR CTO OR CFO OR COO OR VP OR "vice president" OR "chief" appoint OR named OR joins',
        max_results=10, days_back=90,
    )
    gnews2 = search_google_news(
        f'"{company}" executive leadership change OR new OR appointed OR hire',
        max_results=8, days_back=90,
    )
    gnews = list(gnews1) + list(gnews2)
    all_results.extend(gnews)
    if gnews:
        print(f"[exec-signals] Google News returned {len(gnews)} results")
        _cb("source_done", {"source": "google_news", "status": "done", "summary": f"{len(gnews)} results", "detail": _result_detail(gnews)})
    else:
        _cb("source_done", {"source": "google_news", "status": "skipped", "summary": "No results"})

    # --- Source 4: DuckDuckGo web + news ---
    _cb("source_start", {"source": "ddg", "label": "Web Search", "detail": "Searching for leadership changes"})
    print("[exec-signals] Searching DuckDuckGo for leadership changes...")
    ddg_news = search_news(f"{company} new CTO OR CEO OR CFO OR COO OR VP appointed named", max_results=5)
    ddg_web = search_web(f"{company} executive team leadership changes hires", max_results=5)
    ddg_all = list(ddg_news) + list(ddg_web)
    all_results.extend(ddg_all)
    if ddg_all:
        print(f"[exec-signals] DuckDuckGo returned {len(ddg_all)} results")
        _cb("source_done", {"source": "ddg", "status": "done", "summary": f"{len(ddg_all)} results", "detail": _result_detail(ddg_all)})
    else:
        _cb("source_done", {"source": "ddg", "status": "skipped", "summary": "No results"})

    # --- Source 5: Hacker News ---
    _cb("source_start", {"source": "hackernews", "label": "Hacker News", "detail": "Searching tech community for leadership news"})
    print("[exec-signals] Searching Hacker News for leadership news...")
    hn = search_hackernews(f"{company} CEO CTO new hire leadership", max_results=5, fetch_comments_top_n=2)
    all_results.extend(hn)
    if hn:
        print(f"[exec-signals] Hacker News returned {len(hn)} results")
        _cb("source_done", {"source": "hackernews", "status": "done", "summary": f"{len(hn)} results", "detail": _result_detail(hn)})
    else:
        _cb("source_done", {"source": "hackernews", "status": "skipped", "summary": "No results"})

    # --- Deduplicate and format ---
    all_results = dedup_results(all_results)
    news_text = format_search_results(all_results) if all_results else ""

    if not sec_text and not news_text and not exec_openings_text:
        print(f"[exec-signals] No data from any source — cannot generate report")
        return None

    total_sources = sum([bool(sec_text), bool(exec_openings_text), bool(news_text)])
    print(f"[exec-signals] {total_sources} data source(s) with results, {len(all_results)} search results after dedup")

    # --- Generate report ---
    prompt = build_executive_signals_prompt(company, sec_text, news_text, exec_openings_text)
    prompt += get_temporal_context(company, "executive_signals")

    _cb("generating", {"detail": "LLM synthesizing executive signals report"})
    print("[exec-signals] Generating report...")
    text, model = generate_text(prompt)

    # --- Save report ---
    today = datetime.now().strftime("%Y-%m-%d")
    safe_prefix = company.lower().replace(" ", "_").replace(".", "_")

    header = f"""# Executive Hiring Signals: {company}

**Company:** {company}
**Date:** {today}
**Sources:** {total_sources} data source(s), {len(all_results)} search results | **Model:** {model}

---

"""
    report = header + text

    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    filename = unique_report_path(reports_dir, f"{safe_prefix}_executive_signals_{today}.md")
    filename.write_text(report, encoding="utf-8")

    print(f"[exec-signals] Report saved to {filename}")
    save_to_dossier(company, "executive_signals", report_file=str(filename), report_text=report, model_used=model, progress_cb=_cb)
    _cb("report_saved", {"path": str(filename), "model": model})
    return str(filename)
