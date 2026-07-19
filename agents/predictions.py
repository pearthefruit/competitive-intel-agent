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


def generate_predictions_for_signal(signal_id: int, signal_title: str, signal_body: str, domain: str, db):
    """Generate 2-3 predictions for a signal. Runs in background thread — silent failure."""
    try:
        prompt = build_predictions_prompt(signal_title, signal_body or '', domain or 'general')
        result = generate_json(prompt, chain=FAST_CHAIN, expect="object", required_keys=["predictions"])
        predictions = result.get('predictions', []) if result else []

        today = datetime.date.today()
        for p in predictions[:3]:
            horizon = _clamp_horizon(p)
            expected_by = (today + datetime.timedelta(days=horizon)).isoformat()
            db.execute(
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
        db.commit()
        logger.info(f"Generated {len(predictions[:3])} predictions for signal {signal_id}")
    except Exception as e:
        logger.warning(f"Prediction generation failed for signal {signal_id}: {e}")


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

# Only the lead of a signal body carries its topic; the tail drags the vector
# toward generic newswire language.
_SIGNAL_EMBED_CHARS = 300


def prediction_embed_text(claim: str, mechanism: str = '') -> str:
    """Canonical text embedded for a prediction. Keep in sync with backfill."""
    return f"{claim} {mechanism or ''}".strip()


def signal_embed_text(title: str, body: str = '') -> str:
    """Canonical text embedded for a signal when matching against predictions."""
    return f"{title} {(body or '')[:_SIGNAL_EMBED_CHARS]}".strip()


def semantic_candidates(signal_title: str, signal_body: str, db, limit: int = 5,
                        min_similarity: float = MIN_MATCH_SIMILARITY,
                        exclude_signal_id: int = None) -> list:
    """Return open predictions semantically close to the signal. No LLM.

    Replaces the previous keyword/IDF overlap filter, which ranked essentially at
    random: with only ~10^2 open predictions, IDF cannot separate topical tokens
    from ordinary English, so long signals matched long predictions on filler
    words. Cosine over MiniLM ranks by meaning and is corpus-size independent.

    Predictions with no stored embedding are skipped rather than silently treated
    as non-matching — run backfill_prediction_embeddings.py after upgrading.
    """
    import numpy as np
    from agents.embeddings import embed_text

    text = signal_embed_text(signal_title, signal_body)
    if not text:
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

    try:
        q = np.frombuffer(embed_text(text), dtype=np.float32)
    except Exception as e:
        logger.warning(f"Signal embedding failed, skipping match: {e}")
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


def match_signal_to_predictions(signal_id: int, signal_title: str, signal_body: str, db):
    """Match a signal against open predictions. Write evidence rows. Called in background thread."""
    from prompts.predictions import build_evidence_judge_prompt

    # Cap at 5 LLM judge calls per signal. Already-judged pairs are excluded in
    # the query rather than skipped in this loop, so they don't consume slots.
    candidates = semantic_candidates(
        signal_title, signal_body, db, limit=5, exclude_signal_id=signal_id
    )
    if not candidates:
        return

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

            if stance == 'unrelated' or weight < 0.3:
                continue

            db.execute(
                """INSERT OR IGNORE INTO prediction_evidence
                   (prediction_id, signal_id, stance, weight, note)
                   VALUES (?, ?, ?, ?, ?)""",
                (pred['id'], signal_id, stance, weight, note)
            )
            db.commit()
            logger.info(
                f"Evidence: signal {signal_id} {stance} prediction {pred['id']} "
                f"(w={weight:.2f}, cos={pred.get('similarity', 0):.2f})"
            )
        except Exception as e:
            logger.warning(f"Evidence judge failed for prediction {pred['id']}: {e}")


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


# ── Phase 3: Thread-level prediction generation ───────────────────────────────

def generate_predictions_for_thread(thread_id: int, thread_title: str, thread_body: str, db):
    """Generate 2-3 predictions for a thread. Runs in background thread — silent failure."""
    from prompts.predictions import build_thread_predictions_prompt
    try:
        prompt = build_thread_predictions_prompt(thread_title, thread_body or '')
        result = generate_json(prompt, chain=FAST_CHAIN, expect="object", required_keys=["predictions"])
        predictions = result.get('predictions', []) if result else []

        today = datetime.date.today()
        for p in predictions[:3]:
            horizon = _clamp_horizon(p)
            expected_by = (today + datetime.timedelta(days=horizon)).isoformat()
            db.execute(
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
        db.commit()
        logger.info(f"Generated {len(predictions[:3])} predictions for thread {thread_id}")
    except Exception as e:
        logger.warning(f"Thread prediction generation failed for thread {thread_id}: {e}")


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
