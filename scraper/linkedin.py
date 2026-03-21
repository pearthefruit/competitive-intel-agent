"""
LinkedIn job scraper using the guest API (no login required).
Adapted from JobDiscovery — stripped of Flask/config dependencies.

Extracts metadata from SERP cards first, then enriches with detail page if available.
Falls back to SERP-only data when detail pages return 400/429.
"""

import re
import json
import time
import httpx
from bs4 import BeautifulSoup
from urllib.parse import urlencode

GUEST_API = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
GUEST_JOB_DETAIL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

REQUEST_TIMEOUT = 10


class LinkedInScraper:
    """Scrapes LinkedIn job listings via the unauthenticated Guest API."""

    def __init__(self):
        self.client = httpx.Client(
            headers=REQUEST_HEADERS,
            timeout=REQUEST_TIMEOUT,
            follow_redirects=True,
        )

    def scrape(self, url, company_name):
        """Scrape LinkedIn for jobs matching the company name.

        url: LinkedIn search URL (with keywords param) or just a search query string.
        company_name: Used for logging only.
        Returns list of job dicts matching the ATS scraper interface.
        """
        print(f"[linkedin] Searching LinkedIn for {company_name} jobs...")

        # Fetch SERP cards (up to 100 jobs across 4 pages)
        serp_jobs = self._fetch_serp_cards(url)
        print(f"[linkedin] Found {len(serp_jobs)} job card(s)")

        if not serp_jobs:
            return []

        # Enrich each card with detail page data
        jobs = []
        detail_failures = 0
        for i, serp_data in enumerate(serp_jobs, 1):
            job_url = serp_data["url"]

            try:
                print(f"  [{i}/{len(serp_jobs)}] Fetching: {serp_data.get('title', 'Unknown')[:50]}...")
                detail = self._fetch_job_detail(job_url)
                if detail and detail.get("title"):
                    # Merge: detail wins, SERP fills gaps
                    job_data = {**serp_data, **{k: v for k, v in detail.items() if v}}
                    jobs.append(job_data)
                else:
                    # Detail fetch failed — use SERP card data (no description)
                    detail_failures += 1
                    jobs.append(serp_data)

                # Pause between requests to reduce 429s
                if i < len(serp_jobs):
                    time.sleep(1.5)

            except Exception as e:
                print(f"  [error] Failed to fetch {job_url[:60]}: {e}")
                jobs.append(serp_data)  # Still save SERP data

        if detail_failures:
            print(f"[linkedin] {detail_failures} jobs saved with SERP-only data (detail pages blocked)")

        # Normalize to match ATS scraper output format
        normalized = []
        for job in jobs:
            normalized.append({
                "title": job.get("title"),
                "department": None,  # LinkedIn doesn't provide department
                "location": job.get("location"),
                "url": job.get("url"),
                "description": job.get("description") or "",
                "salary": job.get("salary"),
                "date_posted": job.get("posted_date"),
            })

        return normalized

    def _fetch_serp_cards(self, search_url):
        """Fetch job cards from LinkedIn SERP pages. Returns list of card dicts."""
        all_cards = []
        seen_urls = set()

        # Extract keywords from URL or use it as-is
        if "keywords=" in search_url:
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(search_url)
            params = parse_qs(parsed.query)
            keywords = params.get("keywords", [""])[0]
        else:
            keywords = search_url  # Treat as raw search term

        for start in range(0, 100, 25):
            api_params = {"keywords": keywords, "start": str(start)}
            api_url = f"{GUEST_API}?{urlencode(api_params)}"

            try:
                response = self.client.get(api_url)
                if response.status_code != 200:
                    break

                soup = BeautifulSoup(response.text, "html.parser")
                cards = soup.find_all("div", class_=lambda c: c and "base-card" in c)
                if not cards:
                    cards = soup.find_all("li")
                if not cards:
                    break

                page_count = 0
                for card in cards:
                    card_data = self._parse_serp_card(card)
                    if card_data and card_data["url"] not in seen_urls:
                        seen_urls.add(card_data["url"])
                        all_cards.append(card_data)
                        page_count += 1

                print(f"  Page {start // 25 + 1}: {page_count} cards")

            except Exception as e:
                print(f"  [error] LinkedIn API error at offset {start}: {e}")
                break

        return all_cards

    def _parse_serp_card(self, card):
        """Extract metadata from a single LinkedIn SERP job card."""
        link = card.find("a", class_=lambda c: c and "base-card__full-link" in c)
        if not link:
            link = card.find("a", href=lambda h: h and "/jobs/view/" in h)
        if not link:
            return None

        href = link.get("href", "")
        if "/jobs/view/" not in href:
            return None

        clean_url = href.split("?")[0]
        if not clean_url.startswith("http"):
            clean_url = "https://www.linkedin.com" + clean_url

        title = None
        title_el = card.find("h3", class_=lambda c: c and "base-search-card__title" in c)
        if not title_el:
            title_el = card.find("span", class_=lambda c: c and "sr-only" in c)
        if not title_el:
            title_el = link
        if title_el:
            title = title_el.get_text(strip=True)

        company = None
        company_el = card.find("h4", class_=lambda c: c and "base-search-card__subtitle" in c)
        if not company_el:
            company_el = card.find("a", class_=lambda c: c and "hidden-nested-link" in c)
        if company_el:
            company = company_el.get_text(strip=True)

        location = None
        loc_el = card.find("span", class_=lambda c: c and "job-search-card__location" in c)
        if loc_el:
            location = loc_el.get_text(strip=True)

        salary = None
        salary_el = card.find("span", class_=lambda c: c and "job-search-card__salary-info" in c)
        if salary_el:
            salary = salary_el.get_text(strip=True)

        date_el = card.find("time")
        posted_date = date_el.get("datetime", "") if date_el else ""

        if not title:
            return None

        return {
            "url": clean_url,
            "title": title,
            "company": company,
            "location": location,
            "salary": salary,
            "description": "",
            "posted_date": posted_date,
        }

    def _fetch_job_detail(self, job_url):
        """Fetch job details. Tries direct page (JSON-LD), then guest API."""
        # Strategy 1: Direct page fetch
        try:
            response = self.client.get(job_url)
            if response.status_code == 200 and len(response.text) > 500:
                result = self._parse_detail_html(response.text, job_url)
                if result and result.get("description"):
                    return result
        except Exception:
            pass

        # Strategy 2: Guest API detail endpoint
        job_id = job_url.rstrip("/").split("/")[-1]
        try:
            detail_url = GUEST_JOB_DETAIL.format(job_id=job_id)
            response = self.client.get(detail_url)
            if response.status_code == 200 and len(response.text) > 500:
                return self._parse_detail_html(response.text, job_url)
        except Exception:
            pass

        return None

    def _parse_detail_html(self, html, job_url):
        """Parse LinkedIn job detail HTML for structured data."""
        soup = BeautifulSoup(html, "html.parser")

        title = None
        company = None
        location = None
        salary = None
        description = None

        # Try JSON-LD first (most reliable)
        script_tag = soup.find("script", type="application/ld+json")
        if script_tag:
            try:
                data = json.loads(script_tag.string)
                title = data.get("title")

                location_data = data.get("jobLocation", {})
                if isinstance(location_data, dict):
                    addr = location_data.get("address", {})
                    if isinstance(addr, dict):
                        parts = [addr.get("addressLocality", ""), addr.get("addressRegion", "")]
                        location = ", ".join(p for p in parts if p)
                elif isinstance(location_data, list) and location_data:
                    addr = location_data[0].get("address", {})
                    parts = [addr.get("addressLocality", ""), addr.get("addressRegion", "")]
                    location = ", ".join(p for p in parts if p)

                org = data.get("hiringOrganization", {})
                if isinstance(org, dict):
                    company = org.get("name")

                salary_data = data.get("baseSalary", {})
                if isinstance(salary_data, dict):
                    value = salary_data.get("value", {})
                    if isinstance(value, dict):
                        min_v = value.get("minValue", "")
                        max_v = value.get("maxValue", "")
                        unit = value.get("unitText", "YEAR")
                        if min_v and max_v:
                            salary = f"${min_v:,} - ${max_v:,}/{unit.lower()}"
                        elif min_v:
                            salary = f"${min_v:,}/{unit.lower()}"
            except (json.JSONDecodeError, AttributeError):
                pass

        # Fallback to HTML parsing
        if not title:
            title_el = soup.find("h2", class_=lambda c: c and "title" in c if c else False)
            if not title_el:
                title_el = soup.find("h1")
            if title_el:
                title = title_el.get_text(strip=True)

        if not company:
            company_el = soup.find("a", class_=lambda c: c and "org-name" in c if c else False)
            if not company_el:
                company_el = soup.find("a", class_=lambda c: c and "company" in c.lower() if c else False)
            if company_el:
                company = company_el.get_text(strip=True)

        if not location:
            loc_el = soup.find("span", class_=lambda c: c and "bullet" in c if c else False)
            if loc_el:
                location = loc_el.get_text(strip=True)

        if not description:
            desc_el = soup.find("div", class_=lambda c: c and "description" in c if c else False)
            if not desc_el:
                desc_el = soup.find("section", class_=lambda c: c and "description" in c if c else False)
            if desc_el:
                description = desc_el.get_text(separator="\n\n", strip=True)

        return {
            "url": job_url,
            "title": title,
            "company": company,
            "location": location,
            "salary": salary,
            "description": description or "",
        }

    def close(self):
        self.client.close()
