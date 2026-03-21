"""Agent: Financial Analysis — SEC EDGAR for public companies, web search for private."""

from datetime import datetime
from pathlib import Path

from agents.llm import generate_text, save_to_dossier
from scraper.sec_edgar import lookup_cik, get_company_facts, extract_financials, get_recent_filings, format_financials_for_prompt
from scraper.stock_data import get_stock_data, format_stock_data_for_prompt
from scraper.web_search import search_web, search_news, format_search_results
from prompts.financial import build_financial_prompt, build_financial_prompt_private


def financial_analysis(company):
    """Run financial analysis for a company. Returns path to saved report or None."""
    print(f"\n[financial] Analyzing {company}...")

    # Step 1: Try SEC EDGAR (public company)
    cik_result = lookup_cik(company)

    if isinstance(cik_result, list):
        # Multiple matches — disambiguation needed
        print(f"[financial] Multiple SEC matches found for '{company}':")
        for i, c in enumerate(cik_result, 1):
            print(f"  {i}. {c['company_name']} (ticker: {c['ticker']}, match: {c['match_type']})")

        # In CLI mode, prompt for selection
        try:
            choice = input(f"\nSelect 1-{len(cik_result)}, or 0 for private company search: ").strip()
            idx = int(choice) - 1
            if idx < 0:
                print(f"[financial] Using web search instead")
                return _analyze_private(company)
            cik_info = cik_result[idx]
        except (ValueError, IndexError, EOFError):
            # Default to first match
            cik_info = cik_result[0]
            print(f"[financial] Defaulting to: {cik_info['company_name']}")

        return _analyze_public(company, cik_info)

    elif cik_result:
        # If match is only via ticker and name doesn't obviously match, confirm
        if cik_result.get("match_type") == "ticker":
            search_upper = company.strip().upper()
            name_upper = cik_result["company_name"].upper()
            if search_upper not in name_upper:
                print(f"[financial] Ticker '{cik_result['ticker']}' matches {cik_result['company_name']}")
                print(f"  Is this the company you meant? (If not, this might be a private company)")
                try:
                    confirm = input("  Use this match? (y/n): ").strip().lower()
                    if confirm != "y":
                        return _analyze_private(company)
                except (EOFError, KeyboardInterrupt):
                    pass
        return _analyze_public(company, cik_result)
    else:
        print(f"[financial] {company} not found in SEC EDGAR — could be private, foreign-listed, or filed under a different entity name")
        print(f"[financial] Falling back to web search — financial data will be less precise without official SEC filings")
        print(f"[financial] For better data, try checking Bloomberg, PitchBook, or the company's investor relations page directly")
        return _analyze_private(company)


def _analyze_public(company, cik_info):
    """Analyze a public company using SEC EDGAR data."""
    cik = cik_info["cik"]
    ticker = cik_info["ticker"]
    edgar_name = cik_info["company_name"]

    print(f"[financial] Found: {edgar_name} (ticker: {ticker}, CIK: {cik})")

    # Fetch EDGAR data
    facts = get_company_facts(cik)
    if not facts:
        print("[financial] Could not fetch XBRL company facts — SEC EDGAR API may be rate-limited or this entity hasn't filed in XBRL format")
        print("[financial] Falling back to web search — results will lack the precision of structured SEC data")
        return _analyze_private(company)

    financials = extract_financials(facts)
    if not financials:
        print("[financial] XBRL data exists but no standard financial metrics (revenue, net income, etc.) could be extracted")
        print("[financial] This sometimes happens with holding companies or entities that file non-standard XBRL taxonomies")
        print("[financial] Falling back to web search for financial data")
        return _analyze_private(company)

    filings = get_recent_filings(cik)
    financials_text = format_financials_for_prompt(financials, filings)

    # Fetch live market data (stock price, market cap, valuation ratios)
    print(f"[financial] Fetching live market data for {ticker}...")
    stock_data = get_stock_data(ticker)
    if stock_data:
        market_text = format_stock_data_for_prompt(stock_data)
        financials_text += "\n" + market_text
        print(f"[financial] Got market data: price={stock_data.get('price')}, market_cap={stock_data.get('market_cap')}")
    else:
        print(f"[financial] Could not fetch live market data for {ticker} — report will use SEC data only")

    print(f"[financial] Extracted {len(financials)} financial metrics, {len(filings)} recent filings")

    # Generate report
    prompt = build_financial_prompt(company, ticker, financials_text)

    print("[financial] Generating report...")
    text, model = generate_text(prompt)

    # Build and save report
    today = datetime.now().strftime("%Y-%m-%d")
    safe_name = company.lower().replace(" ", "_").replace(".", "_")

    header = f"""# Financial Analysis: {company}

**Ticker:** {ticker} | **CIK:** {cik} | **Date:** {today}
**Source:** SEC EDGAR (XBRL) | **Model:** {model}

---

"""
    report = header + text

    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    filename = reports_dir / f"{safe_name}_financial_{today}.md"
    filename.write_text(report, encoding="utf-8")

    print(f"[financial] Report saved to {filename}")
    save_to_dossier(company, "financial", report_file=str(filename), report_text=report, model_used=model)
    return str(filename)


def _analyze_private(company):
    """Analyze a private company using web search results."""
    print(f"[financial] Searching for financial data on {company}...")

    # Multiple targeted searches (cover both private and foreign-listed companies)
    queries = [
        f"{company} revenue earnings financial results",
        f"{company} funding valuation market cap",
        f"{company} financial news 2024 2025",
    ]

    all_results = []
    for query in queries:
        results = search_web(query, max_results=3)
        all_results.extend(results)
        news = search_news(query, max_results=2)
        all_results.extend(news)

    if not all_results:
        print("[financial] No web search results found — company may be too obscure, newly formed, or using a different public-facing name")
        print("[financial] Try searching with the parent company name, or check Crunchbase/PitchBook manually")
        return None

    # Deduplicate by title
    seen_titles = set()
    unique_results = []
    for r in all_results:
        title = r.get("title", "")
        if title not in seen_titles:
            seen_titles.add(title)
            unique_results.append(r)

    search_text = format_search_results(unique_results)

    # Try to find a ticker and get live market data (works for foreign-listed companies)
    from scraper.stock_data import lookup_ticker
    ticker = lookup_ticker(company)
    if ticker:
        print(f"[financial] Found ticker {ticker} for {company} — fetching live market data...")
        stock_data = get_stock_data(ticker)
        if stock_data:
            market_text = format_stock_data_for_prompt(stock_data)
            search_text += f"\n\nLIVE MARKET DATA (from Yahoo Finance, ticker: {ticker}):\n{market_text}"
            print(f"[financial] Got market data: price={stock_data.get('price')}, market_cap={stock_data.get('market_cap')}")

    # Generate report
    prompt = build_financial_prompt_private(company, search_text)

    print("[financial] Generating report...")
    text, model = generate_text(prompt)

    # Save report
    today = datetime.now().strftime("%Y-%m-%d")
    safe_name = company.lower().replace(" ", "_").replace(".", "_")

    header = f"""# Financial Analysis: {company}

**Status:** Not in SEC EDGAR (private or foreign-listed) | **Date:** {today}
**Source:** Web Search | **Model:** {model}

---

"""
    report = header + text

    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    filename = reports_dir / f"{safe_name}_financial_{today}.md"
    filename.write_text(report, encoding="utf-8")

    print(f"[financial] Report saved to {filename}")
    save_to_dossier(company, "financial", report_file=str(filename), report_text=report, model_used=model)
    return str(filename)
