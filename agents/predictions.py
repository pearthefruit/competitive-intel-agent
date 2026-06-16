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


def generate_predictions_for_signal(signal_id: int, signal_title: str, signal_body: str, domain: str, db):
    """Generate 2-3 predictions for a signal. Runs in background thread — silent failure."""
    try:
        prompt = build_predictions_prompt(signal_title, signal_body or '', domain or 'general')
        result = generate_json(prompt, chain=FAST_CHAIN)
        predictions = result.get('predictions', []) if result else []

        today = datetime.date.today()
        for p in predictions[:3]:
            horizon = int(p.get('horizon_days', 90))
            expected_by = (today + datetime.timedelta(days=horizon)).isoformat()
            db.execute(
                """INSERT INTO predictions
                   (parent_kind, parent_id, claim, mechanism, horizon_days, expected_by,
                    falsifier, confidence, indicator_type)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ('signal', signal_id,
                 p.get('claim', ''),
                 p.get('mechanism', ''),
                 horizon,
                 expected_by,
                 p.get('falsifier', ''),
                 int(p.get('confidence', 3)),
                 p.get('indicator_type', 'leading'))
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

def keyword_candidates(signal_title: str, signal_body: str, db, limit: int = 10) -> list:
    """Return open predictions that share keyword overlap with the signal. No LLM."""
    import re
    # Tokenize signal: extract meaningful words (>4 chars), lowercase, deduplicate
    text = f"{signal_title} {signal_body or ''}"
    words = set(w.lower() for w in re.findall(r'\b[a-zA-Z]{5,}\b', text))
    if not words:
        return []

    # Fetch open predictions
    rows = db.execute(
        "SELECT id, claim, mechanism, expected_by FROM predictions WHERE status = 'open'"
    ).fetchall()

    candidates = []
    for row in rows:
        pred_text = f"{row['claim']} {row['mechanism'] or ''}".lower()
        overlap = sum(1 for w in words if w in pred_text)
        if overlap >= 2:  # at least 2 keyword matches
            candidates.append((overlap, dict(row)))

    # Return top candidates sorted by overlap score
    candidates.sort(key=lambda x: x[0], reverse=True)
    return [c[1] for c in candidates[:limit]]


def match_signal_to_predictions(signal_id: int, signal_title: str, signal_body: str, db):
    """Match a signal against open predictions. Write evidence rows. Called in background thread."""
    from prompts.predictions import build_evidence_judge_prompt

    candidates = keyword_candidates(signal_title, signal_body, db)
    if not candidates:
        return

    for pred in candidates[:5]:  # cap at 5 LLM calls per signal
        # Skip if evidence already recorded for this pair
        existing = db.execute(
            "SELECT 1 FROM prediction_evidence WHERE prediction_id=? AND signal_id=?",
            (pred['id'], signal_id)
        ).fetchone()
        if existing:
            continue

        try:
            prompt = build_evidence_judge_prompt(
                signal_title,
                signal_body or '',
                pred['claim'],
                pred.get('mechanism', '')
            )
            result = generate_json(prompt, chain=FAST_CHAIN)
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
            logger.info(f"Evidence: signal {signal_id} {stance} prediction {pred['id']} (w={weight:.2f})")
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
        result = generate_json(prompt, chain=FAST_CHAIN)
        predictions = result.get('predictions', []) if result else []

        today = datetime.date.today()
        for p in predictions[:3]:
            horizon = int(p.get('horizon_days', 90))
            expected_by = (today + datetime.timedelta(days=horizon)).isoformat()
            db.execute(
                """INSERT INTO predictions
                   (parent_kind, parent_id, claim, mechanism, horizon_days, expected_by,
                    falsifier, confidence, indicator_type)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ('thread', thread_id,
                 p.get('claim', ''),
                 p.get('mechanism', ''),
                 horizon,
                 expected_by,
                 p.get('falsifier', ''),
                 int(p.get('confidence', 3)),
                 p.get('indicator_type', 'leading'))
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
