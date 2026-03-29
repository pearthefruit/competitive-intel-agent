"""ProPublica Nonprofit Explorer API — IRS Form 990 data for nonprofits.

Free API, no authentication required.
Docs: https://projects.propublica.org/nonprofits/api
"""

import httpx

_BASE = "https://projects.propublica.org/nonprofits/api/v2"
_HEADERS = {"User-Agent": "SignalVault/1.0 (competitive intelligence tool)"}
_TIMEOUT = 15


def search_nonprofit(name, state=None):
    """Search ProPublica Nonprofit Explorer by name.

    Returns dict with {ein, name, city, state, ntee_code} or None.
    """
    params = {"q": name}
    if state:
        params["state[id]"] = state.upper()

    try:
        resp = httpx.get(f"{_BASE}/search.json", params=params,
                         headers=_HEADERS, timeout=_TIMEOUT)
        if resp.status_code != 200:
            print(f"[nonprofit] Search failed: HTTP {resp.status_code}")
            return None

        data = resp.json()
        orgs = data.get("organizations", [])
        if not orgs:
            return None

        top = orgs[0]
        return {
            "ein": top.get("ein"),
            "strein": top.get("strein"),
            "name": top.get("name"),
            "city": top.get("city"),
            "state": top.get("state"),
            "ntee_code": top.get("ntee_code"),
        }
    except Exception as e:
        print(f"[nonprofit] Search error: {e}")
        return None


def get_nonprofit_financials(ein):
    """Get Form 990 filing data for a nonprofit by EIN.

    Returns dict with organization info + list of filings with financial data,
    or None if no filings found.
    """
    try:
        resp = httpx.get(f"{_BASE}/organizations/{ein}.json",
                         headers=_HEADERS, timeout=_TIMEOUT)
        if resp.status_code != 200:
            print(f"[nonprofit] Org lookup failed: HTTP {resp.status_code}")
            return None

        data = resp.json()
        org = data.get("organization", {})
        filings = data.get("filings_with_data", [])

        if not filings:
            return None

        return {
            "organization": {
                "name": org.get("name"),
                "ein": org.get("ein"),
                "city": org.get("city"),
                "state": org.get("state"),
                "ntee_code": org.get("ntee_code"),
                "classification": org.get("classification"),
                "ruling_date": org.get("ruling_date"),
            },
            "filings": filings,
        }
    except Exception as e:
        print(f"[nonprofit] Financials error: {e}")
        return None


def format_990_for_prompt(filing_data):
    """Format ProPublica 990 filing data as structured text for LLM consumption.

    Returns formatted string suitable for injection into financial analysis prompt.
    """
    if not filing_data:
        return ""

    org = filing_data.get("organization", {})
    filings = filing_data.get("filings", [])

    lines = [
        "IRS FORM 990 DATA (Source: ProPublica Nonprofit Explorer)",
        f"Organization: {org.get('name', 'Unknown')}",
        f"EIN: {org.get('ein', 'Unknown')}",
        f"Location: {org.get('city', '?')}, {org.get('state', '?')}",
        f"NTEE Code: {org.get('ntee_code', 'N/A')}",
        "",
        "FINANCIAL HISTORY (from IRS Form 990 filings):",
        f"{'Year':<6} {'Revenue':>15} {'Expenses':>15} {'Assets':>15} {'Liabilities':>15}",
        f"{'-'*6} {'-'*15} {'-'*15} {'-'*15} {'-'*15}",
    ]

    for f in filings[:5]:  # Last 5 years
        year = f.get("tax_prd_yr", "?")
        rev = _fmt_money(f.get("totrevenue"))
        exp = _fmt_money(f.get("totfuncexpns"))
        assets = _fmt_money(f.get("totassetsend"))
        liab = _fmt_money(f.get("totliabend"))
        lines.append(f"{year:<6} {rev:>15} {exp:>15} {assets:>15} {liab:>15}")

    # Most recent filing detail
    latest = filings[0] if filings else {}
    if latest:
        lines.extend([
            "",
            f"LATEST FILING DETAIL (Tax Period: {latest.get('tax_prd_yr', '?')}):",
            f"  Total Revenue: {_fmt_money(latest.get('totrevenue'))}",
            f"  Contributions/Gifts: {_fmt_money(latest.get('totcntrbgfts'))}",
            f"  Investment Income: {_fmt_money(latest.get('invstmntinc'))}",
            f"  Total Expenses: {_fmt_money(latest.get('totfuncexpns'))}",
            f"  Officer Compensation: {_fmt_money(latest.get('compnsatncurrofcr'))}",
            f"  Other Salaries: {_fmt_money(latest.get('othrsalwages'))}",
            f"  Total Assets: {_fmt_money(latest.get('totassetsend'))}",
            f"  Total Liabilities: {_fmt_money(latest.get('totliabend'))}",
            f"  Net Assets: {_fmt_money(_safe_sub(latest.get('totassetsend'), latest.get('totliabend')))}",
        ])

    return "\n".join(lines)


def _fmt_money(value):
    """Format a dollar amount with commas, or 'N/A' if missing."""
    if value is None:
        return "N/A"
    try:
        return f"${int(value):,}"
    except (ValueError, TypeError):
        return str(value)


def _safe_sub(a, b):
    """Subtract b from a, returning None if either is None."""
    if a is None or b is None:
        return None
    try:
        return int(a) - int(b)
    except (ValueError, TypeError):
        return None
