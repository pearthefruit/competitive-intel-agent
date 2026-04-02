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

# Map common brand/product names to SEC filing entity names
COMPANY_ALIASES = {
    "GOOGLE": "ALPHABET",
    "YOUTUBE": "ALPHABET",
    "WAYMO": "ALPHABET",
    "DEEPMIND": "ALPHABET",
    "FACEBOOK": "META PLATFORMS",
    "INSTAGRAM": "META PLATFORMS",
    "WHATSAPP": "META PLATFORMS",
    "SNAPCHAT": "SNAP",
    "TIKTOK": "BYTEDANCE",
    "LINKEDIN": "MICROSOFT",
    "GITHUB": "MICROSOFT",
    "AWS": "AMAZON.COM",
    "AMAZON": "AMAZON.COM",
    "WHOLE FOODS": "AMAZON.COM",
    "TWITTER": "X HOLDINGS",
    "VMWARE": "BROADCOM",
    "PAYPAL": "PAYPAL HOLDINGS",
    "VENMO": "PAYPAL HOLDINGS",
    "SLACK": "SALESFORCE",
    "TABLEAU": "SALESFORCE",
    "ACTIVISION": "MICROSOFT",
    "ACTIVISION BLIZZARD": "MICROSOFT",
    "PLAYSTATION": "SONY GROUP",
    "SONY": "SONY GROUP",
    "SAMSUNG": None,  # Korean-listed, not in SEC
}

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

    # Resolve brand/product names to SEC filing entity names
    alias = COMPANY_ALIASES.get(search)
    if alias is None and search in COMPANY_ALIASES:
        # Explicitly mapped to None = known non-SEC company
        print(f"[edgar] {company_name} is known to be non-US-listed (no SEC filings)")
        return None
    if alias:
        print(f"[edgar] Resolved alias: {company_name} → {alias}")
        search = alias

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
    Only includes clean annual (FY) and single-quarter (Q1-Q4) data,
    filtering out cumulative YTD entries and duplicates.
    """
    if not facts or "facts" not in facts:
        return {}

    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    dei = facts.get("facts", {}).get("dei", {})

    results = {}

    for metric_name, tag_options in FINANCIAL_TAGS.items():
        # Try ALL tag variants and pick the one with the most recent data.
        # Companies change XBRL tags over time (e.g. "Revenues" -> ASC 606
        # "RevenueFromContractWithCustomerExcludingAssessedTax"), so the
        # first tag with data may only have stale entries.
        best_entries = []
        best_max_period = ""
        best_tag = None

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

            # Filter to 10-K/10-Q filings, prefer entries with a "frame"
            # field (CY2025, CY2025Q3, etc.) which are clean single-period
            # snapshots. Entries without "frame" are often cumulative YTD
            # figures (e.g. Jan-Sep) that confuse analysis.
            entries = []
            seen = set()  # Deduplicate by (period, fiscal_period)
            for item in unit_data:
                form = item.get("form", "")
                if form not in ("10-K", "10-Q", "10-K/A", "10-Q/A"):
                    continue

                end_date = item.get("end")
                if not end_date:
                    continue

                fp = item.get("fp", "")
                frame = item.get("frame", "")

                # Skip cumulative YTD entries from 10-Q filings.
                # These lack a "frame" and span >100 days (e.g. Jan-Sep).
                # We only want single-quarter entries (frame like CY2025Q3)
                # and full-year entries (frame like CY2025 from 10-K).
                if form in ("10-Q", "10-Q/A") and not frame:
                    continue

                # Deduplicate: same period end + fiscal period can appear
                # in multiple filings (e.g. FY2024 in both 2024 and 2025 10-K)
                dedup_key = (end_date, fp)
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)

                entries.append({
                    "period": end_date,
                    "value": item.get("val"),
                    "form": form,
                    "filed": item.get("filed", ""),
                    "fiscal_year": item.get("fy"),
                    "fiscal_period": fp,
                })

            if entries:
                entries.sort(key=lambda x: x["period"], reverse=True)
                max_period = entries[0]["period"]
                # Keep whichever tag has the most recent data point
                if max_period > best_max_period:
                    best_max_period = max_period
                    best_entries = entries
                    best_tag = tag

        if best_entries:
            results[metric_name] = best_entries[:12]
            print(f"[edgar] {metric_name}: using tag '{best_tag}', latest={best_max_period}, {len(best_entries)} entries")

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
        accessions = recent.get("accessionNumber", [])

        filings = []
        target_forms = {"10-K", "10-Q", "8-K", "10-K/A", "10-Q/A", "DEF 14A", "S-1"}

        for i in range(len(forms)):
            if forms[i] in target_forms:
                # Build SEC filing URL
                accession = accessions[i] if i < len(accessions) else ""
                doc = docs[i] if i < len(docs) else ""
                filing_url = ""
                if accession and doc:
                    acc_no_dashes = accession.replace("-", "")
                    filing_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_no_dashes}/{doc}"

                filings.append({
                    "form": forms[i],
                    "date": dates[i] if i < len(dates) else "",
                    "document": doc,
                    "description": descriptions[i] if i < len(descriptions) else "",
                    "url": filing_url,
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
            line = f"  {f['date']}: {f['form']} — {f.get('description', '')}"
            if f.get("url"):
                line += f"\n    URL: {f['url']}"
            lines.append(line)

    return "\n".join(lines)


def get_8k_filings(cik, max_filings=15):
    """Fetch recent 8-K filings for a company from the submissions API.

    8-K filings disclose material business events: acquisitions, executive
    changes, material agreements, earnings, impairments, etc.

    Returns list of {form, date, description, url}.
    """
    cik_padded = str(cik).zfill(10)
    url = SUBMISSIONS_URL.format(cik=cik_padded)

    http = httpx.Client(headers=EDGAR_HEADERS, timeout=15)
    try:
        print(f"[edgar] Fetching 8-K filings...")
        resp = http.get(url)
        if resp.status_code != 200:
            print(f"[edgar] Submissions API returned {resp.status_code}")
            return []

        data = resp.json()
        recent = data.get("filings", {}).get("recent", {})

        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        docs = recent.get("primaryDocument", [])
        descriptions = recent.get("primaryDocDescription", [])
        accessions = recent.get("accessionNumber", [])

        filings = []
        for i in range(len(forms)):
            if forms[i] != "8-K":
                continue

            accession = accessions[i] if i < len(accessions) else ""
            doc = docs[i] if i < len(docs) else ""
            filing_url = ""
            if accession and doc:
                acc_no_dashes = accession.replace("-", "")
                filing_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_no_dashes}/{doc}"

            filings.append({
                "form": "8-K",
                "date": dates[i] if i < len(dates) else "",
                "description": descriptions[i] if i < len(descriptions) else "",
                "url": filing_url,
            })
            if len(filings) >= max_filings:
                break

        print(f"[edgar] Found {len(filings)} 8-K filings")
        return filings

    except Exception as e:
        print(f"[edgar] 8-K fetch failed: {e}")
        return []
    finally:
        http.close()


def fetch_8k_content(filing_url, max_chars=5000):
    """Fetch and extract text content from an 8-K filing HTML document.

    Returns cleaned text or empty string on failure.
    """
    if not filing_url:
        return ""
    try:
        http = httpx.Client(headers=EDGAR_HEADERS, timeout=15, follow_redirects=True)
        resp = http.get(filing_url)
        http.close()
        if resp.status_code != 200:
            return ""
        html = resp.text
        # Strip HTML tags
        text = re.sub(r'<[^>]+>', ' ', html)
        # Collapse whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:max_chars]
    except Exception as e:
        print(f"[edgar] Failed to fetch 8-K content: {e}")
        return ""


def format_8k_for_prompt(filings):
    """Format 8-K filing events for LLM context."""
    if not filings:
        return ""

    lines = ["\n### Recent 8-K Filings (Business Events)"]
    for f in filings:
        line = f"  {f['date']}: {f['form']}"
        desc = f.get("description", "")
        if desc:
            line += f" — {desc}"
        if f.get("url"):
            line += f"\n    URL: {f['url']}"
        lines.append(line)

    return "\n".join(lines)
