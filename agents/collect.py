"""Agent 1: Data Collection — scrape all open roles from an ATS board."""

from scraper.ats_api import detect_ats_type, GreenhouseScraper, LeverScraper, AshbyScraper
from scraper.linkedin import LinkedInScraper
from scraper.detect import detect_ats_board
from db import init_db, get_connection, upsert_company, insert_job


SCRAPERS = {
    'greenhouse': GreenhouseScraper,
    'lever': LeverScraper,
    'ashby': AshbyScraper,
    'linkedin': LinkedInScraper,
}


def collect(company_name, url=None, db_path="intel.db"):
    """Scrape all open roles and save to DB.

    If url is None, auto-detects the ATS board by probing common patterns.
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
            print("       Supported: Greenhouse, Lever, Ashby, LinkedIn")
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

    print(f"[collect] Got {len(jobs)} job(s) from API")

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

    conn.close()
    print(f"[collect] Saved {new_count} new jobs ({skipped} skipped as duplicates)")
    return new_count, skipped
