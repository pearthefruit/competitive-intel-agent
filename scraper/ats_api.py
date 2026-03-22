"""
ATS JSON API scrapers for Greenhouse, Lever, and Ashby.
Adapted from JobDiscovery — stripped of Flask/DB dependencies, no keyword filtering.
Returns ALL jobs from a board as plain dicts.
"""

import re
import httpx
from urllib.parse import urlparse
from bs4 import BeautifulSoup

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
REQUEST_TIMEOUT = 15

SALARY_PATTERNS = [
    r'\$[\d,]+(?:\.\d{2})?\s+to\s+\$[\d,]+(?:\.\d{2})?',
    r'\$[\d,]+(?:\.\d{2})?\s*[-\u2013]\s*\$[\d,]+(?:\.\d{2})?(?:\s*/\s*(?:yr|year|annually|hr|hour))?',
    r'\$[\d,]+(?:\.\d{2})?\s*/\s*(?:yr|year|annually|hr|hour)',
    r'(?:base\s+)?(?:salary|pay|compensation)\s+(?:range|scale)?[:\s]+\$[\d,]+[^\n]{0,60}',
]


def _extract_salary_from_text(text):
    if not text:
        return None
    for pattern in SALARY_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            result = match.group(0).strip()
            result = re.split(r'(?<!\d)[.;]', result)[0].strip()
            if len(result) > 120:
                result = result[:120] + '...'
            return result
    return None


def _make_client():
    return httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT,
        follow_redirects=True,
    )


def detect_ats_type(url):
    """Detect ATS type from URL pattern. Returns type string or None."""
    url_lower = url.lower()
    if 'greenhouse.io' in url_lower:
        return 'greenhouse'
    if 'lever.co' in url_lower:
        return 'lever'
    if 'ashbyhq.com' in url_lower:
        return 'ashby'
    if 'myworkdayjobs.com' in url_lower or '/wday/cxs/' in url_lower:
        return 'workday'
    return None


# =================== Greenhouse ===================

class GreenhouseScraper:
    API_BASE = "https://boards-api.greenhouse.io/v1/boards"

    def __init__(self):
        self.http = _make_client()

    def _extract_token(self, url):
        parsed = urlparse(url)
        parts = parsed.path.strip('/').split('/')
        for i, part in enumerate(parts):
            if part == 'boards' and i + 1 < len(parts):
                return parts[i + 1]
        if parts and parts[0] not in ('v1', 'boards', ''):
            return parts[0]
        return None

    def scrape(self, url, company_name):
        """Scrape all jobs from a Greenhouse board. Returns list of job dicts."""
        token = self._extract_token(url)
        if not token:
            print(f"  [warn] Could not extract Greenhouse token from {url}")
            return []

        api_url = f"{self.API_BASE}/{token}/jobs?content=true"
        try:
            response = self.http.get(api_url)
            if response.status_code != 200:
                print(f"  [warn] Greenhouse API returned {response.status_code}")
                return []
            data = response.json()
        except Exception as e:
            print(f"  [error] Greenhouse API failed: {e}")
            return []

        jobs_list = data.get('jobs', [])
        results = []
        for job in jobs_list:
            title = job.get('title', '')
            location = ''
            loc_obj = job.get('location')
            if loc_obj and isinstance(loc_obj, dict):
                location = loc_obj.get('name', '')

            content_html = job.get('content', '')
            description = ''
            if content_html:
                soup = BeautifulSoup(content_html, 'html.parser')
                description = soup.get_text(separator='\n\n', strip=True)

            department = ''
            dept_list = job.get('departments', [])
            if dept_list and isinstance(dept_list, list):
                department = dept_list[0].get('name', '') if dept_list[0] else ''

            results.append({
                'url': job.get('absolute_url', ''),
                'title': title,
                'company': company_name,
                'location': location,
                'department': department,
                'salary': _extract_salary_from_text(description),
                'description': description,
                'date_posted': job.get('updated_at', ''),
            })

        return results

    def close(self):
        self.http.close()


# =================== Lever ===================

class LeverScraper:

    def __init__(self):
        self.http = _make_client()

    def _extract_slug(self, url):
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        path_parts = [p for p in parsed.path.strip('/').split('/') if p]

        if host in ('jobs.lever.co', 'jobs.eu.lever.co'):
            return path_parts[0] if path_parts else None
        if host.endswith('.lever.co'):
            subdomain = host.split('.')[0]
            if subdomain not in ('jobs', 'api', 'www'):
                return subdomain
        return path_parts[0] if path_parts else None

    def _is_eu(self, url):
        return '.eu.lever.co' in url.lower()

    def scrape(self, url, company_name):
        """Scrape all jobs from a Lever board. Returns list of job dicts."""
        slug = self._extract_slug(url)
        if not slug:
            print(f"  [warn] Could not extract Lever slug from {url}")
            return []

        api_host = 'api.eu.lever.co' if self._is_eu(url) else 'api.lever.co'
        api_url = f"https://{api_host}/v0/postings/{slug}?mode=json"
        try:
            response = self.http.get(api_url)
            if response.status_code != 200:
                print(f"  [warn] Lever API returned {response.status_code}")
                return []
            postings = response.json()
        except Exception as e:
            print(f"  [error] Lever API failed: {e}")
            return []

        if not isinstance(postings, list):
            print("  [warn] Lever API returned unexpected format")
            return []

        results = []
        for posting in postings:
            title = posting.get('text', '')
            categories = posting.get('categories', {}) or {}
            location = categories.get('location', '')
            department = categories.get('department', '') or categories.get('team', '')

            salary = None
            salary_range = posting.get('salaryRange')
            if salary_range and isinstance(salary_range, dict):
                sr_min = salary_range.get('min')
                sr_max = salary_range.get('max')
                interval = salary_range.get('interval', 'per-year')
                if sr_min and sr_max:
                    salary = f"${sr_min:,.0f} - ${sr_max:,.0f}/{interval}"
                elif sr_min:
                    salary = f"${sr_min:,.0f}/{interval}"

            description = posting.get('descriptionPlain', '') or ''
            if not salary:
                salary = _extract_salary_from_text(description)

            results.append({
                'url': posting.get('hostedUrl', '') or posting.get('applyUrl', ''),
                'title': title,
                'company': company_name,
                'location': location,
                'department': department,
                'salary': salary,
                'description': description,
                'date_posted': '',
            })

        return results

    def close(self):
        self.http.close()


# =================== Ashby ===================

class AshbyScraper:
    API_BASE = "https://api.ashbyhq.com/posting-api/job-board"

    def __init__(self):
        self.http = _make_client()

    def _extract_board(self, url):
        parsed = urlparse(url)
        path_parts = [p for p in parsed.path.strip('/').split('/') if p]
        if 'job-board' in path_parts:
            idx = path_parts.index('job-board')
            if idx + 1 < len(path_parts):
                return path_parts[idx + 1]
        return path_parts[0] if path_parts else None

    def scrape(self, url, company_name):
        """Scrape all jobs from an Ashby board. Returns list of job dicts."""
        board = self._extract_board(url)
        if not board:
            print(f"  [warn] Could not extract Ashby board from {url}")
            return []

        api_url = f"{self.API_BASE}/{board}?includeCompensation=true"
        try:
            response = self.http.get(api_url)
            if response.status_code != 200:
                print(f"  [warn] Ashby API returned {response.status_code}")
                return []
            data = response.json()
        except Exception as e:
            print(f"  [error] Ashby API failed: {e}")
            return []

        jobs_list = data.get('jobs', [])
        results = []
        for job in jobs_list:
            title = job.get('title', '')
            location = job.get('location', '')
            department = job.get('department', '')
            description = job.get('descriptionPlain', '') or ''

            salary = None
            comp = job.get('compensation')
            if comp and isinstance(comp, dict):
                comp_str = comp.get('compensationTierSummary', '')
                if comp_str:
                    salary = comp_str
            if not salary:
                salary = _extract_salary_from_text(description)

            results.append({
                'url': job.get('jobUrl', ''),
                'title': title,
                'company': company_name,
                'location': location,
                'department': department,
                'salary': salary,
                'description': description,
                'date_posted': '',
            })

        return results

    def close(self):
        self.http.close()
