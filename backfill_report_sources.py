"""Backfill analysis reports (and local job postings) into the source RAG store.

Why this exists
---------------
Source capture shipped ~2026-05-14. Everything analyzed before that wrote a
report to disk and put nothing in the source store, so "Chat with Sources" and
retrieval-first chat find nothing for those companies and quietly fall back to
web search — a failure that looks like success.

Going forward this is handled automatically: ``save_to_dossier()`` indexes every
report as it is written, and ``_capture_hiring_sources()`` indexes postings on
each hiring run. This script is only for seeding a handful of existing companies
so there is something to search today. It is deliberately not a mass migration.

Reports are indexed as ``analysis_report`` — a synthesis tier, slot-capped in
retrieval and badged in the UI, because they are our own LLM output rather than
primary evidence. Only the newest report per (company, analysis_type) stays
indexed; older ones are superseded so chat never arbitrates between two versions
of the same synthesis.

Usage
-----
    python backfill_report_sources.py --dry-run
    python backfill_report_sources.py                    # default 5-company set
    python backfill_report_sources.py --company Uber
    python backfill_report_sources.py --all --limit 20
    python backfill_report_sources.py --skip-hiring

Idempotent: already-indexed reports and postings are detected by dedup key and
skipped, so re-running costs nothing.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import get_connection  # noqa: E402

# Five companies spanning the coverage profiles that stress different paths:
#   HPE           — source-rich with a real 10-K; proves reports yield to
#                   primary evidence instead of crowding it out
#   Window Nation — private, no SEC path; the unverified-web-financials case
#   OpenAI        — zero sources but 720 job postings; stresses the hiring cap
#   Uber          — zero sources, 9 distinct analysis types; widest report mix
#   Danone        — zero sources, 18 analyses over 8 types; exercises supersede
DEFAULT_COMPANIES = [
    "Hewlett Packard Enterprise",
    "Window Nation",
    "OpenAI",
    "Uber",
    "Danone",
]


def _rows(conn, sql, params=()):
    return conn.execute(sql, params).fetchall()


def target_dossiers(conn, companies=None, all_mode=False, limit=None):
    """Resolve the dossiers to process, newest-analysis-first in --all mode."""
    if companies:
        out = []
        for name in companies:
            r = conn.execute(
                "SELECT id, company_name FROM dossiers WHERE lower(company_name) = lower(?)",
                (name,),
            ).fetchone()
            if r:
                out.append((r["id"], r["company_name"]))
            else:
                print(f"  ! no dossier for {name!r} — skipped")
        return out

    if not all_mode:
        return []

    rows = _rows(conn, """
        SELECT d.id, d.company_name, MAX(a.created_at) last_run
          FROM dossiers d
          JOIN dossier_analyses a ON a.dossier_id = d.id
         WHERE a.report_file IS NOT NULL
      GROUP BY d.id
      ORDER BY last_run DESC
    """)
    out = [(r["id"], r["company_name"]) for r in rows]
    return out[:limit] if limit else out


def latest_reports(conn, dossier_id):
    """Newest report per analysis_type — matches the supersede rule."""
    return _rows(conn, """
        SELECT a.analysis_type, a.report_file, MAX(a.created_at) created_at
          FROM dossier_analyses a
         WHERE a.dossier_id = ? AND a.report_file IS NOT NULL
      GROUP BY a.analysis_type
      ORDER BY a.analysis_type
    """, (dossier_id,))


def backfill_reports(conn, dossier_id, company, dry_run=False):
    from agents.source_capture import capture_analysis_report

    added = skipped = missing = 0
    for r in latest_reports(conn, dossier_id):
        path, atype = r["report_file"], r["analysis_type"]
        if not path or not os.path.exists(path):
            print(f"    - {atype:<24} MISSING FILE ({path})")
            missing += 1
            continue
        if dry_run:
            kb = os.path.getsize(path) / 1024
            print(f"    · {atype:<24} would index ({kb:.0f}KB)")
            added += 1
            continue
        try:
            doc_id, is_new = capture_analysis_report(
                conn, dossier_id, company, atype,
                report_file=path,
                report_date=(r["created_at"] or "")[:10] or None,
            )
        except Exception as e:
            print(f"    ! {atype:<24} FAILED: {e}")
            continue
        if is_new:
            print(f"    + {atype:<24} indexed as source {doc_id}")
            added += 1
        else:
            skipped += 1
    if skipped:
        print(f"    ({skipped} already indexed)")
    return added, missing


def backfill_hiring(conn, company, dry_run=False, db_path="intel.db"):
    """Re-index job postings already sitting in the local jobs table."""
    from db import get_company_info, get_all_classified_jobs

    row = conn.execute(
        "SELECT id FROM companies WHERE lower(name) = lower(?)", (company,)
    ).fetchone()
    if not row:
        return 0

    company_id = row["id"]
    jobs = get_all_classified_jobs(conn, company_id)
    if not jobs:
        print("    · hiring: no classified jobs")
        return 0

    if dry_run:
        print(f"    · hiring: would index {len(jobs)} classified postings")
        return len(jobs)

    from agents.analyze import _capture_hiring_sources
    info = get_company_info(conn, company_id)
    _capture_hiring_sources(company, info, jobs, db_path)
    print(f"    + hiring: {len(jobs)} postings processed")
    return len(jobs)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--company", action="append",
                    help="Company name (repeatable). Defaults to the 5-company set.")
    ap.add_argument("--all", action="store_true",
                    help="Every dossier with reports, newest first. Use with --limit.")
    ap.add_argument("--limit", type=int, help="Cap the number of companies")
    ap.add_argument("--skip-hiring", action="store_true",
                    help="Index reports only, leave job postings alone")
    ap.add_argument("--dry-run", action="store_true",
                    help="Report what would be indexed, write nothing")
    ap.add_argument("--db", default="intel.db")
    args = ap.parse_args()

    companies = args.company or (None if args.all else DEFAULT_COMPANIES)
    conn = get_connection(args.db)

    targets = target_dossiers(conn, companies, all_mode=args.all, limit=args.limit)
    if not targets:
        print("Nothing to do.")
        return 0

    mode = "DRY RUN — nothing will be written" if args.dry_run else "writing"
    print(f"Backfilling {len(targets)} companies ({mode})\n")

    tot_reports = tot_missing = tot_jobs = 0
    for dossier_id, company in targets:
        print(f"  {company}")
        added, missing = backfill_reports(conn, dossier_id, company, args.dry_run)
        tot_reports += added
        tot_missing += missing
        if not args.skip_hiring:
            tot_jobs += backfill_hiring(conn, company, args.dry_run, args.db)
        print()

    print("=" * 58)
    print(f"reports indexed : {tot_reports}")
    if tot_missing:
        print(f"missing files   : {tot_missing}")
    if not args.skip_hiring:
        print(f"job postings    : {tot_jobs}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
