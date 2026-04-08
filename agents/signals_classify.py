"""TF-IDF signal classifier — learns from existing thread assignments.

Scores unassigned signals against existing threads using TF-IDF cosine
similarity. No external API, no GPU, no training step — the thread's
signal titles ARE the training data. Improves organically as more
signals are assigned (by user, LLM, or auto-assign).

Bigrams (ngram_range 1-2) catch phrases like "interest rate", "supply chain".
"""

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


# Confidence thresholds
HIGH_CONFIDENCE = 0.30   # auto-assign (clear winner with strong margin)
MEDIUM_CONFIDENCE = 0.12  # LLM confirms
MARGIN_RATIO = 1.5       # top score must be this many times the runner-up for high


def build_thread_profiles(conn):
    """Build a TF-IDF model from existing thread→signal assignments.

    Returns (vectorizer, thread_vectors, thread_ids, thread_titles) or None if
    insufficient data.
    """
    threads = conn.execute(
        """SELECT sc.id, sc.title FROM signal_clusters sc
           WHERE sc.domain != 'narrative'
           AND (SELECT COUNT(*) FROM signal_cluster_items WHERE cluster_id = sc.id) >= 2"""
    ).fetchall()

    if not threads:
        return None

    thread_ids = []
    thread_titles = []
    thread_docs = []

    for t in threads:
        tid = t["id"]
        title = t["title"]

        # Gather all signal titles in this thread
        sigs = conn.execute(
            """SELECT s.title FROM signals s
               JOIN signal_cluster_items sci ON sci.signal_id = s.id
               WHERE sci.cluster_id = ?""",
            (tid,),
        ).fetchall()

        if not sigs:
            continue

        # Thread document = thread title (weighted 3x) + all signal titles
        sig_titles = " ".join(s["title"] for s in sigs)
        doc = f"{title} {title} {title} {sig_titles}"

        thread_ids.append(tid)
        thread_titles.append(title)
        thread_docs.append(doc)

    if len(thread_docs) < 2:
        return None

    vectorizer = TfidfVectorizer(
        ngram_range=(1, 2),
        max_features=5000,
        stop_words="english",
        sublinear_tf=True,
    )
    thread_vectors = vectorizer.fit_transform(thread_docs)

    return vectorizer, thread_vectors, thread_ids, thread_titles


def score_signals(conn, signals, profile=None):
    """Score each signal against existing threads.

    Args:
        conn: DB connection
        signals: list of signal dicts (must have 'id' and 'title')
        profile: optional pre-built profile from build_thread_profiles()

    Returns list of dicts:
        {signal_id, signal_title, scores: [{thread_id, thread_title, score}],
         top_thread_id, top_score, margin, confidence: 'high'|'medium'|'low'}
    """
    if profile is None:
        profile = build_thread_profiles(conn)
    if profile is None:
        return [{"signal_id": s["id"], "signal_title": s["title"],
                 "scores": [], "top_thread_id": None, "top_score": 0,
                 "margin": 0, "confidence": "low"} for s in signals]

    vectorizer, thread_vectors, thread_ids, thread_titles = profile

    results = []
    for sig in signals:
        title = sig.get("title", "")
        if not title:
            results.append({"signal_id": sig["id"], "signal_title": "",
                            "scores": [], "top_thread_id": None, "top_score": 0,
                            "margin": 0, "confidence": "low"})
            continue

        sig_vec = vectorizer.transform([title])
        similarities = cosine_similarity(sig_vec, thread_vectors)[0]

        # Rank threads by similarity
        ranked = sorted(
            zip(thread_ids, thread_titles, similarities),
            key=lambda x: x[2], reverse=True,
        )

        top_score = ranked[0][2] if ranked else 0
        runner_up = ranked[1][2] if len(ranked) > 1 else 0
        margin = top_score / runner_up if runner_up > 0 else float("inf")

        # Determine confidence
        if top_score >= HIGH_CONFIDENCE and margin >= MARGIN_RATIO:
            confidence = "high"
        elif top_score >= MEDIUM_CONFIDENCE:
            confidence = "medium"
        else:
            confidence = "low"

        results.append({
            "signal_id": sig["id"],
            "signal_title": title,
            "scores": [
                {"thread_id": tid, "thread_title": ttitle, "score": round(float(sim), 4)}
                for tid, ttitle, sim in ranked[:5]
            ],
            "top_thread_id": ranked[0][0] if ranked and top_score >= MEDIUM_CONFIDENCE else None,
            "top_score": round(float(top_score), 4),
            "margin": round(float(margin), 2),
            "confidence": confidence,
        })

    return results


def keyword_assign(conn, signals, progress_cb=None):
    """Auto-assign high-confidence signals to threads using TF-IDF.

    Returns dict:
        assigned: list of {signal_id, thread_id, thread_title, score, margin}
        needs_llm: list of signal dicts (medium confidence)
        needs_review: list of signal dicts (low confidence)
        profile_stats: {thread_count, signal_count}
    """
    from db import link_signal_to_cluster

    _cb = progress_cb or (lambda *a: None)

    _cb("keyword_start", {"signal_count": len(signals)})

    profile = build_thread_profiles(conn)
    if profile is None:
        _cb("keyword_done", {"assigned": 0, "needs_llm": len(signals), "needs_review": 0})
        return {
            "assigned": [],
            "needs_llm": signals,
            "needs_review": [],
            "profile_stats": {"thread_count": 0, "signal_count": 0},
        }

    _, _, thread_ids, _ = profile
    scored = score_signals(conn, signals, profile=profile)

    assigned = []
    needs_llm = []
    needs_review = []

    for sc in scored:
        sig = next((s for s in signals if s["id"] == sc["signal_id"]), None)
        if not sig:
            continue

        if sc["confidence"] == "high" and sc["top_thread_id"]:
            # Auto-assign
            link_signal_to_cluster(conn, sc["top_thread_id"], sc["signal_id"])
            conn.execute(
                "UPDATE signal_clusters SET last_signal_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (sc["top_thread_id"],),
            )
            top = sc["scores"][0] if sc["scores"] else {}
            assigned.append({
                "signal_id": sc["signal_id"],
                "signal_title": sc["signal_title"],
                "thread_id": sc["top_thread_id"],
                "thread_title": top.get("thread_title", ""),
                "score": sc["top_score"],
                "margin": sc["margin"],
            })
        elif sc["confidence"] == "medium":
            needs_llm.append(sig)
        else:
            needs_review.append(sig)

    if assigned:
        conn.commit()

    _cb("keyword_done", {
        "assigned": len(assigned),
        "needs_llm": len(needs_llm),
        "needs_review": len(needs_review),
    })

    return {
        "assigned": assigned,
        "needs_llm": needs_llm,
        "needs_review": needs_review,
        "profile_stats": {"thread_count": len(thread_ids), "signal_count": len(signals)},
    }
