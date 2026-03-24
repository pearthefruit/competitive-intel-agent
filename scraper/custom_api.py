"""
Custom company-specific careers API scrapers.

Some companies have reverse-engineerable JSON APIs on their careers pages
that return richer data than generic ATS probing. This module provides a
registry of known APIs and scraper classes for each.

Adding a new company:
  1. Create a scraper class with __init__, scrape(url, company_name), close()
  2. Add an entry to CUSTOM_REGISTRY at the bottom of this file
"""

import re
import httpx
from bs4 import BeautifulSoup
from scraper.ats_api import _extract_salary_from_text

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
REQUEST_TIMEOUT = 15
MAX_AMAZON_JOBS = 5000


def _make_client(**extra_headers):
    headers = {"User-Agent": USER_AGENT}
    headers.update(extra_headers)
    return httpx.Client(
        headers=headers,
        timeout=REQUEST_TIMEOUT,
        follow_redirects=True,
    )


# =================== Amazon ===================

class AmazonScraper:
    """Scrape Amazon Jobs via their public search JSON API."""

    API_URL = "https://www.amazon.jobs/en/search.json"

    def __init__(self):
        self.http = _make_client()

    def scrape(self, url, company_name):
        """Scrape all jobs from Amazon's careers API. Returns list of job dicts."""
        results = []
        offset = 0
        page_size = 100

        while offset < MAX_AMAZON_JOBS:
            params = {
                "base_query": "",
                "offset": offset,
                "result_limit": page_size,
                "sort": "recent",
            }
            try:
                resp = self.http.get(self.API_URL, params=params)
                if resp.status_code != 200:
                    print(f"  [warn] Amazon API returned {resp.status_code} at offset {offset}")
                    break
                data = resp.json()
            except Exception as e:
                print(f"  [error] Amazon API failed at offset {offset}: {e}")
                break

            jobs = data.get("jobs", [])
            if not jobs:
                break

            total_hits = data.get("hits", 0)

            for job in jobs:
                title = job.get("title", "")
                job_path = job.get("job_path", "")
                job_url = f"https://www.amazon.jobs{job_path}" if job_path else ""

                location = job.get("normalized_location", "")
                if not location:
                    city = job.get("city", "")
                    country = job.get("country_code", "")
                    location = f"{city}, {country}" if city else country

                description_html = job.get("description", "")
                description = ""
                if description_html:
                    soup = BeautifulSoup(description_html, "html.parser")
                    description = soup.get_text(separator="\n\n", strip=True)

                basic_quals = job.get("basic_qualifications", "")
                preferred_quals = job.get("preferred_qualifications", "")
                if basic_quals:
                    description += f"\n\nBasic Qualifications:\n{basic_quals}"
                if preferred_quals:
                    description += f"\n\nPreferred Qualifications:\n{preferred_quals}"

                salary = _extract_salary_from_text(description)

                results.append({
                    "url": job_url,
                    "title": title,
                    "company": company_name,
                    "location": location,
                    "department": job.get("job_category", ""),
                    "salary": salary,
                    "description": description,
                    "date_posted": job.get("posted_date", ""),
                })

            offset += page_size
            if offset >= total_hits:
                break

            print(f"  [amazon] Fetched {min(offset, total_hits)}/{total_hits} jobs...")

        print(f"  [amazon] Total: {len(results)} jobs scraped")
        return results

    def close(self):
        self.http.close()


# =================== Jane Street ===================

JANE_STREET_CITY_MAP = {
    "NYC": "New York",
    "LDN": "London",
    "HKG": "Hong Kong",
    "SGP": "Singapore",
    "AMT": "Amsterdam",
}


class JaneStreetScraper:
    """Scrape Jane Street jobs via their public JSON APIs."""

    ENDPOINTS = [
        "https://www.janestreet.com/jobs/main.json",
        "https://www.janestreet.com/jobs/internships.json",
    ]

    def __init__(self):
        self.http = _make_client(**{"X-Requested-With": "XMLHttpRequest"})

    def scrape(self, url, company_name):
        """Scrape all jobs from Jane Street's APIs. Returns list of job dicts."""
        results = []
        seen_ids = set()

        for endpoint in self.ENDPOINTS:
            try:
                resp = self.http.get(endpoint)
                if resp.status_code != 200:
                    print(f"  [warn] Jane Street API returned {resp.status_code} for {endpoint}")
                    continue
                jobs = resp.json()
            except Exception as e:
                print(f"  [error] Jane Street API failed for {endpoint}: {e}")
                continue

            if not isinstance(jobs, list):
                print(f"  [warn] Jane Street API returned unexpected format for {endpoint}")
                continue

            for job in jobs:
                job_id = job.get("id")
                if job_id in seen_ids:
                    continue
                seen_ids.add(job_id)

                position = job.get("position", "")
                city_code = job.get("city", "")
                location = JANE_STREET_CITY_MAP.get(city_code, city_code)

                overview_html = job.get("overview", "")
                description = ""
                if overview_html:
                    soup = BeautifulSoup(overview_html, "html.parser")
                    description = soup.get_text(separator="\n\n", strip=True)

                # Build salary from min/max fields
                salary = None
                min_sal = job.get("min_salary")
                max_sal = job.get("max_salary")
                if min_sal and max_sal:
                    salary = f"${min_sal} - ${max_sal}"
                elif min_sal:
                    salary = f"${min_sal}+"
                elif max_sal:
                    salary = f"Up to ${max_sal}"

                job_url = f"https://www.janestreet.com/join-jane-street/position/{job_id}/"

                results.append({
                    "url": job_url,
                    "title": position,
                    "company": company_name,
                    "location": location,
                    "department": job.get("category", "") or job.get("team", ""),
                    "salary": salary,
                    "description": description,
                    "date_posted": "",
                })

        print(f"  [jane street] Total: {len(results)} jobs scraped")
        return results

    def close(self):
        self.http.close()


# =================== Registry ===================

CUSTOM_REGISTRY = {
    "amazon": {
        "scraper": AmazonScraper,
        "detect_url": "https://www.amazon.jobs/en/search.json?result_limit=1",
    },
    "jane street": {
        "scraper": JaneStreetScraper,
        "detect_url": "https://www.janestreet.com/jobs/main.json",
    },
}


def lookup_custom_scraper(company_name):
    """Check if a company has a known custom careers API.

    Returns (registry_key, scraper_cls, detect_url) or None.
    """
    name = company_name.strip().lower()

    # Strip common suffixes
    for suffix in [" inc", " inc.", " co", " co.", " corp", " llc", " ltd"]:
        if name.endswith(suffix):
            name = name[:-len(suffix)].strip()

    for key, entry in CUSTOM_REGISTRY.items():
        # Exact match or substring match in either direction
        if name == key or key in name or name in key:
            return key, entry["scraper"], entry["detect_url"]

    return None
