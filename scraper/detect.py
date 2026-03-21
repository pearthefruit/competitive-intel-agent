"""Auto-detect a company's ATS board by probing known URL patterns.
Falls back to LinkedIn search when no dedicated ATS board is found."""

import re
import httpx
from bs4 import BeautifulSoup
from urllib.parse import urlencode

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


def detect_ats_board(company_name):
    """Probe ATS APIs to find a company's job board.

    Returns (ats_type, board_url, job_count) or (None, None, 0) if not found.
    """
    slugs = _generate_slugs(company_name)
    http = httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=8,
        follow_redirects=True,
    )

    print(f"[detect] Searching for {company_name}'s job board...")
    print(f"[detect] Trying slugs: {', '.join(slugs)}")

    for probe in ATS_PROBES:
        for slug in slugs:
            url = probe["url"].format(slug=slug)
            try:
                resp = http.get(url)
                if probe["check"](resp):
                    # Count jobs from the response
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
                    http.close()
                    return probe["ats"], board_url, job_count
            except httpx.TimeoutException:
                continue
            except Exception:
                continue

    # Fallback: search LinkedIn for the company's jobs
    print(f"[detect] No ATS board found, trying LinkedIn...")
    linkedin_result = _probe_linkedin(company_name, http)
    http.close()

    if linkedin_result:
        return linkedin_result

    print(f"[detect] No jobs found for '{company_name}' on any platform")
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
