"""SEC EDGAR API client — fetch financial data for US public companies."""

import re
from urllib.parse import quote

import httpx

from scraper.money import format_money

try:
    from bs4 import BeautifulSoup as _BeautifulSoup
    _BS4_AVAILABLE = True
except ImportError:
    _BS4_AVAILABLE = False

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

            # Shared formatter — every financial source must present the same
            # units, since they all land in one prompt. See scraper/money.py.
            if isinstance(value, (int, float)):
                formatted = format_money(value)
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
                "accession_number": accession,
                "items": [],  # 8-K item list (e.g. "Item 2.02") not in submissions JSON
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


# ── 10-K section extraction for RAG indexing ───────────────────────────────────────────────

# Sections worth capturing for semantic search. Keys are stable identifiers
# stored in source_sections.section_key (matched via _SECTION_PATTERNS).
SECTION_LABELS = {
    "item1":  "Business",
    "item1a": "Risk Factors",
    "item2":  "Properties",
    "item7":  "Management Discussion & Analysis",
    "item7a": "Quantitative Disclosures About Market Risk",
    "item8":  "Financial Statements",
}

# Maximum filing HTML size we will download (30 MB). Modern inline-XBRL
# 10-K primary documents typically run 5-30 MB.
_MAX_10K_BYTES = 30 * 1024 * 1024

# Hard cap per extracted section (words) — safety against runaway spans
_MAX_SECTION_WORDS = 60_000

try:
    import lxml  # noqa: F401
    _LXML_AVAILABLE = True
except ImportError:
    _LXML_AVAILABLE = False

# Heading regexes per SECTION_LABELS key. Require the heading title words
# (not just "Item 1A") to avoid matching bare cross-references. The quote
# lookbehind rejects quoted cross-references like see "Item 1A. Risk Factors".
_SEP = r"\s*[.:—–\-]?\s*"
_NOQ = r"(?<![\"“‘'])"


def _title_words(*words):
    """Build a heading-title regex tolerating dropcap/small-caps splits.

    Some filers (e.g. Microsoft) style each word's first letter in its own
    span, so extracted text reads "B USINESS" — allow whitespace after the
    first letter of every word.
    """
    return r"\s+".join(w[0] + r"\s*" + w[1:] for w in words)


_SECTION_PATTERNS = {
    "item1":  re.compile(_NOQ + r"item\s+1" + _SEP + _title_words("business"), re.IGNORECASE),
    "item1a": re.compile(_NOQ + r"item\s+1a" + _SEP + _title_words("risk", "factors"), re.IGNORECASE),
    "item2":  re.compile(_NOQ + r"item\s+2" + _SEP + _title_words("propert") + r"(?:ies|y)", re.IGNORECASE),
    "item7":  re.compile(_NOQ + r"item\s+7" + _SEP + r"m\s*anagement[’']?s?\s+d\s*iscussion", re.IGNORECASE),
    "item7a": re.compile(_NOQ + r"item\s+7a" + _SEP + _title_words("quantitative", "and", "qualitative"), re.IGNORECASE),
    "item8":  re.compile(_NOQ + r"item\s+8" + _SEP + _title_words("financial", "statements"), re.IGNORECASE),
}

_HIDDEN_STYLE_RE = re.compile(r"display\s*:\s*none", re.IGNORECASE)


def _extract_filing_text(html):
    """Parse filing HTML and return plain text in reading order.

    Strips inline-XBRL noise before extraction: ix:hidden/ix:header blocks
    (raw XBRL fact values), scripts, styles, and display:none elements.
    Normalizes unicode/non-breaking spaces so heading regexes match.
    """
    import warnings

    # Some filers split words across inline spans mid-word ("RIS"+"K FACTORS"),
    # so we must extract with NO separator to rejoin them — and instead mark
    # block boundaries explicitly with newlines before parsing.
    html = re.sub(r"(?i)(</(?:p|div|tr|li|h[1-6]|table|section)>)", r"\1\n", html)
    html = re.sub(r"(?i)<br\s*/?>", "\n", html)

    parser = "lxml" if _LXML_AVAILABLE else "html.parser"
    with warnings.catch_warnings():
        # Inline-XBRL docs carry an XML declaration; the HTML parser is intentional
        warnings.simplefilter("ignore")
        soup = _BeautifulSoup(html, parser)

    for tag in soup.find_all(["script", "style", "ix:hidden", "ix:header"]):
        tag.decompose()
    for tag in soup.find_all(style=_HIDDEN_STYLE_RE):
        tag.decompose()

    text = soup.get_text(separator="")
    # Normalize &nbsp;/unicode spaces, collapse whitespace runs
    text = re.sub("[\u00a0\u1680\u2000-\u200b\u202f\u205f\u3000\ufeff]", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n(\s*\n)+", "\n\n", text)
    return text.strip()


def _find_section_spans(text):
    """Locate section start offsets in extracted filing text.

    Returns ordered list of (section_key, start_offset).

    Constraint handled here: heading strings also appear in the Table of
    Contents, "Part II" divider mini-TOCs, and running page headers — all
    followed almost immediately by the next heading. So we require chosen
    matches to (a) be followed by substantial content before the next
    detected heading, (b) fall past the TOC region when possible, and
    (c) form a monotonically increasing sequence in item order.
    """
    import bisect

    per_key = {}
    all_positions = []
    for key in SECTION_LABELS:
        pattern = _SECTION_PATTERNS.get(key)
        if pattern is None:
            continue
        positions = [m.start() for m in pattern.finditer(text)]
        per_key[key] = positions
        all_positions.extend(positions)
    all_positions.sort()

    def _gap_after(p):
        """Chars between this match and the next detected heading (any key)."""
        i = bisect.bisect_right(all_positions, p)
        return (all_positions[i] - p) if i < len(all_positions) else len(text) - p

    # TOC / divider rows list the next item heading within a line; a real
    # section heading is followed by ~200+ words (~1200 chars) of content.
    min_gap = 1200
    # TOC + cover page live in the first few percent of the text; cap the
    # cutoff absolutely so huge filings don't skip a legitimate early Item 1.
    toc_cutoff = min(int(len(text) * 0.05), 50_000)

    spans = []
    last_pos = -1
    for key in SECTION_LABELS:
        positions = [p for p in per_key.get(key, []) if p > last_pos]
        if not positions:
            continue
        substantial = [p for p in positions if _gap_after(p) >= min_gap]
        viable = [p for p in substantial if p > toc_cutoff] or substantial
        if viable:
            pos = viable[0]
        else:
            pos = positions[-1]  # all matches trivial — last is likeliest body
        spans.append((key, pos))
        last_pos = pos
    return spans


def _find_latest_10k(cik):
    """Search the full submissions index for the most recent 10-K / 10-K/A.

    Frequent 8-K filers push the 10-K out of small get_recent_filings()
    windows, so this scans ALL recent forms, filtered by type.
    Returns {form, date, document, description, url} or None.
    """
    cik_padded = str(cik).zfill(10)
    url = SUBMISSIONS_URL.format(cik=cik_padded)

    http = httpx.Client(headers=EDGAR_HEADERS, timeout=15)
    try:
        resp = http.get(url)
        if resp.status_code != 200:
            print(f"[edgar] _find_latest_10k: submissions API returned {resp.status_code}")
            return None

        recent = resp.json().get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        docs = recent.get("primaryDocument", [])
        descriptions = recent.get("primaryDocDescription", [])
        accessions = recent.get("accessionNumber", [])

        for i in range(len(forms)):
            if forms[i] not in ("10-K", "10-K/A"):
                continue
            accession = accessions[i] if i < len(accessions) else ""
            doc = docs[i] if i < len(docs) else ""
            if not (accession and doc):
                continue
            acc_no_dashes = accession.replace("-", "")
            return {
                "form": forms[i],
                "date": dates[i] if i < len(dates) else "",
                "document": doc,
                "description": descriptions[i] if i < len(descriptions) else "",
                "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_no_dashes}/{doc}",
            }
        return None
    except Exception as e:
        print(f"[edgar] _find_latest_10k: failed — {e}")
        return None
    finally:
        http.close()


def fetch_10k_sections(cik, filings):
    """Fetch and extract key sections from the most recent 10-K filing.

    Takes the filings list from get_recent_filings() and finds the most
    recent 10-K or 10-K/A — falling back to a direct submissions-index
    search when the provided window is too small. Streams the HTML
    (inline-XBRL filings run 5-30 MB), strips XBRL noise, and splits the
    plain text into the sections in SECTION_LABELS via heading-pattern
    matching. Falls back to a single full_text section if fewer than 2
    sections are detected.

    Returns dict:
        {fiscal_year, form_type, filed_date, url,
         sections: [{section_key, section_label, content, word_count}]}
    Returns None on any failure (non-fatal).
    """
    if not _BS4_AVAILABLE:
        print("[edgar] fetch_10k_sections: BeautifulSoup not available — skipping")
        return None

    # Find most recent 10-K or 10-K/A in filings list
    target = None
    for f in filings or []:
        if f.get("form") in ("10-K", "10-K/A") and f.get("url"):
            target = f
            break

    if not target:
        # Frequent 8-K filers push the 10-K past the caller's filings window
        print("[edgar] no 10-K in provided filings — searching deeper")
        target = _find_latest_10k(cik)

    if not target:
        print("[edgar] fetch_10k_sections: no 10-K filing with URL found")
        return None

    filing_url = target["url"]
    filed_date = target.get("date", "")
    form_type = target.get("form", "10-K")

    # A 10-K filed Jan-Jun almost always covers the PRIOR fiscal year
    fiscal_year = filed_date[:4] if filed_date else ""
    if len(filed_date) >= 7:
        year, month = int(filed_date[:4]), int(filed_date[5:7])
        fiscal_year = str(year - 1) if month <= 6 else str(year)

    print(f"[edgar] Fetching 10-K sections from {filing_url}...")

    try:
        html_headers = dict(EDGAR_HEADERS)
        html_headers["Accept"] = "text/html,application/xhtml+xml"
        http = httpx.Client(headers=html_headers, timeout=60, follow_redirects=True)
        try:
            with http.stream("GET", filing_url) as resp:
                if resp.status_code != 200:
                    print(f"[edgar] fetch_10k_sections: HTTP {resp.status_code} — skipping")
                    return None
                chunks = []
                total = 0
                for chunk in resp.iter_bytes():
                    total += len(chunk)
                    if total > _MAX_10K_BYTES:
                        print(f"[edgar] fetch_10k_sections: filing too large "
                              f"(>{_MAX_10K_BYTES // (1024 * 1024)} MB) — skipping")
                        return None
                    chunks.append(chunk)
        finally:
            http.close()
        html = b"".join(chunks).decode("utf-8", errors="replace")
        del chunks
    except Exception as e:
        print(f"[edgar] fetch_10k_sections: fetch failed — {e}")
        return None

    try:
        text = _extract_filing_text(html)
    except Exception as e:
        print(f"[edgar] fetch_10k_sections: parse failed — {e}")
        return None
    del html

    total_words = len(text.split())
    if total_words < 2000:
        # Almost certainly a wrapper/index page, not the actual 10-K
        print(f"[edgar] fetch_10k_sections: only {total_words} words extracted "
              f"— likely a wrapper page, skipping")
        return None

    spans = _find_section_spans(text)
    sections = []

    for i, (key, start) in enumerate(spans):
        end = spans[i + 1][1] if i + 1 < len(spans) else len(text)
        content = text[start:end].strip()
        words = content.split()
        word_count = len(words)
        if word_count < 100:
            # Trivial span — probably a stray TOC/cross-reference match
            continue
        if word_count > _MAX_SECTION_WORDS:
            content = " ".join(words[:_MAX_SECTION_WORDS])
            word_count = _MAX_SECTION_WORDS

        sections.append({
            "section_key": key,
            "section_label": SECTION_LABELS[key],
            "content": content,
            "word_count": word_count,
        })
        print(f"[edgar]   {key} ({SECTION_LABELS[key]}): {word_count} words")

    if len(sections) < 2:
        # Sectioning failed — a searchable whole filing beats nothing
        print(f"[edgar] fetch_10k_sections: only {len(sections)} section(s) detected "
              f"— falling back to full-text capture")
        words = text.split()
        if len(words) > _MAX_SECTION_WORDS:
            text = " ".join(words[:_MAX_SECTION_WORDS])
        sections = [{
            "section_key": "full_text",
            "section_label": "Full 10-K Text",
            "content": text,
            "word_count": min(len(words), _MAX_SECTION_WORDS),
        }]

    print(f"[edgar] 10-K sections extracted: {len(sections)} sections "
          f"({form_type}, filed {filed_date})")
    return {
        "fiscal_year": fiscal_year,
        "form_type": form_type,
        "filed_date": filed_date,
        "url": filing_url,
        "sections": sections,
    }
