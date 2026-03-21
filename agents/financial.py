"""Agent: Financial Analysis — SEC EDGAR for public companies, web search for private."""

import os
from datetime import datetime
from pathlib import Path

import httpx
import google.generativeai as genai

from scraper.sec_edgar import lookup_cik, get_company_facts, extract_financials, get_recent_filings, format_financials_for_prompt
from scraper.web_search import search_web, search_news, format_search_results
from prompts.financial import build_financial_prompt, build_financial_prompt_private

PROVIDERS = [
    {"name": "groq", "env_key": "GROQ_API_KEY", "url": "https://api.groq.com/openai/v1/chat/completions", "model": "llama-3.3-70b-versatile"},
    {"name": "mistral", "env_key": "MISTRAL_API_KEY", "url": "https://api.mistral.ai/v1/chat/completions", "model": "mistral-small-latest"},
    {"name": "gemini", "env_key": "GEMINI_API_KEYS", "url": None, "model": "gemini-2.5-flash-lite"},
]


def _generate_text(prompt):
    """Try providers in order until one works. Returns (text, model_name)."""
    http = httpx.Client(timeout=60, follow_redirects=True)
    for p in PROVIDERS:
        key = os.environ.get(p["env_key"], "").strip()
        if not key:
            continue
        if "," in key:
            key = key.split(",")[0].strip()

        try:
            if p["name"] == "gemini":
                genai.configure(api_key=key)
                model = genai.GenerativeModel(p["model"])
                response = model.generate_content(prompt)
                http.close()
                return response.text, f"gemini/{p['model']}"
            else:
                headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
                body = {"model": p["model"], "messages": [{"role": "user", "content": prompt}], "temperature": 0.3}
                resp = http.post(p["url"], json=body, headers=headers)
                if resp.status_code == 200:
                    text = resp.json()["choices"][0]["message"]["content"]
                    http.close()
                    return text, f"{p['name']}/{p['model']}"
        except Exception:
            continue
    http.close()
    raise RuntimeError("All providers failed for financial report generation")


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
        print(f"[financial] {company} not found in SEC EDGAR — using web search (private company)")
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
        print("[financial] Could not fetch company facts — falling back to web search")
        return _analyze_private(company)

    financials = extract_financials(facts)
    if not financials:
        print("[financial] No financial data found in XBRL — falling back to web search")
        return _analyze_private(company)

    filings = get_recent_filings(cik)
    financials_text = format_financials_for_prompt(financials, filings)

    print(f"[financial] Extracted {len(financials)} financial metrics, {len(filings)} recent filings")

    # Generate report
    prompt = build_financial_prompt(company, ticker, financials_text)

    print("[financial] Generating report...")
    text, model = _generate_text(prompt)

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
    return str(filename)


def _analyze_private(company):
    """Analyze a private company using web search results."""
    print(f"[financial] Searching for financial data on {company}...")

    # Multiple targeted searches
    queries = [
        f"{company} funding valuation",
        f"{company} revenue growth",
        f"{company} financial news",
    ]

    all_results = []
    for query in queries:
        results = search_web(query, max_results=3)
        all_results.extend(results)
        news = search_news(query, max_results=2)
        all_results.extend(news)

    if not all_results:
        print("[financial] No search results found")
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

    # Generate report
    prompt = build_financial_prompt_private(company, search_text)

    print("[financial] Generating report...")
    text, model = _generate_text(prompt)

    # Save report
    today = datetime.now().strftime("%Y-%m-%d")
    safe_name = company.lower().replace(" ", "_").replace(".", "_")

    header = f"""# Financial Analysis: {company}

**Status:** Private Company | **Date:** {today}
**Source:** Web Search | **Model:** {model}

---

"""
    report = header + text

    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    filename = reports_dir / f"{safe_name}_financial_{today}.md"
    filename.write_text(report, encoding="utf-8")

    print(f"[financial] Report saved to {filename}")
    return str(filename)
