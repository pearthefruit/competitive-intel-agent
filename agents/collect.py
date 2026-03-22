"""Agent 1: Data Collection — scrape all open roles from all available sources."""

import re
from urllib.parse import urlencode

from scraper.ats_api import detect_ats_type, GreenhouseScraper, LeverScraper, AshbyScraper
from scraper.linkedin import LinkedInScraper
from scraper.workday import WorkdayScraper
from scraper.detect import detect_ats_board
from db import init_db, get_connection, upsert_company, insert_job


SCRAPERS = {
    'greenhouse': GreenhouseScraper,
    'lever': LeverScraper,
    'ashby': AshbyScraper,
    'workday': WorkdayScraper,
    'linkedin': LinkedInScraper,
}

LINKEDIN_SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"


def _normalize_title(title):
    """Normalize a job title for cross-source deduplication.

    Conservative — only strips noise that varies between platforms
    (remote/hybrid tags, extra whitespace), not meaningful title components.
    """
    if not title:
        return ""
    t = title.lower().strip()
    # Remove parenthetical work-arrangement tags that differ between sources
    t = re.sub(r'\s*\((?:remote|hybrid|onsite|contract|full[- ]?time|part[- ]?time|temporary)\)', '', t, flags=re.IGNORECASE)
    # Collapse whitespace
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def _get_existing_titles(conn, company_id):
    """Get normalized titles for all existing jobs of a company."""
    rows = conn.execute(
        "SELECT title FROM jobs WHERE company_id = ?", (company_id,)
    ).fetchall()
    return {_normalize_title(r["title"]) for r in rows if r["title"]}


def _supplement_with_linkedin(company_name, conn, company_id):
    """Supplement primary ATS data with LinkedIn for additional job coverage.

    Scrapes LinkedIn, deduplicates against existing jobs by normalized title
    and URL, and inserts only genuinely new listings.
    Returns count of new jobs added.
    """
    print(f"\n[collect] Supplementing with LinkedIn...")

    existing_titles = _get_existing_titles(conn, company_id)

    scraper = LinkedInScraper()
    try:
        search_url = f"{LINKEDIN_SEARCH_URL}?{urlencode({'keywords': company_name})}"
        jobs = scraper.scrape(search_url, company_name)
    except Exception as e:
        print(f"[collect] LinkedIn supplement failed: {e}")
        return 0
    finally:
        scraper.close()

    new_count = 0
    deduped = 0
    for job in jobs:
        norm_title = _normalize_title(job.get("title", ""))
        if norm_title and norm_title in existing_titles:
            deduped += 1
            continue

        inserted = insert_job(conn, company_id, job)
        if inserted:
            new_count += 1
            if norm_title:
                existing_titles.add(norm_title)
        else:
            deduped += 1  # URL-based dedup caught it

    print(f"[collect] LinkedIn: +{new_count} unique jobs ({deduped} duplicates filtered)")
    return new_count


def collect(company_name, url=None, db_path="intel.db"):
    """Scrape all open roles and save to DB.

    Scrapes the primary ATS board, then supplements with LinkedIn for
    additional coverage. Deduplicates across sources by URL and normalized title.
    Returns (new_count, skipped_count).
    """
    init_db(db_path)

    # Auto-detect if no URL provided
    if not url:
        ats_type, url, _ = detect_ats_board(company_name)
        if not url:
            print(f"[error] Could not find an ATS board for '{company_name}'")
            print("       Try providing the URL directly with --url")
            return 0, 0
    else:
        ats_type = detect_ats_type(url)
        if not ats_type:
            print(f"[error] Could not detect ATS type from URL: {url}")
            print("       Supported: Greenhouse, Lever, Ashby, Workday, LinkedIn")
            return 0, 0

    scraper_cls = SCRAPERS.get(ats_type)
    if not scraper_cls:
        print(f"[error] No scraper for ATS type: {ats_type}")
        return 0, 0

    print(f"[collect] Scraping {company_name} via {ats_type}...")
    scraper = scraper_cls()
    try:
        jobs = scraper.scrape(url, company_name)
    except Exception as e:
        print(f"[error] Scrape failed: {e}")
        return 0, 0
    finally:
        scraper.close()

    print(f"[collect] Got {len(jobs)} job(s) from {ats_type}")

    conn = get_connection(db_path)
    company_id = upsert_company(conn, company_name, url, ats_type)

    new_count = 0
    skipped = 0
    for job in jobs:
        inserted = insert_job(conn, company_id, job)
        if inserted:
            new_count += 1
        else:
            skipped += 1

    # Supplement with LinkedIn for broader coverage (if primary wasn't already LinkedIn)
    if ats_type != "linkedin":
        linkedin_new = _supplement_with_linkedin(company_name, conn, company_id)
        new_count += linkedin_new

    conn.close()
    print(f"[collect] Total: {new_count} new jobs ({skipped} skipped as duplicates)")
    return new_count, skipped
