"""One-shot restore: wipe the 7 signals-related tables in intel.db and
repopulate them from intel_backup_pre_phase3.json.

Non-signal tables (dossiers, lenses, campaigns, hypotheses, board_positions, etc.)
are left untouched so prospecting data is preserved.
"""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent
DB_PATH = ROOT / "intel.db"
BACKUP = ROOT / "intel_backup_pre_phase3.json"

# Tables covered by the backup. Order matters for clean delete (child tables first).
TABLES_DELETE_ORDER = [
    "signal_cluster_items",
    "signal_entities",
    "causal_links",
    "causal_paths",
    "narratives",
    "signal_clusters",
    "signals",
]
# Insert order: parents first.
TABLES_INSERT_ORDER = list(reversed(TABLES_DELETE_ORDER))


def main():
    data = json.loads(BACKUP.read_text(encoding="utf-8"))
    tables = data["tables"]

    print(f"Loaded backup: {BACKUP.name}")
    for t in TABLES_INSERT_ORDER:
        print(f"  {t}: {len(tables.get(t, []))} rows")

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys = OFF")
    cur = conn.cursor()

    # Flush WAL into main DB so we start from a clean checkpoint.
    try:
        cur.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.OperationalError:
        pass

    try:
        cur.execute("BEGIN")
        for t in TABLES_DELETE_ORDER:
            cur.execute(f"DELETE FROM {t}")
            print(f"  cleared {t}")

        for t in TABLES_INSERT_ORDER:
            rows = tables.get(t, [])
            if not rows:
                continue
            db_cols = [r[1] for r in cur.execute(f"PRAGMA table_info({t})").fetchall()]
            backup_cols = list(rows[0].keys())
            use_cols = [c for c in backup_cols if c in db_cols]
            missing = set(backup_cols) - set(db_cols)
            if missing:
                print(f"  WARN: {t} backup has columns not in DB (dropped): {missing}")
            placeholders = ",".join(["?"] * len(use_cols))
            cols_sql = ",".join(use_cols)
            sql = f"INSERT INTO {t} ({cols_sql}) VALUES ({placeholders})"
            cur.executemany(sql, [[row.get(c) for c in use_cols] for row in rows])
            print(f"  inserted {len(rows)} into {t}")

        conn.commit()
        print("Restore committed.")
    except Exception as e:
        conn.rollback()
        print(f"ERROR — rolled back: {e}", file=sys.stderr)
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.close()


if __name__ == "__main__":
    main()
