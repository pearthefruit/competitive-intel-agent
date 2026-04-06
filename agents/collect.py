"""Agent 1: Data Collection — scrape all open roles from all available sources."""

import re
from urllib.parse import urlencode

from scraper.ats_api import detect_ats_type, GreenhouseScraper, LeverScraper, AshbyScraper
from scraper.linkedin import LinkedInScraper
from scraper.workday import WorkdayScraper
from scraper.detect import detect_ats_board
from scraper.custom_api import CUSTOM_REGISTRY
from db import init_db, get_connection, upsert_company, insert_job


SCRAPERS = {
    'greenhouse': GreenhouseScraper,
    'lever': LeverScraper,
    'ashby': AshbyScraper,
    'workday': WorkdayScraper,
    'linkedin': LinkedInScraper,
}

# Add custom company-specific scrapers (Amazon, Jane Street, etc.)
for _key, _entry in CUSTOM_REGISTRY.items():
    SCRAPERS[_key] = _entry["scraper"]

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
    """Scrape all open roles from all available sources and save to DB.

    When no URL is provided, auto-detects ALL ATS boards for the company
    and collects from each. Deduplicates across sources by URL and normalized title.
    Returns (new_count, skipped_count).
    """
    init_db(db_path)

    # Explicit URL mode — scrape single source
    if url:
        ats_type = detect_ats_type(url)
        if not ats_type:
            print(f"[error] Could not detect ATS type from URL: {url}")
            print("       Supported: Greenhouse, Lever, Ashby, Workday, LinkedIn")
            return 0, 0
        boards = [(ats_type, url, 0)]
    else:
        # Auto-detect ALL boards
        from scraper.detect import detect_all_boards
        boards = detect_all_boards(company_name)
        if not boards:
            print(f"[error] Could not find any job boards for '{company_name}'")
            print("       Try providing the URL directly with --url")
            return 0, 0

    conn = get_connection(db_path)
    # Use first board's info for company record
    primary_ats = boards[0][0] if boards else None
    primary_url = boards[0][1] if boards else None
    company_id = upsert_company(conn, company_name, primary_url, primary_ats)

    total_new = 0
    total_skipped = 0
    existing_titles = _get_existing_titles(conn, company_id)

    for ats_type, board_url, _ in boards:
        scraper_cls = SCRAPERS.get(ats_type)
        if not scraper_cls:
            print(f"[collect] No scraper for ATS type: {ats_type}, skipping")
            continue

        print(f"[collect] Scraping {company_name} via {ats_type}...")
        scraper = scraper_cls()
        try:
            jobs = scraper.scrape(board_url, company_name)
        except Exception as e:
            print(f"[collect] {ats_type} scrape failed: {e}")
            continue
        finally:
            scraper.close()

        new_count = 0
        skipped = 0
        for job in jobs:
            # Cross-source dedup by normalized title
            norm_title = _normalize_title(job.get("title", ""))
            if norm_title and norm_title in existing_titles:
                skipped += 1
                continue

            inserted = insert_job(conn, company_id, job, source_board=board_url)
            if inserted:
                new_count += 1
                if norm_title:
                    existing_titles.add(norm_title)
            else:
                skipped += 1

        print(f"[collect] {ats_type}: +{new_count} new ({skipped} duplicates)")
        total_new += new_count
        total_skipped += skipped

    conn.close()
    print(f"[collect] Total: {total_new} new jobs across {len(boards)} source(s) ({total_skipped} skipped)")
    return total_new, total_skipped
