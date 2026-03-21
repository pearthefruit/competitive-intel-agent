"""SEC EDGAR API client — fetch financial data for US public companies."""

import re
from urllib.parse import quote

import httpx

EDGAR_HEADERS = {
    "User-Agent": "CompetitiveIntelAgent contact@example.com",
    "Accept": "application/json",
}

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"

# Cache the tickers list in memory
_tickers_cache = None

# XBRL tags we care about (in priority order for each metric)
FINANCIAL_TAGS = {
    "revenue": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
        "SalesRevenueServicesNet",
    ],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "operating_income": ["OperatingIncomeLoss"],
    "gross_profit": ["GrossProfit"],
    "rd_expense": [
        "ResearchAndDevelopmentExpense",
        "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost",
    ],
    "total_assets": ["Assets"],
    "total_liabilities": ["Liabilities"],
    "cash": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsAndShortTermInvestments",
    ],
    "stockholders_equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "shares_outstanding": ["CommonStockSharesOutstanding", "EntityCommonStockSharesOutstanding"],
    "employees": ["EntityNumberOfEmployees"],
}


def _load_tickers():
    """Load and cache the SEC tickers list."""
    global _tickers_cache
    if _tickers_cache is None:
        http = httpx.Client(headers=EDGAR_HEADERS, timeout=15)
        try:
            print("[edgar] Fetching company tickers list...")
            resp = http.get(TICKERS_URL)
            if resp.status_code != 200:
                print(f"[edgar] Failed to fetch tickers: {resp.status_code}")
                return None
            _tickers_cache = resp.json()
        finally:
            http.close()
    return _tickers_cache


def _strip_suffixes(name):
    """Remove common corporate suffixes for comparison."""
    result = name.upper().replace(",", "").replace(".", "")
    for suffix in ["INC", "CORP", "CORPORATION", "LLC", "LTD", "CO", "HOLDINGS", "GROUP", "PLC"]:
        result = result.replace(suffix, "").strip()
    return result.strip()


def lookup_cik(company_name):
    """Look up a company's CIK number from its name or ticker.

    Returns dict with {cik, ticker, company_name, match_type} or None.
    If multiple ambiguous matches, returns list of candidates instead.
    """
    tickers = _load_tickers()
    if not tickers:
        return None

    search = company_name.strip().upper()
    search_base = _strip_suffixes(search)

    candidates = []

    # Pass 1: Exact name match (highest confidence)
    for entry in tickers.values():
        title_base = _strip_suffixes(entry["title"])
        if search_base == title_base:
            return {
                "cik": entry["cik_str"],
                "ticker": entry["ticker"],
                "company_name": entry["title"],
                "match_type": "exact_name",
            }

    # Pass 2: Name contains as whole word
    for entry in tickers.values():
        title = entry["title"].upper()
        if re.search(r'\b' + re.escape(search_base) + r'\b', title):
            candidates.append({
                "cik": entry["cik_str"],
                "ticker": entry["ticker"],
                "company_name": entry["title"],
                "match_type": "name_contains",
            })

    # Pass 3: Ticker match
    ticker_match = None
    for entry in tickers.values():
        if entry["ticker"].upper() == search:
            ticker_match = {
                "cik": entry["cik_str"],
                "ticker": entry["ticker"],
                "company_name": entry["title"],
                "match_type": "ticker",
            }
            break

    # If we have a name match, prefer it over ticker match
    if len(candidates) == 1:
        return candidates[0]

    # If multiple name matches, add ticker match if different
    if ticker_match:
        # Don't add if it's already in candidates
        if not any(c["cik"] == ticker_match["cik"] for c in candidates):
            candidates.append(ticker_match)

    if not candidates and ticker_match:
        return ticker_match

    # Pass 4: Word-based matching (multi-word searches)
    if not candidates:
        search_words = set(search.split())
        if len(search_words) >= 2:
            for entry in tickers.values():
                title_words = set(entry["title"].upper().split())
                if search_words.issubset(title_words):
                    candidates.append({
                        "cik": entry["cik_str"],
                        "ticker": entry["ticker"],
                        "company_name": entry["title"],
                        "match_type": "word_match",
                    })

    if len(candidates) == 1:
        return candidates[0]
    elif len(candidates) > 1:
        # Return list for disambiguation
        return candidates[:5]

    return None


def get_company_facts(cik):
    """Fetch all XBRL facts for a company from EDGAR.

    Returns the full JSON response or None on failure.
    """
    cik_padded = str(cik).zfill(10)
    url = COMPANY_FACTS_URL.format(cik=cik_padded)

    http = httpx.Client(headers=EDGAR_HEADERS, timeout=30)
    try:
        print(f"[edgar] Fetching company facts for CIK {cik}...")
        resp = http.get(url)
        if resp.status_code != 200:
            print(f"[edgar] Failed to fetch company facts: {resp.status_code}")
            return None
        return resp.json()
    finally:
        http.close()


def extract_financials(facts):
    """Extract key financial metrics from XBRL company facts.

    Returns dict of {metric_name: [{period, value, unit, filed}, ...]}.
    Only includes USD annual (10-K) and quarterly (10-Q) data.
    """
    if not facts or "facts" not in facts:
        return {}

    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    dei = facts.get("facts", {}).get("dei", {})

    results = {}

    for metric_name, tag_options in FINANCIAL_TAGS.items():
        # Try each tag variant until we find one with data
        for tag in tag_options:
            # Check both us-gaap and dei namespaces
            concept = us_gaap.get(tag) or dei.get(tag)
            if not concept:
                continue

            units = concept.get("units", {})

            # For monetary values, use USD; for shares/employees, use "shares" or "pure"
            unit_data = units.get("USD") or units.get("shares") or units.get("pure")
            if not unit_data:
                # Try first available unit
                if units:
                    unit_data = list(units.values())[0]

            if not unit_data:
                continue

            # Filter to 10-K (annual) and 10-Q (quarterly) filings
            entries = []
            for item in unit_data:
                form = item.get("form", "")
                if form not in ("10-K", "10-Q", "10-K/A", "10-Q/A"):
                    continue

                # Only include entries with an end date (period-end snapshots)
                end_date = item.get("end")
                if not end_date:
                    continue

                # Skip entries with start dates far from end (annual in quarterly, etc.)
                start = item.get("start")
                if start and form in ("10-Q", "10-Q/A"):
                    # Quarterly entries should span ~90 days
                    pass  # Keep all for now, LLM can interpret

                entries.append({
                    "period": end_date,
                    "value": item.get("val"),
                    "form": form,
                    "filed": item.get("filed", ""),
                    "fiscal_year": item.get("fy"),
                    "fiscal_period": item.get("fp"),
                })

            if entries:
                # Sort by period descending, keep last 12 entries (3 years)
                entries.sort(key=lambda x: x["period"], reverse=True)
                results[metric_name] = entries[:12]
                break  # Found data for this metric, move to next

    return results


def get_recent_filings(cik, max_filings=10):
    """Fetch recent filing metadata for a company.

    Returns list of {form, filingDate, primaryDocument, description}.
    """
    cik_padded = str(cik).zfill(10)
    url = SUBMISSIONS_URL.format(cik=cik_padded)

    http = httpx.Client(headers=EDGAR_HEADERS, timeout=15)
    try:
        print(f"[edgar] Fetching recent filings...")
        resp = http.get(url)
        if resp.status_code != 200:
            return []

        data = resp.json()
        recent = data.get("filings", {}).get("recent", {})

        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        docs = recent.get("primaryDocument", [])
        descriptions = recent.get("primaryDocDescription", [])

        filings = []
        target_forms = {"10-K", "10-Q", "8-K", "10-K/A", "10-Q/A", "DEF 14A", "S-1"}

        for i in range(len(forms)):
            if forms[i] in target_forms:
                filings.append({
                    "form": forms[i],
                    "date": dates[i] if i < len(dates) else "",
                    "document": docs[i] if i < len(docs) else "",
                    "description": descriptions[i] if i < len(descriptions) else "",
                })
                if len(filings) >= max_filings:
                    break

        return filings

    finally:
        http.close()


def format_financials_for_prompt(financials, filings):
    """Format extracted financial data into a string for the LLM prompt."""
    lines = []

    for metric, entries in financials.items():
        label = metric.replace("_", " ").title()
        lines.append(f"\n### {label}")

        for e in entries[:8]:  # Last 8 data points
            value = e["value"]
            if value is None:
                continue

            # Format large numbers
            if isinstance(value, (int, float)):
                if abs(value) >= 1_000_000_000:
                    formatted = f"${value / 1_000_000_000:.2f}B"
                elif abs(value) >= 1_000_000:
                    formatted = f"${value / 1_000_000:.1f}M"
                elif abs(value) >= 1_000:
                    formatted = f"${value / 1_000:.1f}K"
                else:
                    formatted = f"{value:,.0f}"
            else:
                formatted = str(value)

            period_label = f"{e.get('fiscal_period', '??')} {e.get('fiscal_year', '??')}"
            lines.append(f"  {period_label} ({e['form']}): {formatted}")

    if filings:
        lines.append("\n### Recent Filings")
        for f in filings[:8]:
            lines.append(f"  {f['date']}: {f['form']} — {f.get('description', '')}")

    return "\n".join(lines)
