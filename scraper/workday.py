"""
Workday ATS scraper using the public Workday JSON API.
Ported from JobDiscovery/Crucible — auto-discovers the correct wd instance
and site name, then scrapes jobs without any authentication.
"""

import re
import httpx
from urllib.parse import urlparse
from bs4 import BeautifulSoup

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
PROBE_TIMEOUT = 4   # Short timeout for discovery probes
REQUEST_TIMEOUT = 10
MAX_JOBS = 100       # Max jobs to return per scrape


def _extract_salary(text):
    """Extract salary from description text."""
    if not text:
        return None
    patterns = [
        r'\$[\d,]+(?:\.\d{2})?\s+to\s+\$[\d,]+(?:\.\d{2})?',
        r'\$[\d,]+(?:\.\d{2})?\s*[-\u2013]\s*\$[\d,]+(?:\.\d{2})?(?:\s*/\s*(?:yr|year|annually|hr|hour))?',
        r'\$[\d,]+(?:\.\d{2})?\s*/\s*(?:yr|year|annually|hr|hour)',
        r'(?:base\s+)?(?:salary|pay|compensation)\s+(?:range|scale)?[:\s]+\$[\d,]+[^\n]{0,60}',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            result = match.group(0).strip()
            result = re.split(r'(?<!\d)[.;]', result)[0].strip()
            return result[:120] if len(result) > 120 else result
    return None


def _extract_slug(company_name):
    """Generate a Workday-compatible slug from a company name."""
    if not company_name:
        return None
    return re.sub(r'[^a-z0-9]', '', company_name.lower())


def _generate_site_names(slug):
    """Generate likely Workday site name variations.

    Companies use wildly inconsistent naming: Unilever_Experienced_Professionals,
    AccentureExternal, WalmartExternal, External, etc. We try many patterns.
    """
    cap = slug.capitalize()
    upper = slug.upper()
    names = [
        # Most common patterns
        f'{cap}External',
        f'{upper}External',
        f'{cap}_External',
        f'{cap}Careers',
        f'{cap}_Careers',
        # Experienced/Professional boards (very common for large companies)
        f'{cap}_Experienced_Professionals',
        f'{cap}ExperiencedProfessionals',
        f'{cap}_Experienced',
        f'{cap}_Professional',
        # Generic fallbacks
        'External',
        'External_US',
        'Careers',
        # Job boards
        f'{cap}_Jobs',
        f'{cap}Jobs',
        f'{cap}_Career_Site',
    ]
    # Deduplicate preserving order
    seen = set()
    unique = []
    for n in names:
        if n not in seen:
            seen.add(n)
            unique.append(n)
    return unique


class WorkdayScraper:
    """Scrapes Workday ATS job listings via the public JSON API."""

    def __init__(self):
        self.http = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
            follow_redirects=True,
        )

    def scrape(self, url, company_name):
        """Scrape jobs from a Workday ATS.

        url: Either a discovered API URL (from detect_workday) or a
             myworkdayjobs.com URL to parse directly.
        company_name: Company name for output normalization.
        Returns list of job dicts matching the ATS scraper interface.
        """
        # If url is an API endpoint we already discovered, scrape directly
        if '/wday/cxs/' in url:
            return self._scrape_from_api_url(url, company_name)

        # Otherwise, parse as a myworkdayjobs.com URL
        parsed = urlparse(url)
        if 'myworkdayjobs.com' not in parsed.netloc:
            print(f"  [warn] Not a Workday URL: {url}")
            return []

        return self._scrape_direct_url(url, company_name)

    def _scrape_direct_url(self, url, company_name):
        """Parse a myworkdayjobs.com URL and hit its API."""
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        slug = host.split('.')[0]
        base = f"https://{host}"

        # Extract site name from path
        path_parts = [p for p in parsed.path.strip('/').split('/') if p]
        if path_parts and path_parts[0] not in ('en-US', 'wday'):
            site_names = [path_parts[0]]
        else:
            site_names = _generate_site_names(slug)

        for site_name in site_names:
            api_url = f"{base}/wday/cxs/{slug}/{site_name}/jobs"
            try:
                resp = self.http.post(
                    api_url,
                    json={'appliedFacets': {}, 'limit': 1, 'offset': 0, 'searchText': ''},
                    headers={'Content-Type': 'application/json'},
                    timeout=PROBE_TIMEOUT,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if 'jobPostings' in data and data.get('total', 0) > 0:
                        print(f"[workday] API found at {host}/{site_name} ({data['total']} total jobs)")
                        return self._scrape_jobs(api_url, base, slug, site_name, company_name)
            except Exception:
                continue

        print(f"[workday] Could not find API for {host}")
        return []

    def _scrape_from_api_url(self, api_url, company_name):
        """Scrape using a pre-discovered API URL."""
        # Parse: https://slug.wdN.myworkdayjobs.com/wday/cxs/slug/sitename/jobs
        parts = api_url.split('/wday/cxs/')
        base = parts[0]
        rest = parts[1].split('/')
        slug = rest[0]
        site_name = rest[1]
        return self._scrape_jobs(api_url, base, slug, site_name, company_name)

    def _scrape_jobs(self, api_url, base_url, slug, site_name, company_name):
        """Fetch and normalize jobs from a Workday API endpoint."""
        all_postings = []
        seen_paths = set()

        # Paginate through results (Workday caps at 20 per request)
        offset = 0
        while offset < MAX_JOBS:
            try:
                resp = self.http.post(
                    api_url,
                    json={
                        'appliedFacets': {},
                        'limit': 20,
                        'offset': offset,
                        'searchText': '',
                    },
                    headers={'Content-Type': 'application/json'},
                )
                if resp.status_code != 200:
                    break
                data = resp.json()
                postings = data.get('jobPostings', [])
                if not postings:
                    break
                for p in postings:
                    path = p.get('externalPath', '')
                    if path not in seen_paths:
                        seen_paths.add(path)
                        all_postings.append(p)
                offset += 20
                total = data.get('total', 0)
                if offset >= total:
                    break
            except Exception as e:
                print(f"[workday] Pagination error at offset {offset}: {e}")
                break

        print(f"[workday] {len(all_postings)} unique job(s) found")

        results = []
        for posting in all_postings:
            title = posting.get('title', '')
            location = posting.get('locationsText', '')
            ext_path = posting.get('externalPath', '')

            if not title:
                continue

            job_url = f"{base_url}/en-US/{site_name}{ext_path}"

            # Fetch detail page for description + salary
            salary = None
            description = ''
            try:
                detail_api = f"{base_url}/wday/cxs/{slug}/{site_name}{ext_path}"
                detail_resp = self.http.get(detail_api)
                if detail_resp.status_code == 200:
                    detail = detail_resp.json()
                    job_info = detail.get('jobPostingInfo', {})
                    desc_html = job_info.get('jobDescription', '')
                    if desc_html:
                        desc_soup = BeautifulSoup(desc_html, 'html.parser')
                        description = desc_soup.get_text(separator='\n\n', strip=True)
                        salary = _extract_salary(description)
                    location = job_info.get('location', location)
            except Exception:
                pass  # Keep SERP-level data

            results.append({
                'url': job_url,
                'title': title,
                'company': company_name,
                'location': location,
                'department': None,
                'salary': salary,
                'description': description,
                'date_posted': '',
            })

        return results

    def close(self):
        self.http.close()


def detect_workday(company_name):
    """Probe Workday to find a company's job board.

    Returns (api_url, total_jobs) or (None, 0) if not found.
    """
    slug = _extract_slug(company_name)
    if not slug:
        return None, 0

    site_names = _generate_site_names(slug)

    http = httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=PROBE_TIMEOUT,
        follow_redirects=True,
    )

    print(f"[detect] Probing Workday for '{slug}'...")

    try:
        for wd_num in [5, 1, 2, 3, 4, 101, 102, 103, 104, 105]:
            base = f"https://{slug}.wd{wd_num}.myworkdayjobs.com"
            reachable = None

            for site_name in site_names:
                api_url = f"{base}/wday/cxs/{slug}/{site_name}/jobs"
                try:
                    resp = http.post(
                        api_url,
                        json={'appliedFacets': {}, 'limit': 1, 'offset': 0, 'searchText': ''},
                        headers={'Content-Type': 'application/json'},
                    )
                    reachable = True
                    if resp.status_code == 200:
                        data = resp.json()
                        if 'jobPostings' in data and data.get('total', 0) > 0:
                            total = data['total']
                            print(f"[detect] Found! Workday wd{wd_num}/{site_name} ({total} jobs)")
                            return api_url, total
                except httpx.ConnectError:
                    reachable = False
                    break  # DNS failed — skip this wd number
                except Exception:
                    continue

            if reachable is False:
                continue
    finally:
        http.close()

    return None, 0
