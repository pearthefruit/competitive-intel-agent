"""Backfill claim_embedding for predictions created before semantic matching.

Predictions without an embedding are invisible to the evidence matcher, so this
must run once after upgrading. Idempotent — only touches NULL embeddings.

    python backfill_prediction_embeddings.py [--db intel.db] [--all]

--all re-embeds every prediction (use if the embedding text format changes).
"""
import argparse
import sqlite3

from agents.embeddings import embed_batch
from agents.predictions import prediction_embed_text

BATCH = 64


def backfill_signals(conn, limit, redo=False):
    """Embed signals so retro-matching can compare new predictions against history.

    Signals are otherwise embedded lazily as they're matched, so this is only
    needed to make existing history retro-matchable immediately.
    """
    from agents.predictions import signal_embed_text

    where = "" if redo else (
        " WHERE id NOT IN (SELECT signal_id FROM signal_match_embeddings)")
    rows = conn.execute(
        f"SELECT id, title, body FROM signals{where} ORDER BY collected_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    if not rows:
        print("Signals: nothing to embed.")
        return

    print(f"Embedding {len(rows)} signals (MiniLM, CPU)...")
    done = 0
    for i in range(0, len(rows), BATCH):
        chunk = rows[i:i + BATCH]
        vecs = embed_batch([signal_embed_text(r["title"], r["body"]) for r in chunk])
        conn.executemany(
            "INSERT OR REPLACE INTO signal_match_embeddings (signal_id, embedding) VALUES (?, ?)",
            [(r["id"], v) for v, r in zip(vecs, chunk)],
        )
        conn.commit()
        done += len(chunk)
        print(f"  {done}/{len(rows)}")
    print(f"Signals: {done} embedded.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="intel.db")
    ap.add_argument("--all", action="store_true",
                    help="re-embed every prediction, not just those missing one")
    ap.add_argument("--signals", action="store_true",
                    help="also embed signals (enables retro-matching against history)")
    ap.add_argument("--signal-limit", type=int, default=1000,
                    help="max signals to embed, newest first (default 1000)")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    if args.signals:
        backfill_signals(conn, args.signal_limit, args.all)

    where = "" if args.all else " WHERE claim_embedding IS NULL"
    rows = conn.execute(
        f"SELECT id, claim, mechanism FROM predictions{where}"
    ).fetchall()

    if not rows:
        print("Nothing to backfill — all predictions already embedded.")
        conn.close()
        return

    print(f"Embedding {len(rows)} predictions (MiniLM, CPU)...")
    done = 0
    for i in range(0, len(rows), BATCH):
        chunk = rows[i:i + BATCH]
        vecs = embed_batch([
            prediction_embed_text(r["claim"], r["mechanism"]) for r in chunk
        ])
        conn.executemany(
            "UPDATE predictions SET claim_embedding = ? WHERE id = ?",
            [(v, r["id"]) for v, r in zip(vecs, chunk)],
        )
        conn.commit()
        done += len(chunk)
        print(f"  {done}/{len(rows)}")

    remaining = conn.execute(
        "SELECT COUNT(*) FROM predictions WHERE claim_embedding IS NULL"
    ).fetchone()[0]
    print(f"Done. {done} embedded, {remaining} still missing an embedding.")
    conn.close()


if __name__ == "__main__":
    main()
