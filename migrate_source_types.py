"""Migrate source_documents.source_type to the canonical enum.

Publisher names leaked into source_type from news search results (e.g.
'Forbes', 'CNBC'). For every row whose source_type is not in
CANONICAL_SOURCE_TYPES, move the old value into metadata_json under
"publisher" and set source_type='news_article'. Alias values ('article',
'Google News') collapse into their canonical type without a publisher.
Dedup keys with a stale type prefix are rewritten so future runs still
deduplicate against migrated rows.

Usage:
    python migrate_source_types.py --dry-run   # print mapping, no writes
    python migrate_source_types.py             # backup DB, then migrate
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime

base_dir = r"C:\Users\peary\OneDrive - The City University of New York\Web Scraping\competitive-intel-agent"
db_path = os.path.join(base_dir, "intel.db")
sys.path.insert(0, base_dir)

from agents.source_capture import CANONICAL_SOURCE_TYPES, normalize_source_type


def backup_db():
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak_path = os.path.join(base_dir, f"intel.db.bak-sourcetypes-{stamp}")
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(bak_path)
    src.backup(dst)  # safe with WAL — copies a consistent snapshot
    dst.close()
    src.close()
    print(f"Backed up intel.db to {os.path.basename(bak_path)}")
    return bak_path


def main():
    parser = argparse.ArgumentParser(description="Canonicalize source_documents.source_type")
    parser.add_argument("--dry-run", action="store_true", help="print the mapping without writing")
    args = parser.parse_args()

    if not args.dry_run:
        backup_db()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        "SELECT id, source_type, metadata_json, dedup_key FROM source_documents"
    ).fetchall()
    before_types = {r["source_type"] for r in rows}
    existing_dedup_keys = {r["dedup_key"] for r in rows if r["dedup_key"]}

    scanned = len(rows)
    migrated = 0
    mapping = {}  # (old_type, new_type, publisher) -> count

    for r in rows:
        old_type = r["source_type"]
        new_type, publisher = normalize_source_type(old_type)
        if new_type == old_type:
            continue  # already canonical

        key = (old_type, new_type, publisher)
        mapping[key] = mapping.get(key, 0) + 1
        migrated += 1
        if args.dry_run:
            continue

        # Merge publisher into existing metadata_json (don't clobber)
        meta_json = r["metadata_json"]
        if publisher:
            try:
                meta = json.loads(meta_json) if meta_json else {}
            except (ValueError, TypeError):
                meta = {}
            meta.setdefault("publisher", publisher)
            meta_json = json.dumps(meta)

        # Rewrite stale dedup_key prefix (f"{type}|{hash}") so future runs
        # dedup against this row; skip on UNIQUE conflict
        dedup_key = r["dedup_key"]
        new_dedup_key = dedup_key
        if dedup_key and old_type and dedup_key.startswith(f"{old_type}|"):
            candidate = f"{new_type}|" + dedup_key[len(old_type) + 1:]
            if candidate not in existing_dedup_keys:
                new_dedup_key = candidate
                existing_dedup_keys.discard(dedup_key)
                existing_dedup_keys.add(candidate)

        conn.execute(
            "UPDATE source_documents SET source_type = ?, metadata_json = ?, dedup_key = ? WHERE id = ?",
            (new_type, meta_json, new_dedup_key, r["id"]),
        )

    if not args.dry_run:
        conn.commit()

    # ── Summary ──────────────────────────────────────────────────────────
    print(f"\n{'DRY RUN — no writes' if args.dry_run else 'Migration complete'}")
    print(f"Rows scanned:  {scanned}")
    print(f"Rows migrated: {migrated}")
    print(f"Distinct source_type values before: {len(before_types)}")

    if mapping:
        print("\nMapping (old -> new [publisher]) x count:")
        for (old, new, pub), count in sorted(mapping.items(), key=lambda x: -x[1]):
            pub_str = f" [publisher={pub!r}]" if pub else ""
            print(f"  {old!r} -> {new!r}{pub_str} x {count}")

    after_types = {
        row[0] for row in conn.execute("SELECT DISTINCT source_type FROM source_documents")
    }
    print(f"\nDistinct source_type values after: {len(after_types)}")
    non_canonical = sorted(t for t in after_types if t not in CANONICAL_SOURCE_TYPES)
    if non_canonical:
        print(f"Non-canonical values {'remaining (would remain)' if args.dry_run else 'REMAINING'}: {non_canonical if not args.dry_run else len(non_canonical)}")
    else:
        print("All source_type values are canonical.")

    conn.close()


if __name__ == "__main__":
    main()
