"""ProPublica Nonprofit Explorer API — IRS Form 990 data for nonprofits.

Free API, no authentication required.
Docs: https://projects.propublica.org/nonprofits/api
"""

import difflib
import re
import unicodedata

import httpx

_BASE = "https://projects.propublica.org/nonprofits/api/v2"
_HEADERS = {"User-Agent": "SignalVault/1.0 (competitive intelligence tool)"}
_TIMEOUT = 15

# ── Match verification ────────────────────────────────────────────────────────
# ProPublica's search is fuzzy full-text over ~1.8M organisations, so it returns
# *something* for almost any query. Taking the top hit unverified produced a
# 0-for-11 record on this database: Samsung matched Samsung Presbyterian Church,
# SpaceX matched Maker Spacex, and Aslan Protects matched The Aslan Project Inc,
# whose 990 then supplied that company's entire reported financials.
#
# The cost here is asymmetric. A missed 990 degrades to web search; a wrong one
# attributes another organisation's finances to the company and corrupts every
# downstream score. So verification is deliberately strict and false negatives
# are the accepted failure mode.

MIN_NAME_SIMILARITY = 0.85

# Legal-form suffixes, safe to ignore when comparing.
_LEGAL_SUFFIX = r'\b(inc|incorporated|llc|ltd|limited|corp|corporation|co|plc|sa|nv|ag|gmbh|lp|llp)\b'

# Words denoting a DIFFERENT kind of organisation. A corporate foundation is a
# separate legal and financial entity from the corporation that endowed it, and
# is the single nastiest false positive class — "Dow Jones" vs "Dow Jones
# Foundation" scores 1.00 on name similarity once you normalise the suffix away.
_ENTITY_TYPE_WORDS = {
    "foundation", "trust", "fund", "church", "society", "association",
    "ministries", "charities", "charity", "institute", "alumni",
    "endowment", "auxiliary", "chapter", "club", "league",
}


def _normalize_org_name(name):
    # Fold accents first. Without this the [^a-z0-9] strip cuts accented letters
    # out mid-word, so "Nestlé" becomes "nestl" and European names silently stop
    # matching themselves.
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r'^\s*the\b', ' ', s)
    s = re.sub(_LEGAL_SUFFIX, ' ', s)
    s = re.sub(r'[^a-z0-9 ]', ' ', s)
    return ' '.join(s.split())


def verify_nonprofit_match(company, org_name, min_similarity=MIN_NAME_SIMILARITY):
    """Decide whether a ProPublica hit really is the company. Returns (ok, reason).

    Three independent gates, because no single one catches everything:

    1. Every significant token of the company name must appear in the org name.
       Character similarity alone is not enough — "Aslan Protects" vs "Aslan
       Project" scores 0.89 because *protects* and *project* nearly rhyme, yet
       they are unrelated organisations. Token identity is not fooled by that.
    2. The org must not introduce an entity-type word the company lacks, which
       is what separates a company from its charitable foundation.
    3. Character similarity must still clear the threshold, which catches the
       leftovers like "SpaceX" vs "Maker Spacex" that pass the token test
       because the query is a single word.
    """
    a, b = _normalize_org_name(company), _normalize_org_name(org_name)
    if not a or not b:
        return False, "empty name"

    a_tokens, b_tokens = set(a.split()), set(b.split())

    missing = a_tokens - b_tokens
    if missing:
        return False, f"company tokens absent from org name: {', '.join(sorted(missing))}"

    extra_entity = (b_tokens - a_tokens) & _ENTITY_TYPE_WORDS
    if extra_entity:
        return False, f"different entity type: {', '.join(sorted(extra_entity))}"

    sim = difflib.SequenceMatcher(None, a, b).ratio()
    if sim < min_similarity:
        return False, f"name similarity {sim:.2f} below {min_similarity}"

    return True, f"verified (similarity {sim:.2f})"


def search_nonprofit(name, state=None, verify=True, max_candidates=10):
    """Search ProPublica Nonprofit Explorer by name, returning only a verified match.

    Returns dict with {ein, name, city, state, ntee_code, match_reason} or None.

    Scans the top results rather than blindly trusting the first — the correct
    organisation is not always ranked first, and the first is very often an
    unrelated charity that merely shares a word. Every candidate must pass
    verify_nonprofit_match(); if none does, this returns None and the caller
    falls back to web search, which is the safe direction to fail.

    Pass verify=False only for exploratory tooling, never for analysis.
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

        def _pack(org, reason):
            return {
                "ein": org.get("ein"),
                "strein": org.get("strein"),
                "name": org.get("name"),
                "city": org.get("city"),
                "state": org.get("state"),
                "ntee_code": org.get("ntee_code"),
                "match_reason": reason,
            }

        if not verify:
            return _pack(orgs[0], "unverified")

        rejected = []
        for org in orgs[:max_candidates]:
            ok, reason = verify_nonprofit_match(name, org.get("name"))
            if ok:
                print(f"[nonprofit] Verified match for {name!r}: "
                      f"{org.get('name')!r} — {reason}")
                return _pack(org, reason)
            rejected.append(f"{org.get('name')!r} ({reason})")

        # Logged loudly: a silent no-match looks identical to "not a nonprofit",
        # and the difference matters when debugging a missing financial source.
        print(f"[nonprofit] No verified match for {name!r} among "
              f"{len(orgs[:max_candidates])} candidate(s); rejected: "
              + "; ".join(rejected[:3]))
        return None
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
    """Format a 990 dollar amount in the shared magnitude-suffixed format.

    990 figures arrive as raw dollars. Emitting them that way put '$501,098'
    into a report that otherwise talks in $M/$B, and the model rendered it as
    '$501.1M' — off by 1000x. Scale is knowable here, so it is resolved here.
    """
    from scraper.money import format_money
    return format_money(value)


def _safe_sub(a, b):
    """Subtract b from a, returning None if either is None."""
    if a is None or b is None:
        return None
    try:
        return int(a) - int(b)
    except (ValueError, TypeError):
        return None
