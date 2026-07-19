"""Background prediction generator for SignalVault.

Generates 2-3 falsifiable forward-looking predictions for each captured signal.
Runs in a background thread — silent failure, never blocks the capture flow.

Phase 2: also matches incoming signals against open predictions and writes
evidence to the prediction_evidence table.
"""

import threading
import datetime
import logging
from agents.llm import generate_json, FAST_CHAIN
from prompts.predictions import build_predictions_prompt

logger = logging.getLogger(__name__)

# Predictions past due by more than this many days auto-expire (still open ones
# within the grace window surface as "overdue" in the UI instead).
EXPIRY_GRACE_DAYS = 14

# Sanity bounds on LLM-provided horizons
MIN_HORIZON_DAYS = 7
MAX_HORIZON_DAYS = 540


def _embed_claim(claim: str, mechanism: str = ''):
    """Embed a prediction claim for evidence matching. None on failure.

    Soft-fails so a missing/broken embedding model never blocks generation — the
    prediction is still stored, just skipped by the matcher until backfilled.
    """
    try:
        from agents.embeddings import embed_text
        return embed_text(prediction_embed_text(claim, mechanism))
    except Exception as e:
        logger.warning(f"Claim embedding failed (prediction still saved): {e}")
        return None


def _clamp_horizon(p) -> int:
    try:
        horizon = int(p.get('horizon_days', 90))
    except (TypeError, ValueError):
        horizon = 90
    return max(MIN_HORIZON_DAYS, min(MAX_HORIZON_DAYS, horizon))


def sweep_expired_predictions(db, grace_days: int = EXPIRY_GRACE_DAYS) -> int:
    """Mark open predictions past expected_by + grace as expired. Returns count.

    Cheap single UPDATE — safe to run on every predictions list request.
    """
    cutoff = (datetime.date.today() - datetime.timedelta(days=grace_days)).isoformat()
    cur = db.execute(
        """UPDATE predictions
           SET status = 'expired',
               resolved_at = CURRENT_TIMESTAMP,
               resolution_note = 'Auto-expired ' || CAST(julianday('now') - julianday(expected_by) AS INTEGER) || ' days past due with no resolution'
           WHERE status = 'open' AND expected_by < ?""",
        (cutoff,),
    )
    db.commit()
    if cur.rowcount:
        logger.info(f"Expired {cur.rowcount} predictions past {grace_days}d grace")
    return cur.rowcount


def _retro_match_new(prediction_ids: list, db) -> None:
    """Retro-match freshly created predictions against stored signals. Never raises."""
    for pid in prediction_ids:
        try:
            retro_match_prediction(pid, db)
        except Exception as e:
            logger.warning(f"Retro-match failed for prediction {pid}: {e}")


def generate_predictions_for_signal(signal_id: int, signal_title: str, signal_body: str, domain: str, db):
    """Generate 2-3 predictions for a signal. Runs in background thread — silent failure."""
    new_ids = []
    try:
        prompt = build_predictions_prompt(signal_title, signal_body or '', domain or 'general')
        result = generate_json(prompt, chain=FAST_CHAIN, expect="object", required_keys=["predictions"])
        predictions = result.get('predictions', []) if result else []

        today = datetime.date.today()
        for p in predictions[:3]:
            horizon = _clamp_horizon(p)
            expected_by = (today + datetime.timedelta(days=horizon)).isoformat()
            cur = db.execute(
                """INSERT INTO predictions
                   (parent_kind, parent_id, claim, mechanism, horizon_days, expected_by,
                    falsifier, confidence, indicator_type, claim_embedding)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ('signal', signal_id,
                 p.get('claim', ''),
                 p.get('mechanism', ''),
                 horizon,
                 expected_by,
                 p.get('falsifier', ''),
                 int(p.get('confidence', 3)),
                 p.get('indicator_type', 'leading'),
                 _embed_claim(p.get('claim', ''), p.get('mechanism', '')))
            )
            new_ids.append(cur.lastrowid)
        db.commit()
        logger.info(f"Generated {len(predictions[:3])} predictions for signal {signal_id}")
    except Exception as e:
        logger.warning(f"Prediction generation failed for signal {signal_id}: {e}")

    # Already on a background thread — retro-match inline rather than fanning out
    # more threads. Without this a prediction can only ever be resolved by signals
    # that arrive after it, never by evidence already in the DB.
    _retro_match_new(new_ids, db)


def generate_predictions_async(signal_id: int, signal_title: str, signal_body: str, domain: str, db_factory):
    """Launch prediction generation in a background thread.

    db_factory: callable that returns a fresh DB connection (needed for thread safety).
    """
    def _run():
        db = db_factory()
        try:
            generate_predictions_for_signal(signal_id, signal_title, signal_body, domain, db)
        finally:
            db.close()

    t = threading.Thread(target=_run, daemon=True)
    t.start()


# ── Phase 2: Signal → Prediction evidence matching ────────────────────────────

# Cosine floor for handing a (signal, prediction) pair to the LLM judge.
# Tuned on intel.db (120 signals x 136 open predictions). Started at 0.45, raised
# to 0.50 after an A/B of the judge showed it calls nearly every 0.45-0.50 pair
# 'unrelated' — those candidates cost a call and yield no evidence. Below ~0.45
# matches are thematic-only, which is what produced the inert 'partial' rows under
# the old keyword filter.
MIN_MATCH_SIMILARITY = 0.50

# Evidence below this LLM-assigned weight is not written to the ledger.
MIN_EVIDENCE_WEIGHT = 0.3

# Judge calls per signal, per direction.
MAX_JUDGE_CALLS_PER_SIGNAL = 5

# Only the lead of a signal body carries its topic; the tail drags the vector
# toward generic newswire language.
_SIGNAL_EMBED_CHARS = 300


def prediction_embed_text(claim: str, mechanism: str = '') -> str:
    """Canonical text embedded for a prediction. Keep in sync with backfill."""
    return f"{claim} {mechanism or ''}".strip()


def signal_embed_text(title: str, body: str = '') -> str:
    """Canonical text embedded for a signal when matching against predictions."""
    return f"{title} {(body or '')[:_SIGNAL_EMBED_CHARS]}".strip()


def get_or_create_signal_embedding(signal_id, signal_title: str, signal_body: str, db):
    """Return a signal's match embedding as a numpy vector, computing+storing if absent.

    Embedding lazily during matching means retro-matching gets a growing corpus of
    comparable signals for free, instead of needing an upfront pass over the DB.
    Returns None if the text is empty or the embedding model is unavailable.
    """
    import numpy as np
    from agents.embeddings import embed_text

    if signal_id is not None:
        row = db.execute(
            "SELECT embedding FROM signal_match_embeddings WHERE signal_id = ?", (signal_id,)
        ).fetchone()
        if row and row["embedding"]:
            return np.frombuffer(row["embedding"], dtype=np.float32)

    text = signal_embed_text(signal_title, signal_body)
    if not text:
        return None
    try:
        blob = embed_text(text)
    except Exception as e:
        logger.warning(f"Signal embedding failed for {signal_id}: {e}")
        return None

    if signal_id is not None:
        try:
            db.execute(
                "INSERT OR REPLACE INTO signal_match_embeddings (signal_id, embedding) VALUES (?, ?)",
                (signal_id, blob),
            )
            db.commit()
        except Exception as e:
            logger.warning(f"Storing signal embedding failed for {signal_id}: {e}")
    return np.frombuffer(blob, dtype=np.float32)


def semantic_candidates(signal_title: str, signal_body: str, db, limit: int = 5,
                        min_similarity: float = MIN_MATCH_SIMILARITY,
                        exclude_signal_id: int = None, signal_id: int = None) -> list:
    """Return open predictions semantically close to the signal. No LLM.

    Replaces the previous keyword/IDF overlap filter, which ranked essentially at
    random: with only ~10^2 open predictions, IDF cannot separate topical tokens
    from ordinary English, so long signals matched long predictions on filler
    words. Cosine over MiniLM ranks by meaning and is corpus-size independent.

    Predictions with no stored embedding are skipped rather than silently treated
    as non-matching — run backfill_prediction_embeddings.py after upgrading.
    """
    import numpy as np

    q = get_or_create_signal_embedding(signal_id, signal_title, signal_body, db)
    if q is None:
        return []

    # Exclude pairs already judged, so re-runs and retro-matching don't spend
    # candidate slots re-judging evidence we already hold.
    sql = """SELECT id, claim, mechanism, expected_by, claim_embedding
             FROM predictions
             WHERE status = 'open' AND claim_embedding IS NOT NULL"""
    params = ()
    if exclude_signal_id is not None:
        sql += """ AND id NOT IN (SELECT prediction_id FROM prediction_evidence
                                  WHERE signal_id = ?)"""
        params = (exclude_signal_id,)

    rows = db.execute(sql, params).fetchall()
    if not rows:
        return []

    scored = []
    for row in rows:
        emb = np.frombuffer(row['claim_embedding'], dtype=np.float32)
        # Both vectors are L2-normalized, so dot product == cosine similarity.
        sim = float(np.dot(q, emb))
        if sim >= min_similarity:
            cand = dict(row)
            cand.pop('claim_embedding', None)
            cand['similarity'] = sim
            scored.append(cand)

    scored.sort(key=lambda c: c['similarity'], reverse=True)
    return scored[:limit]


def match_signal_to_predictions(signal_id: int, signal_title: str, signal_body: str, db) -> int:
    """Match a signal against open predictions. Writes evidence rows, returns how many.

    Runs in a background thread. Marks the signal processed so batch drains don't
    re-judge it.
    """
    from prompts.predictions import build_evidence_judge_prompt

    # Already-judged pairs are excluded in the query rather than skipped in this
    # loop, so they don't consume candidate slots.
    candidates = semantic_candidates(
        signal_title, signal_body, db, limit=MAX_JUDGE_CALLS_PER_SIGNAL,
        exclude_signal_id=signal_id, signal_id=signal_id,
    )
    written = 0
    if not candidates:
        mark_signal_matched(signal_id, db)
        return 0

    for pred in candidates:
        try:
            prompt = build_evidence_judge_prompt(
                signal_title,
                signal_body or '',
                pred['claim'],
                pred.get('mechanism', '')
            )
            result = generate_json(prompt, chain=FAST_CHAIN, expect="object", required_keys=["stance", "weight"])
            if not result:
                continue

            stance = result.get('stance', 'unrelated')
            weight = float(result.get('weight', 0.0))
            note = result.get('note')

            if stance == 'unrelated' or weight < MIN_EVIDENCE_WEIGHT:
                continue

            db.execute(
                """INSERT OR IGNORE INTO prediction_evidence
                   (prediction_id, signal_id, stance, weight, note)
                   VALUES (?, ?, ?, ?, ?)""",
                (pred['id'], signal_id, stance, weight, note)
            )
            db.commit()
            written += 1
            logger.info(
                f"Evidence: signal {signal_id} {stance} prediction {pred['id']} "
                f"(w={weight:.2f}, cos={pred.get('similarity', 0):.2f})"
            )
        except Exception as e:
            logger.warning(f"Evidence judge failed for prediction {pred['id']}: {e}")

    mark_signal_matched(signal_id, db)
    return written


def match_predictions_async(signal_id: int, signal_title: str, signal_body: str, db_factory):
    """Match a new signal against open predictions in a background thread."""
    def _run():
        db = db_factory()
        try:
            match_signal_to_predictions(signal_id, signal_title, signal_body, db)
        except Exception as e:
            logger.warning(f"match_predictions_async failed for signal {signal_id}: {e}")
        finally:
            db.close()

    t = threading.Thread(target=_run, daemon=True)
    t.start()


# ── Phase 2b: batch fan-out for scraped signals ───────────────────────────────
#
# Scans and feed ingests used to have no prediction hooks at all: only manually
# captured signals were ever checked against open predictions, so a scan
# containing the exact confirming evidence would silently pass every open
# prediction by. Matching is modelled as a queue (signals.predictions_matched_at)
# rather than an inline hook, so a signal that arrives while providers are down
# gets picked up on the next drain instead of being lost.

# Ceiling on one drain, so a huge scan can't fan out unbounded. Each signal
# costs at most MAX_JUDGE_CALLS_PER_SIGNAL judge calls, and most cost zero
# because nothing clears the similarity floor.
MAX_BATCH_MATCH_SIGNALS = 150


def mark_signal_matched(signal_id: int, db) -> None:
    """Flag a signal as processed so drains don't re-judge it."""
    db.execute(
        "UPDATE signals SET predictions_matched_at = CURRENT_TIMESTAMP WHERE id = ?",
        (signal_id,),
    )
    db.commit()


def count_pending_match(db) -> int:
    """Signals awaiting a prediction-evidence pass."""
    return db.execute(
        "SELECT COUNT(*) FROM signals WHERE predictions_matched_at IS NULL"
    ).fetchone()[0]


def match_pending_signals(db, limit: int = MAX_BATCH_MATCH_SIGNALS) -> dict:
    """Drain the pending-match queue. Returns counts. Safe to call repeatedly.

    Newest first: recent signals are the ones most likely to resolve an open
    prediction, and a backlog older than the open predictions is rarely useful.
    """
    open_preds = db.execute(
        "SELECT COUNT(*) FROM predictions WHERE status = 'open' AND claim_embedding IS NOT NULL"
    ).fetchone()[0]
    if not open_preds:
        return {"processed": 0, "evidence_written": 0, "skipped": "no open predictions"}

    rows = db.execute(
        """SELECT id, title, body FROM signals
           WHERE predictions_matched_at IS NULL
           ORDER BY collected_at DESC LIMIT ?""",
        (limit,),
    ).fetchall()

    processed = 0
    written = 0
    for row in rows:
        try:
            written += match_signal_to_predictions(row["id"], row["title"], row["body"], db)
        except Exception as e:
            logger.warning(f"batch match failed for signal {row['id']}: {e}")
        finally:
            # Mark regardless: a signal that errored shouldn't wedge the queue.
            mark_signal_matched(row["id"], db)
            processed += 1

    logger.info(f"Batch match: {processed} signals, {written} evidence rows")
    return {"processed": processed, "evidence_written": written,
            "remaining": count_pending_match(db)}


def match_pending_signals_async(db_factory, limit: int = MAX_BATCH_MATCH_SIGNALS):
    """Drain the pending-match queue in one background thread (not one per signal)."""
    def _run():
        db = db_factory()
        try:
            match_pending_signals(db, limit)
        except Exception as e:
            logger.warning(f"match_pending_signals_async failed: {e}")
        finally:
            db.close()

    t = threading.Thread(target=_run, daemon=True)
    t.start()


# ── Phase 2c: retro-matching (new prediction vs signals already in the DB) ────

MAX_RETRO_SIGNALS = 5          # judge calls per new prediction
RETRO_LOOKBACK_DAYS = 45


def retro_match_prediction(prediction_id: int, db,
                           limit: int = MAX_RETRO_SIGNALS,
                           days_back: int = RETRO_LOOKBACK_DAYS,
                           min_similarity: float = None) -> int:
    """Match ONE new prediction against signals already stored. Returns rows written.

    The forward matcher only ever checks a prediction against signals that arrive
    *after* it, so a prediction created today could never be supported by evidence
    already sitting in the DB. This closes that gap.

    Uses stored signal embeddings only — signals are embedded lazily during
    matching, so coverage grows over time (backfill with
    backfill_prediction_embeddings.py --signals).
    """
    import numpy as np
    from prompts.predictions import build_evidence_judge_prompt

    if min_similarity is None:
        min_similarity = MIN_MATCH_SIMILARITY

    pred = db.execute(
        "SELECT id, claim, mechanism, claim_embedding FROM predictions WHERE id = ?",
        (prediction_id,),
    ).fetchone()
    if not pred or not pred["claim_embedding"]:
        return 0

    rows = db.execute(
        """SELECT s.id, s.title, s.body, sme.embedding
           FROM signals s
           JOIN signal_match_embeddings sme ON sme.signal_id = s.id
           WHERE s.collected_at >= datetime('now', ?)
             AND s.id NOT IN (SELECT signal_id FROM prediction_evidence WHERE prediction_id = ?)
           ORDER BY s.collected_at DESC""",
        (f"-{days_back} days", prediction_id),
    ).fetchall()
    if not rows:
        return 0

    q = np.frombuffer(pred["claim_embedding"], dtype=np.float32)
    scored = []
    for row in rows:
        sim = float(np.dot(q, np.frombuffer(row["embedding"], dtype=np.float32)))
        if sim >= min_similarity:
            scored.append((sim, row))
    scored.sort(key=lambda x: x[0], reverse=True)

    written = 0
    for sim, row in scored[:limit]:
        try:
            prompt = build_evidence_judge_prompt(
                row["title"], (row["body"] or "")[:1500],
                pred["claim"], pred["mechanism"] or "",
            )
            result = generate_json(prompt, chain=FAST_CHAIN, expect="object",
                                   required_keys=["stance", "weight"])
            if not result:
                continue
            stance = result.get("stance", "unrelated")
            weight = float(result.get("weight", 0.0))
            if stance == "unrelated" or weight < MIN_EVIDENCE_WEIGHT:
                continue
            db.execute(
                """INSERT OR IGNORE INTO prediction_evidence
                   (prediction_id, signal_id, stance, weight, note)
                   VALUES (?, ?, ?, ?, ?)""",
                (prediction_id, row["id"], stance, weight, result.get("note")),
            )
            db.commit()
            written += 1
            logger.info(f"Retro-evidence: signal {row['id']} {stance} prediction "
                        f"{prediction_id} (w={weight:.2f}, cos={sim:.2f})")
        except Exception as e:
            logger.warning(f"Retro judge failed for prediction {prediction_id}: {e}")
    return written


def retro_match_predictions_async(prediction_ids: list, db_factory):
    """Retro-match newly created predictions in one background thread."""
    def _run():
        db = db_factory()
        try:
            for pid in prediction_ids:
                retro_match_prediction(pid, db)
        except Exception as e:
            logger.warning(f"retro_match_predictions_async failed: {e}")
        finally:
            db.close()

    if not prediction_ids:
        return
    t = threading.Thread(target=_run, daemon=True)
    t.start()


# ── Phase 3: Thread-level prediction generation ───────────────────────────────

def generate_predictions_for_thread(thread_id: int, thread_title: str, thread_body: str, db):
    """Generate 2-3 predictions for a thread. Runs in background thread — silent failure."""
    from prompts.predictions import build_thread_predictions_prompt
    new_ids = []
    try:
        prompt = build_thread_predictions_prompt(thread_title, thread_body or '')
        result = generate_json(prompt, chain=FAST_CHAIN, expect="object", required_keys=["predictions"])
        predictions = result.get('predictions', []) if result else []

        today = datetime.date.today()
        for p in predictions[:3]:
            horizon = _clamp_horizon(p)
            expected_by = (today + datetime.timedelta(days=horizon)).isoformat()
            cur = db.execute(
                """INSERT INTO predictions
                   (parent_kind, parent_id, claim, mechanism, horizon_days, expected_by,
                    falsifier, confidence, indicator_type, claim_embedding)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ('thread', thread_id,
                 p.get('claim', ''),
                 p.get('mechanism', ''),
                 horizon,
                 expected_by,
                 p.get('falsifier', ''),
                 int(p.get('confidence', 3)),
                 p.get('indicator_type', 'leading'),
                 _embed_claim(p.get('claim', ''), p.get('mechanism', '')))
            )
            new_ids.append(cur.lastrowid)
        db.commit()
        logger.info(f"Generated {len(predictions[:3])} predictions for thread {thread_id}")
    except Exception as e:
        logger.warning(f"Thread prediction generation failed for thread {thread_id}: {e}")

    _retro_match_new(new_ids, db)


def generate_thread_predictions_async(thread_id: int, thread_title: str, thread_body: str, db_factory):
    """Launch thread prediction generation in a background thread.

    db_factory: callable that returns a fresh DB connection (needed for thread safety).
    """
    def _run():
        db = db_factory()
        try:
            generate_predictions_for_thread(thread_id, thread_title, thread_body, db)
        finally:
            db.close()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
