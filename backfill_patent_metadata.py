"""One-shot backfill: populate metadata_json for patent sources captured before
metadata was persisted (title + url + abstract only).

No LLM: metadata (assignee, inventor, dates, CPC) comes from the patent scraper's
search results, matched to stored rows by patent number. The LLM name-variation
step in the patent agent is intentionally skipped — we search the plain company
name (+ wildcard), so patents filed under subsidiary/variant names may remain
unmatched (reported at the end).

Usage:
    python backfill_patent_metadata.py [--dry-run] [--company "Name"]
"""

import argparse
import re

from db import get_connection
from scraper.patents import search_patents, search_patents_with_name


def _patent_number_from_url(url):
    """Extract the patent number token from a Google Patents URL."""
    if not url:
        return None
    m = re.search(r"/patent/([^/?#]+)", url)
    return m.group(1).upper() if m else None


def _clean(v):
    return re.sub(r"<[^>]+>", "", v).strip() if isinstance(v, str) else v


def _build_metadata(p):
    """Same shape the patent agent now writes."""
    cpc = ", ".join(
        (c.get("title") or c.get("id") or "") for c in p.get("cpc_categories", [])
    ).strip(", ")
    number = p.get("number") or p.get("patent_number") or ""
    return {
        k: v for k, v in {
            "patent_number": number,
            "assignee": _clean(p.get("assignee")),
            "inventor": _clean(p.get("inventor")),
            "filing_date": p.get("filing_date"),
            "priority_date": p.get("priority_date"),
            "publication_date": p.get("date") or p.get("publication_date"),
            "status": p.get("status"),
            "type": p.get("type"),
            "uspc_class": p.get("uspc_class"),
            "active_countries": p.get("active_countries"),
            "cpc": cpc or None,
        }.items() if v
    }


def _scrape_company(company):
    """Return {patent_number: patent_dict} for a company, no LLM."""
    found = {}
    for fn, arg in ((search_patents, company), (search_patents_with_name, f"{company}*")):
        try:
            result = fn(arg, 80, "") if fn is search_patents else fn(arg, 80, "")
            pats = result[0] if isinstance(result, tuple) else result
        except Exception as e:
            print(f"    [warn] scrape failed for {arg!r}: {e}")
            continue
        for p in pats or []:
            num = _patent_number_from_url(p.get("url") or p.get("patent_url"))
            if not num:
                num = (p.get("number") or "").upper() or None
            if num and num not in found:
                found[num] = p
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--company", help="backfill a single company")
    args = ap.parse_args()

    conn = get_connection()
    where = "AND d.company_name = ? COLLATE NOCASE" if args.company else ""
    params = (args.company,) if args.company else ()
    companies = conn.execute(
        f"""SELECT d.id, d.company_name, COUNT(*) n
            FROM source_documents sd JOIN dossiers d ON sd.dossier_id = d.id
            WHERE sd.source_type='patent'
              AND (sd.metadata_json IS NULL OR sd.metadata_json='') {where}
            GROUP BY d.id ORDER BY n DESC""",
        params,
    ).fetchall()

    print(f"{sum(r['n'] for r in companies)} metadata-less patents across {len(companies)} companies\n")
    total_filled, total_unmatched = 0, 0

    for did, name, n in companies:
        rows = conn.execute(
            """SELECT id, url FROM source_documents
               WHERE dossier_id=? AND source_type='patent'
                 AND (metadata_json IS NULL OR metadata_json='')""",
            (did,),
        ).fetchall()

        scraped = _scrape_company(name)
        filled = unmatched = 0
        for sid, url in rows:
            num = _patent_number_from_url(url)
            p = scraped.get(num) if num else None
            if not p:
                unmatched += 1
                continue
            meta = _build_metadata(p)
            if not meta:
                unmatched += 1
                continue
            if not args.dry_run:
                import json
                conn.execute(
                    "UPDATE source_documents SET metadata_json=? WHERE id=?",
                    (json.dumps(meta), sid),
                )
            filled += 1
        if not args.dry_run:
            conn.commit()
        total_filled += filled
        total_unmatched += unmatched
        print(f"  {name:32} filled {filled}/{n}" + (f", {unmatched} unmatched" if unmatched else ""))

    conn.close()
    print(f"\nDone. Filled {total_filled}, unmatched {total_unmatched}"
          + (" (dry run — nothing written)" if args.dry_run else ""))


if __name__ == "__main__":
    main()
