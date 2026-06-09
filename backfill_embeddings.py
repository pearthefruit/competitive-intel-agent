"""Backfill embeddings for source_documents that have no chunks.

Run from the competitive-intel-agent directory:
    python backfill_embeddings.py [--company "HPE"] [--dry-run]

Finds every source_document whose content was saved but never chunked/embedded
(because it was saved via the legacy save_source_document() path) and embeds it.

This is a one-time migration — future analysis runs will use capture_and_embed()
directly, so sources will be indexed on first save.
"""

import argparse
import sys
from dotenv import load_dotenv
load_dotenv()

from db import get_connection, save_source_chunks
from agents.source_capture import chunk_text
from agents.embeddings import embed_batch


def _fetch_unchunked(conn, company_filter=None):
    """Return source_documents rows with content but no chunks."""
    if company_filter:
        rows = conn.execute(
            """
            SELECT sd.id, sd.source_type, sd.title, sd.url, sd.content, sd.dossier_id,
                   d.company_name
            FROM source_documents sd
            JOIN dossiers d ON d.id = sd.dossier_id
            WHERE sd.content IS NOT NULL AND sd.content != ''
              AND sd.id NOT IN (SELECT DISTINCT source_doc_id FROM source_chunks)
              AND LOWER(d.company_name) LIKE LOWER(?)
            ORDER BY sd.id
            """,
            (f"%{company_filter}%",),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT sd.id, sd.source_type, sd.title, sd.url, sd.content, sd.dossier_id,
                   d.company_name
            FROM source_documents sd
            JOIN dossiers d ON d.id = sd.dossier_id
            WHERE sd.content IS NOT NULL AND sd.content != ''
              AND sd.id NOT IN (SELECT DISTINCT source_doc_id FROM source_chunks)
            ORDER BY sd.id
            """,
        ).fetchall()
    return [dict(r) for r in rows]


def backfill(company_filter=None, dry_run=False):
    conn = get_connection()
    rows = _fetch_unchunked(conn, company_filter)

    if not rows:
        print("[backfill] No unchunked source documents found.")
        conn.close()
        return

    print(f"[backfill] Found {len(rows)} source documents to embed"
          + (f" for company matching '{company_filter}'" if company_filter else ""))

    if dry_run:
        for r in rows:
            words = len((r["content"] or "").split())
            print(f"  [{r['id']}] {r['company_name']} | {r['source_type']} | {r['title'][:60]} ({words}w)")
        print("[backfill] Dry run — no changes made.")
        conn.close()
        return

    ok = 0
    fail = 0
    for r in rows:
        try:
            content = r["content"] or ""
            raw_chunks = chunk_text(content)
            if not raw_chunks:
                print(f"  [{r['id']}] SKIP (no chunks generated): {r['title'][:60]}")
                continue
            embeddings = embed_batch(raw_chunks)
            chunk_rows = [
                {
                    "chunk_index": idx,
                    "chunk_text": raw_chunks[idx],
                    "embedding_bytes": embeddings[idx],
                }
                for idx in range(len(raw_chunks))
            ]
            save_source_chunks(conn, r["id"], chunk_rows, source_section_id=None)
            conn.commit()
            ok += 1
            print(f"  [{r['id']}] OK ({len(raw_chunks)} chunks): {r['company_name']} | {r['source_type']} | {r['title'][:60]}")
        except Exception as e:
            fail += 1
            print(f"  [{r['id']}] FAIL: {r['title'][:60]} — {e}")

    conn.close()
    print(f"\n[backfill] Done: {ok} embedded, {fail} failed, {len(rows) - ok - fail} skipped.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill embeddings for unchunked source documents")
    parser.add_argument("--company", default=None, help="Filter by company name substring")
    parser.add_argument("--dry-run", action="store_true", help="List what would be embedded without doing it")
    args = parser.parse_args()
    backfill(company_filter=args.company, dry_run=args.dry_run)
