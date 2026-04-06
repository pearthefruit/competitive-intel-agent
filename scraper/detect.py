"""Auto-detect a company's ATS board by probing known URL patterns.
Falls back to Workday probing, then LinkedIn search when no dedicated ATS board is found."""

import re
import httpx
from bs4 import BeautifulSoup
from urllib.parse import urlencode
from scraper.workday import detect_workday
from scraper.custom_api import lookup_custom_scraper

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

# Patterns to try, in order of likelihood. {slug} gets replaced with variations of the company name.
ATS_PROBES = [
    {
        "ats": "greenhouse",
        "url": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
        "check": lambda r: r.status_code == 200 and "jobs" in r.text[:100],
        "board_url": "https://boards.greenhouse.io/{slug}",
    },
    {
        "ats": "lever",
        "url": "https://api.lever.co/v0/postings/{slug}?mode=json&limit=1",
        "check": lambda r: r.status_code == 200 and r.text.startswith("["),
        "board_url": "https://jobs.lever.co/{slug}",
    },
    {
        "ats": "ashby",
        "url": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
        "check": lambda r: r.status_code == 200 and "jobs" in r.text[:100],
        "board_url": "https://jobs.ashbyhq.com/{slug}",
    },
]


def _generate_slugs(company_name):
    """Generate likely URL slugs from a company name.

    e.g. "Palo Alto Networks" -> ["paloaltonetworks", "palo-alto-networks", "paltoaltonetworks", "pan"]
    """
    name = company_name.strip()
    lower = name.lower()

    slugs = []

    # No spaces, no special chars
    slugs.append(re.sub(r"[^a-z0-9]", "", lower))

    # Hyphenated
    slugs.append(re.sub(r"[^a-z0-9]+", "-", lower).strip("-"))

    # Underscored
    slugs.append(re.sub(r"[^a-z0-9]+", "_", lower).strip("_"))

    # As-is lowercase (for single-word companies like "stripe")
    if " " not in name:
        slugs.append(lower)

    # Drop common suffixes
    for suffix in [" inc", " inc.", " co", " co.", " corp", " labs", " ai", " io", " hq"]:
        if lower.endswith(suffix):
            trimmed = lower[: -len(suffix)].strip()
            slugs.append(re.sub(r"[^a-z0-9]", "", trimmed))
            slugs.append(re.sub(r"[^a-z0-9]+", "-", trimmed).strip("-"))

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for s in slugs:
        if s and s not in seen:
            seen.add(s)
            unique.append(s)

    return unique


def detect_all_boards(company_name):
    """Probe ALL ATS APIs to find every job board for a company.

    Returns list of (ats_type, board_url, job_count) tuples.
    """
    boards = []

    # Check custom company APIs first (Amazon, Jane Street, etc.)
    custom = lookup_custom_scraper(company_name)
    if custom:
        registry_key, scraper_cls, detect_url = custom
        print(f"[detect] Known custom API for {company_name} ({registry_key})")
        try:
            resp = httpx.get(
                detect_url,
                headers={"User-Agent": USER_AGENT},
                timeout=8,
                follow_redirects=True,
            )
            if resp.status_code == 200:
                print(f"[detect] Found! Custom API confirmed for {registry_key}")
                boards.append((registry_key, detect_url, 0))
        except Exception:
            pass

    slugs = _generate_slugs(company_name)
    http = httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=8,
        follow_redirects=True,
    )

    print(f"[detect] Searching for ALL job boards for {company_name}...")
    print(f"[detect] Trying slugs: {', '.join(slugs)}")

    found_ats_types = set()
    for probe in ATS_PROBES:
        if probe["ats"] in found_ats_types:
            continue  # Already found a board for this ATS type
        for slug in slugs:
            url = probe["url"].format(slug=slug)
            try:
                resp = http.get(url)
                if probe["check"](resp):
                    try:
                        data = resp.json()
                        if isinstance(data, list):
                            job_count = len(data)
                        elif isinstance(data, dict) and "jobs" in data:
                            job_count = len(data["jobs"])
                        else:
                            job_count = 0
                    except Exception:
                        job_count = 0

                    board_url = probe["board_url"].format(slug=slug)
                    print(f"[detect] Found! {probe['ats'].title()} board: {board_url} ({job_count} jobs)")
                    boards.append((probe["ats"], board_url, job_count))
                    found_ats_types.add(probe["ats"])
                    break  # Found this ATS type, move to next probe
            except httpx.TimeoutException:
                continue
            except Exception:
                continue

    # Probe Workday API (many large companies use Workday)
    print(f"[detect] Trying Workday...")
    wd_url, wd_count = detect_workday(company_name)
    if wd_url and wd_count > 0:
        boards.append(("workday", wd_url, wd_count))

    # Probe LinkedIn
    print(f"[detect] Trying LinkedIn...")
    linkedin_result = _probe_linkedin(company_name, http)
    http.close()
    if linkedin_result:
        boards.append(linkedin_result)

    if boards:
        print(f"[detect] Found {len(boards)} source(s) for {company_name}: {', '.join(b[0] for b in boards)}")
    else:
        print(f"[detect] No jobs found for '{company_name}' on any platform")

    return boards


def detect_ats_board(company_name):
    """Probe ATS APIs to find a company's job board (first match).

    Returns (ats_type, board_url, job_count) or (None, None, 0) if not found.
    Backward-compatible wrapper around detect_all_boards().
    """
    boards = detect_all_boards(company_name)
    if boards:
        return boards[0]
    return None, None, 0


LINKEDIN_GUEST_API = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"


def _probe_linkedin(company_name, http):
    """Probe LinkedIn Guest API to check if the company has job listings.

    Returns (ats_type, search_url, job_count) or None.
    """
    params = {"keywords": company_name}
    api_url = f"{LINKEDIN_GUEST_API}?{urlencode(params)}"

    try:
        resp = http.get(api_url)
        if resp.status_code != 200:
            return None

        soup = BeautifulSoup(resp.text, "html.parser")
        cards = soup.find_all("div", class_=lambda c: c and "base-card" in c)
        if not cards:
            cards = soup.find_all("li")

        if not cards:
            return None

        job_count = len(cards)
        search_url = f"{LINKEDIN_GUEST_API}?{urlencode(params)}"
        print(f"[detect] Found! LinkedIn search: {company_name} ({job_count}+ jobs)")
        return "linkedin", search_url, job_count

    except Exception:
        return None
