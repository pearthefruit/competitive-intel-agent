"""One-shot backfill: capture 10-K sections for public companies that have
XBRL sources but no ``sec_10k`` source.

Why this exists: the 10-K fetch was silently broken until the 2026-07-12 fix
(5MB cap + dead anchor parsing), so every public company analyzed before then
captured 8-Ks and XBRL but never a 10-K. The fetch works now — this fills the
gap for companies already in the store without re-running full financial
analysis.

Usage:
    python backfill_10k_sources.py [--dry-run] [--company "Name"] [--limit N]
"""

import argparse

from db import get_connection, get_or_create_dossier, ensure_filing_document
from scraper.sec_edgar import lookup_cik, get_recent_filings, fetch_10k_sections
from agents.source_capture import capture_and_embed


def _targets(conn, company=None):
    """Companies with a sec_xbrl source but no sec_10k source."""
    if company:
        rows = conn.execute(
            "SELECT id, company_name FROM dossiers WHERE company_name = ? COLLATE NOCASE",
            (company,),
        ).fetchall()
        return [(r["id"], r["company_name"]) for r in rows]

    rows = conn.execute(
        """
        SELECT d.id, d.company_name
        FROM dossiers d
        WHERE EXISTS (SELECT 1 FROM source_documents s
                      WHERE s.dossier_id = d.id AND s.source_type = 'sec_xbrl')
          AND NOT EXISTS (SELECT 1 FROM source_documents s
                          WHERE s.dossier_id = d.id AND s.source_type = 'sec_10k')
        ORDER BY d.company_name
        """
    ).fetchall()
    return [(r["id"], r["company_name"]) for r in rows]


def _resolve_cik(company):
    result = lookup_cik(company)
    if isinstance(result, dict):
        return result["cik"]
    if isinstance(result, list) and result:
        return result[0]["cik"]
    return None


def backfill_one(conn, dossier_id, company):
    """Fetch + capture the latest 10-K for one company. Returns a status string."""
    cik = _resolve_cik(company)
    if not cik:
        return "no CIK"

    filings = get_recent_filings(cik)
    try:
        data = fetch_10k_sections(cik, filings)
    except Exception as e:
        return f"fetch error: {e}"
    if not data or not data.get("sections"):
        return "no 10-K found"

    fiscal_year = data.get("fiscal_year", "")
    meta = {
        "fiscal_year": fiscal_year,
        "form_type": data.get("form_type"),
        "filed_date": data.get("filed_date"),
        "section_index": [
            {"key": s["section_key"], "label": s["section_label"],
             "word_count": s.get("word_count", 0)}
            for s in data.get("sections", [])
        ],
    }
    sid, is_new = capture_and_embed(
        conn,
        dossier_id=dossier_id,
        source_type="sec_10k",
        title=f"10-K {fiscal_year} — {company}",
        url=data.get("url"),
        content=None,
        metadata=meta,
        source_date=data.get("filed_date"),
        sections=data.get("sections"),
        dedup_kwargs={"company": company, "fiscal_year": fiscal_year},
    )
    try:
        ensure_filing_document(conn, sid)
    except Exception as e:
        print(f"    [warn] Documents bridge failed (non-fatal): {e}")
    n = len(data.get("sections", []))
    return f"{'captured' if is_new else 'already indexed'} FY{fiscal_year}, {n} sections"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="list targets, don't fetch")
    ap.add_argument("--company", help="backfill a single company by name")
    ap.add_argument("--limit", type=int, default=0, help="cap number of companies")
    args = ap.parse_args()

    conn = get_connection()
    targets = _targets(conn, args.company)
    if args.limit:
        targets = targets[: args.limit]

    print(f"{len(targets)} company(ies) with XBRL but no 10-K source:")
    for _, name in targets:
        print(f"  - {name}")
    if args.dry_run:
        conn.close()
        return

    print("\nBackfilling...\n")
    counts = {"captured": 0, "skipped": 0}
    for dossier_id, name in targets:
        # Ensure a dossier id (targets already have one, but keep it robust)
        did = dossier_id or get_or_create_dossier(conn, name)
        try:
            status = backfill_one(conn, did, name)
        except Exception as e:
            status = f"ERROR: {e}"
        conn.commit()
        ok = status.startswith(("captured", "already"))
        counts["captured" if ok else "skipped"] += 1
        print(f"  {name:32} -> {status}")

    conn.close()
    print(f"\nDone. {counts['captured']} with a 10-K, {counts['skipped']} skipped.")


if __name__ == "__main__":
    main()
