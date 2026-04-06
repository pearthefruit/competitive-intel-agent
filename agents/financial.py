"""Agent: Financial Analysis — SEC EDGAR for US-listed, Yahoo Finance for foreign-listed, web search for private."""

from datetime import datetime
from pathlib import Path

from agents.llm import generate_text, save_to_dossier, get_temporal_context, unique_report_path
from scraper.sec_edgar import lookup_cik, get_company_facts, extract_financials, get_recent_filings, format_financials_for_prompt, get_8k_filings, format_8k_for_prompt
from scraper.stock_data import get_stock_data, format_stock_data_for_prompt, get_extended_financials, format_extended_financials_for_prompt
from scraper.web_search import search_web, search_news, format_search_results, dedup_results
from scraper.google_news import search_google_news
from prompts.financial import build_financial_prompt, build_financial_prompt_private
from agents.metrics import compute_financial_metrics, format_metrics_for_prompt


def _result_detail(results, max_items=15):
    """Format search results as detail lines for progress events."""
    lines = []
    for r in results[:max_items]:
        title = r.get('title', '')[:80]
        url = r.get('href', r.get('url', ''))
        if title:
            lines.append(f'• {title}' + (f'  ({url})' if url else ''))
    return '\n'.join(lines) if lines else ''


def financial_analysis(company, progress_cb=None):
    """Run financial analysis for a company. Returns path to saved report or None.

    Args:
        company: Company name
        progress_cb: Optional callback(event_type, event_data) for structured progress.
            Events emitted: source_start, source_done, generating, report_saved
    """
    _cb = progress_cb or (lambda *a: None)
    print(f"\n[financial] Analyzing {company}...")

    # Check for cached financial snapshot from niche evaluation
    # If snapshot confirms private company, skip SEC EDGAR lookup entirely
    try:
        from db import get_connection, get_or_create_dossier, get_financial_snapshot
        _snap_conn = get_connection()
        _snap_did = get_or_create_dossier(_snap_conn, company)
        _snap = get_financial_snapshot(_snap_conn, _snap_did)
        _snap_conn.close()
        if _snap and not _snap.get("is_public") and not _snap.get("ticker"):
            print(f"[financial] Snapshot confirms {company} is private — skipping SEC EDGAR lookup")
            _cb("source_start", {"source": "sec_edgar", "label": "SEC EDGAR", "detail": f"Looking up {company}"})
            _cb("source_done", {"source": "sec_edgar", "status": "skipped", "summary": "Private company (cached)"})
            return _analyze_non_sec(company, _cb)
    except Exception:
        pass

    # Step 1: Try SEC EDGAR (public company)
    _cb("source_start", {"source": "sec_edgar", "label": "SEC EDGAR", "detail": f"Looking up {company}"})
    cik_result = lookup_cik(company)

    if isinstance(cik_result, list):
        # Multiple matches — auto-select first (no interactive prompts)
        print(f"[financial] Multiple SEC matches found for '{company}':")
        for i, c in enumerate(cik_result, 1):
            print(f"  {i}. {c['company_name']} (ticker: {c['ticker']}, match: {c['match_type']})")
        cik_info = cik_result[0]
        print(f"[financial] Auto-selecting: {cik_info['company_name']}")
        _edgar_detail = f"Entity: {cik_info['company_name']}\nTicker: {cik_info['ticker']}\nCIK: {cik_info['cik']}\nMatch: {cik_info['match_type']}"
        _cb("source_done", {"source": "sec_edgar", "status": "done", "summary": f"Found: {cik_info['company_name']} (ticker: {cik_info['ticker']})", "detail": _edgar_detail})
        return _analyze_public(company, cik_info, _cb)

    elif cik_result:
        # If match is only via ticker and name doesn't match, fall back to web search
        if cik_result.get("match_type") == "ticker":
            search_upper = company.strip().upper()
            name_upper = cik_result["company_name"].upper()
            if search_upper not in name_upper:
                print(f"[financial] Ticker '{cik_result['ticker']}' matches {cik_result['company_name']} — name mismatch, using web search instead")
                _cb("source_done", {"source": "sec_edgar", "status": "skipped", "summary": "Ticker mismatch", "detail": f"Ticker {cik_result['ticker']} → {cik_result['company_name']}\nName mismatch with '{company}'"})
                return _analyze_non_sec(company, _cb)
        _edgar_detail = f"Entity: {cik_result['company_name']}\nTicker: {cik_result['ticker']}\nCIK: {cik_result['cik']}\nMatch: {cik_result['match_type']}"
        _cb("source_done", {"source": "sec_edgar", "status": "done", "summary": f"Found: {cik_result['company_name']} (ticker: {cik_result['ticker']})", "detail": _edgar_detail})
        return _analyze_public(company, cik_result, _cb)
    else:
        print(f"[financial] {company} not found in SEC EDGAR — could be private, foreign-listed, or filed under a different entity name")
        print(f"[financial] Falling back to web search — financial data will be less precise without official SEC filings")
        print(f"[financial] For better data, try checking Bloomberg, PitchBook, or the company's investor relations page directly")
        _cb("source_done", {"source": "sec_edgar", "status": "skipped", "summary": "Not found (private or foreign)"})
        return _analyze_non_sec(company, _cb)


def _analyze_public(company, cik_info, _cb=None):
    """Analyze a public company using SEC EDGAR data."""
    _cb = _cb or (lambda *a: None)
    cik = cik_info["cik"]
    ticker = cik_info["ticker"]
    edgar_name = cik_info["company_name"]

    print(f"[financial] Found: {edgar_name} (ticker: {ticker}, CIK: {cik})")

    # Fetch EDGAR data
    _cb("source_start", {"source": "xbrl", "label": "XBRL Financials", "detail": f"Fetching company facts for CIK {cik}"})
    facts = get_company_facts(cik)
    if not facts:
        print("[financial] Could not fetch XBRL company facts — SEC EDGAR API may be rate-limited or this entity hasn't filed in XBRL format")
        print("[financial] Falling back to web search — results will lack the precision of structured SEC data")
        _cb("source_done", {"source": "xbrl", "status": "error", "summary": "API unavailable"})
        return _analyze_non_sec(company, _cb)

    financials = extract_financials(facts)
    if not financials:
        print("[financial] XBRL data exists but no standard financial metrics (revenue, net income, etc.) could be extracted")
        print("[financial] This sometimes happens with holding companies or entities that file non-standard XBRL taxonomies")
        print("[financial] Falling back to web search for financial data")
        _cb("source_done", {"source": "xbrl", "status": "error", "summary": "No extractable metrics"})
        return _analyze_non_sec(company, _cb)

    filings = get_recent_filings(cik)
    financials_text = format_financials_for_prompt(financials, filings)
    xbrl_detail = "Metrics: " + ", ".join(financials.keys()) + f"\n{len(filings)} recent filings"
    _cb("source_done", {"source": "xbrl", "status": "done", "summary": f"{len(financials)} metrics, {len(filings)} filings", "detail": xbrl_detail})

    # Fetch live market data (stock price, market cap, valuation ratios)
    _cb("source_start", {"source": "yahoo_finance", "label": "Yahoo Finance", "detail": f"Market data for {ticker}"})
    print(f"[financial] Fetching live market data for {ticker}...")
    stock_data = get_stock_data(ticker)
    if stock_data:
        market_text = format_stock_data_for_prompt(stock_data)
        financials_text += "\n" + market_text
        print(f"[financial] Got market data: price={stock_data.get('price')}, market_cap={stock_data.get('market_cap')}")
        yf_detail = '\n'.join(f"• {k}: {v}" for k, v in stock_data.items() if v is not None and k not in ('_raw',))
        _cb("source_done", {"source": "yahoo_finance", "status": "done", "summary": f"price={stock_data.get('price')}, cap={stock_data.get('market_cap')}", "detail": yf_detail})
    else:
        print(f"[financial] Could not fetch live market data for {ticker} — report will use SEC data only")
        _cb("source_done", {"source": "yahoo_finance", "status": "skipped", "summary": "Unavailable"})

    print(f"[financial] Extracted {len(financials)} financial metrics, {len(filings)} recent filings")

    # Fetch extended data (analyst estimates, upgrades, news — not statements since SEC has those)
    _cb("source_start", {"source": "analyst", "label": "Analyst Estimates", "detail": f"Estimates + news for {ticker}"})
    print(f"[financial] Fetching analyst estimates and news for {ticker}...")
    extended = get_extended_financials(ticker)
    if extended:
        currency = stock_data.get("currency", "USD") if stock_data else "USD"
        ext_text = format_extended_financials_for_prompt(extended, currency=currency, include_statements=False)
        if ext_text:
            financials_text += "\n" + ext_text
            print(f"[financial] Added analyst estimates and news")
            _cb("source_done", {"source": "analyst", "status": "done", "summary": "Analyst estimates added"})
    else:
        _cb("source_done", {"source": "analyst", "status": "skipped", "summary": "No data"})

    # Fetch recent 8-K filings (material business events)
    _cb("source_start", {"source": "8k_filings", "label": "8-K Filings", "detail": "Material business events"})
    print(f"[financial] Fetching recent 8-K filing events...")
    eight_k = get_8k_filings(cik)
    if eight_k:
        financials_text += "\n" + format_8k_for_prompt(eight_k)
        print(f"[financial] Added {len(eight_k)} 8-K filing events")
        eight_k_detail = '\n'.join(f"• {e.get('form', '8-K')} ({e.get('date', 'N/A')}): {', '.join(e.get('items', []))}" for e in eight_k[:10])
        _cb("source_done", {"source": "8k_filings", "status": "done", "summary": f"{len(eight_k)} events", "detail": eight_k_detail})
    else:
        _cb("source_done", {"source": "8k_filings", "status": "skipped", "summary": "None found"})

    # Compute deterministic financial metrics
    fin_metrics = compute_financial_metrics(financials, stock_data, extended)
    if fin_metrics:
        metrics_block = format_metrics_for_prompt({"financial": fin_metrics})
        if metrics_block:
            financials_text += "\n\n" + metrics_block
        print(f"[financial] Computed {len(fin_metrics)} deterministic metrics")

    # Generate report
    prompt = build_financial_prompt(company, ticker, financials_text)
    prompt += get_temporal_context(company, "financial")

    _cb("generating", {"detail": "LLM synthesizing financial report"})
    print("[financial] Generating report...")
    text, model = generate_text(prompt)

    # Build quick-reference metrics header
    today = datetime.now().strftime("%Y-%m-%d")
    safe_name = company.lower().replace(" ", "_").replace(".", "_")

    metrics_header = ""
    if fin_metrics:
        parts = []
        if fin_metrics.get("revenue_formatted"):
            s = f"**Revenue:** {fin_metrics['revenue_formatted']}"
            if fin_metrics.get("revenue_yoy_growth") is not None:
                s += f" ({fin_metrics['revenue_yoy_growth']:+.1f}% YoY)"
            parts.append(s)
        if fin_metrics.get("rd_intensity") is not None:
            parts.append(f"**R&D Intensity:** {fin_metrics['rd_intensity']:.1f}%")
        if fin_metrics.get("operating_margin") is not None:
            parts.append(f"**Op Margin:** {fin_metrics['operating_margin']:.1f}%")
        if fin_metrics.get("fcf_formatted"):
            parts.append(f"**FCF:** {fin_metrics['fcf_formatted']}")
        if fin_metrics.get("market_cap_formatted"):
            parts.append(f"**Market Cap:** {fin_metrics['market_cap_formatted']}")
        if parts:
            metrics_header = "\n" + " | ".join(parts) + "\n"

    header = f"""# Financial Analysis: {company}

**Ticker:** {ticker} | **CIK:** {cik} | **Date:** {today}
**Source:** SEC EDGAR (XBRL) | **Model:** {model}
{metrics_header}
---

"""
    report = header + text

    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    filename = unique_report_path(reports_dir, f"{safe_name}_financial_{today}.md")
    filename.write_text(report, encoding="utf-8")

    print(f"[financial] Report saved to {filename}")
    dossier_result = save_to_dossier(company, "financial", report_file=str(filename), report_text=report, model_used=model, progress_cb=_cb)

    # Overlay computed metrics onto LLM-extracted key facts for precision
    if fin_metrics and dossier_result:
        _persist_computed_metrics(company, fin_metrics)

    _cb("report_saved", {"path": str(filename), "model": model})
    return str(filename)


def _persist_computed_metrics(company, fin_metrics):
    """Override LLM-extracted financial key facts with deterministic computed values."""
    try:
        from db import get_connection, get_dossier_by_company
        import json

        conn = get_connection()
        dossier = get_dossier_by_company(conn, company)
        if not dossier:
            conn.close()
            return

        row = conn.execute(
            "SELECT id, key_facts_json FROM dossier_analyses WHERE dossier_id = ? AND analysis_type = 'financial' ORDER BY created_at DESC LIMIT 1",
            (dossier["id"],)
        ).fetchone()
        if not row or not row["key_facts_json"]:
            conn.close()
            return

        kf = json.loads(row["key_facts_json"])

        # Override with computed values (more reliable than LLM extraction)
        if fin_metrics.get("revenue_formatted"):
            kf["revenue"] = fin_metrics["revenue_formatted"]
        if fin_metrics.get("revenue_yoy_growth") is not None:
            kf["revenue_growth"] = f"{fin_metrics['revenue_yoy_growth']:+.1f}%"
        if fin_metrics.get("market_cap_formatted"):
            kf["market_cap"] = fin_metrics["market_cap_formatted"]
        if fin_metrics.get("employee_count"):
            kf["headcount"] = fin_metrics["employee_count"]
        if fin_metrics.get("cash_formatted"):
            kf["cash_position"] = fin_metrics["cash_formatted"]

        # Store the full computed metrics for the briefing to consume
        kf["_computed_metrics"] = fin_metrics

        conn.execute(
            "UPDATE dossier_analyses SET key_facts_json = ? WHERE id = ?",
            (json.dumps(kf), row["id"])
        )
        conn.commit()
        conn.close()
        print(f"[financial] Persisted {len(fin_metrics)} computed metrics to key facts")
    except Exception as e:
        print(f"[financial] Warning: could not persist computed metrics: {e}")


def _analyze_non_sec(company, _cb=None):
    """Analyze a company not in SEC EDGAR using ProPublica 990 + Yahoo Finance + web search."""
    _cb = _cb or (lambda *a: None)
    print(f"[financial] Searching for financial data on {company}...")

    # Try ProPublica Nonprofit Explorer first (free, no auth, structured 990 data)
    _cb("source_start", {"source": "propublica", "label": "ProPublica 990", "detail": f"Nonprofit lookup for {company}"})
    nonprofit_data = None
    try:
        from scraper.nonprofit import search_nonprofit, get_nonprofit_financials, format_990_for_prompt
        match = search_nonprofit(company)
        if match:
            print(f"[financial] Found nonprofit match: {match['name']} (EIN: {match['ein']})")
            financials = get_nonprofit_financials(match["ein"])
            if financials and financials.get("filings"):
                nonprofit_data = format_990_for_prompt(financials)
                print(f"[financial] Got Form 990 data — {len(financials['filings'])} years of filings")
                pp_detail = f"Name: {match['name']}\nEIN: {match['ein']}\n{len(financials['filings'])} years of Form 990 data"
                _cb("source_done", {"source": "propublica", "status": "done", "summary": f"{len(financials['filings'])} years of 990 filings", "detail": pp_detail})
            else:
                print(f"[financial] Nonprofit matched but no 990 filings found")
                _cb("source_done", {"source": "propublica", "status": "skipped", "summary": "Matched but no filings"})
        else:
            _cb("source_done", {"source": "propublica", "status": "skipped", "summary": "Not a nonprofit"})
    except Exception as e:
        print(f"[financial] ProPublica lookup failed: {e}")
        _cb("source_done", {"source": "propublica", "status": "error", "summary": str(e)[:80]})

    # Multiple targeted searches (cover both private and foreign-listed companies)
    _cb("source_start", {"source": "web_search", "label": "Web Search", "detail": f"5 financial queries for {company}"})
    year = datetime.now().year
    queries = [
        f"{company} revenue earnings financial results {year - 1} {year}",
        f"{company} funding valuation market cap {year}",
        f"{company} annual report fiscal year {year - 1}",
        f"{company} financial news {year - 1} {year}",
        # Finance-sector queries — harmless for non-finance companies (just return nothing)
        f"{company} assets under management AUM {year}",
    ]

    all_results = []
    for query in queries:
        results = search_web(query, max_results=5, fetch_content=True)
        all_results.extend(results)
        news = search_news(query, max_results=3, fetch_content=True)
        all_results.extend(news)
        gnews = search_google_news(query, max_results=3, days_back=30)
        all_results.extend(gnews)

    if not all_results:
        print("[financial] No web search results found — company may be too obscure, newly formed, or using a different public-facing name")
        print("[financial] Try searching with the parent company name, or check Crunchbase/PitchBook manually")
        _cb("source_done", {"source": "web_search", "status": "error", "summary": "No results"})
        return None

    # Deduplicate (normalized title matching, keeps highest-quality source)
    unique_results = dedup_results(all_results)

    # Log fetch stats so we can see how much content actually made it through
    fetched = [r for r in unique_results if len(r.get("body", "")) > 300]
    snippet_only = [r for r in unique_results if 0 < len(r.get("body", "")) <= 300]
    no_body = [r for r in unique_results if not r.get("body")]
    print(f"[financial] Search results: {len(unique_results)} unique ({len(fetched)} with fetched content, {len(snippet_only)} snippet-only, {len(no_body)} no body)")
    web_detail = _result_detail(unique_results)
    _cb("source_done", {"source": "web_search", "status": "done", "summary": f"{len(unique_results)} unique results ({len(queries)} queries)", "detail": web_detail})

    search_text = format_search_results(unique_results)

    # Try to find a ticker and get live market data (works for foreign-listed companies)
    _cb("source_start", {"source": "yahoo_finance", "label": "Yahoo Finance", "detail": f"Ticker lookup for {company}"})
    from scraper.stock_data import lookup_ticker
    ticker = lookup_ticker(company)
    has_statements = False
    if ticker:
        print(f"[financial] Found ticker {ticker} for {company} — fetching live market data...")
        stock_data = get_stock_data(ticker)
        if stock_data:
            market_text = format_stock_data_for_prompt(stock_data)
            search_text += f"\n\nLIVE MARKET DATA (from Yahoo Finance, ticker: {ticker}):\n{market_text}"
            print(f"[financial] Got market data: price={stock_data.get('price')}, market_cap={stock_data.get('market_cap')}")

        # Fetch full financial statements + analyst data + news
        print(f"[financial] Fetching financial statements and analyst data for {ticker}...")
        extended = get_extended_financials(ticker)
        if extended:
            currency = stock_data.get("currency", "") if stock_data else ""
            ext_text = format_extended_financials_for_prompt(extended, currency=currency, include_statements=True)
            if ext_text:
                search_text += "\n" + ext_text
                has_statements = "income_stmt" in extended
                if has_statements:
                    print(f"[financial] Got full financial statements — this company has structured data comparable to SEC filers")
        yf2_parts = [f"Ticker: {ticker}"]
        if stock_data:
            yf2_parts.extend(f"• {k}: {v}" for k, v in stock_data.items() if v is not None and k not in ('_raw',))
        if has_statements:
            yf2_parts.append("Financial statements: available")
        _cb("source_done", {"source": "yahoo_finance", "status": "done", "summary": f"ticker={ticker}, statements={'yes' if has_statements else 'no'}", "detail": '\n'.join(yf2_parts)})
    else:
        _cb("source_done", {"source": "yahoo_finance", "status": "skipped", "summary": "No ticker found"})

    # Prepend 990 data if available — gives LLM structured financials for nonprofits
    if nonprofit_data:
        search_text = nonprofit_data + "\n\n---\n\nADDITIONAL WEB SEARCH CONTEXT:\n" + search_text
        has_statements = True  # 990 data is structured like financial statements

    # Generate report
    prompt = build_financial_prompt_private(company, search_text, has_statements=has_statements)
    prompt += get_temporal_context(company, "financial")

    _cb("generating", {"detail": "LLM synthesizing financial report"})
    print("[financial] Generating report...")
    text, model = generate_text(prompt)

    # Save report
    today = datetime.now().strftime("%Y-%m-%d")
    safe_name = company.lower().replace(" ", "_").replace(".", "_")

    ticker_info = f" | **Ticker:** {ticker}" if ticker else ""
    source_parts = []
    if nonprofit_data:
        source_parts.append("ProPublica 990")
    if ticker:
        source_parts.append("Yahoo Finance")
    source_parts.append("Web Search")
    source = " + ".join(source_parts)
    header = f"""# Financial Analysis: {company}

**Status:** Not in SEC EDGAR (foreign-listed or private){ticker_info} | **Date:** {today}
**Source:** {source} | **Model:** {model}

---

"""
    report = header + text

    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    filename = unique_report_path(reports_dir, f"{safe_name}_financial_{today}.md")
    filename.write_text(report, encoding="utf-8")

    print(f"[financial] Report saved to {filename}")
    save_to_dossier(company, "financial", report_file=str(filename), report_text=report, model_used=model, progress_cb=_cb)
    _cb("report_saved", {"path": str(filename), "model": model})
    return str(filename)
