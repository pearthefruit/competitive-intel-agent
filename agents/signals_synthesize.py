"""Signal thread synthesis — groups signals into living threads and extracts entities.

Threads are persistent patterns that accumulate signals over time. Each scan's
new signals are either assigned to existing threads or grouped into new ones.
After thread assignment, article text is fetched for thread signals to enrich
entity extraction and thread summaries.
"""

from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

from agents.llm import generate_json, generate_text, FAST_CHAIN, CHEAP_CHAIN
from prompts.signals import (
    build_thread_assignment_prompt,
    build_entity_extraction_prompt,
    build_thread_update_prompt,
)


def _format_signals_for_prompt(signals, max_chars=4000):
    """Format a list of signal dicts into text for LLM prompts.
    Compact: title only, no body excerpts — keeps prompt small for Groq/Cerebras."""
    lines = []
    char_count = 0
    for s in signals:
        line = f"[{s['id']}] [{s['domain']}] {s['title']}"
        if char_count + len(line) > max_chars:
            break
        lines.append(line)
        char_count += len(line)
    return "\n".join(lines)


def _format_threads_for_prompt(threads):
    """Format existing thread summaries for the assignment prompt.
    Compact: title + signal count only, no synthesis text."""
    if not threads:
        return ""
    lines = []
    for t in threads:
        lines.append(f"[{t['id']}] {t['title']} ({t.get('signal_count', 0)} signals)")
    return "\n".join(lines)


def synthesize_into_threads(conn, new_signals, progress_cb=None):
    """Assign new signals to existing threads or create new threads.

    Args:
        conn: DB connection
        new_signals: list of signal dicts (must have 'id' key)
        progress_cb: optional callback(event_type, event_data)

    Returns dict with {assigned_count, new_thread_count, unassigned_count}
    """
    from db import (get_signal_clusters, insert_signal_cluster,
                    link_signal_to_cluster, get_cluster_detail)

    _cb = progress_cb or (lambda *a: None)

    if not new_signals:
        return {"assigned_count": 0, "new_thread_count": 0, "unassigned_count": 0}

    # Fetch all existing threads so LLM can assign to any of them
    # Keep thread list compact for LLM context — exclude narrative threads
    existing_threads = get_signal_clusters(conn, status="all", limit=50, exclude_domain="narrative")
    _cb("synthesize_start", {"signal_count": len(new_signals), "existing_threads": len(existing_threads)})

    # Build prompt and call LLM
    signals_text = _format_signals_for_prompt(new_signals)
    threads_text = _format_threads_for_prompt(existing_threads)

    prompt = build_thread_assignment_prompt(signals_text, threads_text)

    try:
        result = generate_json(prompt, timeout=30, chain=FAST_CHAIN)
    except Exception as e:
        print(f"[synthesize] LLM error: {e}")
        _cb("synthesize_error", {"error": str(e)})
        return {"assigned_count": 0, "new_thread_count": 0, "unassigned_count": len(new_signals)}

    if not result:
        _cb("synthesize_error", {"error": "LLM returned empty result"})
        return {"assigned_count": 0, "new_thread_count": 0, "unassigned_count": len(new_signals)}

    # Process assignments to existing threads
    assignments = result.get("assignments", [])
    new_thread_defs = result.get("new_threads", [])

    # Build signal lookup
    signal_map = {s["id"]: s for s in new_signals}
    existing_thread_ids = {t["id"] for t in existing_threads}

    assigned_count = 0
    for a in assignments:
        sig_id = a.get("signal_id")
        thread_id = a.get("thread_id")
        if sig_id and thread_id and thread_id in existing_thread_ids:
            link_signal_to_cluster(conn, thread_id, sig_id)
            # Update last_signal_at
            conn.execute(
                "UPDATE signal_clusters SET last_signal_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (thread_id,),
            )
            assigned_count += 1

    # Update summaries for threads that got new signals
    updated_thread_ids = set()
    for a in assignments:
        if a.get("thread_id") and a["thread_id"] in existing_thread_ids:
            updated_thread_ids.add(a["thread_id"])

    for tid in updated_thread_ids:
        thread = next((t for t in existing_threads if t["id"] == tid), None)
        if not thread or not thread.get("synthesis"):
            continue
        # Get the new signals assigned to this thread
        new_sigs_for_thread = [
            signal_map[a["signal_id"]]
            for a in assignments
            if a.get("thread_id") == tid and a.get("signal_id") in signal_map
        ]
        if new_sigs_for_thread:
            _update_thread_summary(conn, thread, new_sigs_for_thread)

    _cb("assignments_done", {"assigned": assigned_count, "threads_updated": len(updated_thread_ids)})

    # Create new threads (with fuzzy dedup against existing)
    from difflib import SequenceMatcher
    from db import merge_domains
    new_thread_count = 0
    existing_titles = {t["id"]: (t.get("title") or "").lower() for t in existing_threads}
    existing_domains = {t["id"]: t.get("domain", "") for t in existing_threads}

    for td in new_thread_defs:
        title = td.get("title", "").strip()
        if not title:
            continue
        sig_ids = td.get("signal_ids", [])
        if len(sig_ids) < 2:
            continue

        # Fuzzy dedup: if new thread title is >=85% similar to existing, merge signals + domains
        title_lower = title.lower()
        merged = False
        for eid, etitle in existing_titles.items():
            if SequenceMatcher(None, title_lower, etitle).ratio() >= 0.75:
                print(f"[synthesize] Merging near-duplicate thread '{title}' into existing #{eid} '{etitle}'")
                for sid in sig_ids:
                    if isinstance(sid, int):
                        link_signal_to_cluster(conn, eid, sid)
                # Merge domains (e.g. economics + geopolitics → economics|geopolitics)
                new_domain = td.get("domain", "")
                merged_domain = merge_domains(existing_domains.get(eid, ""), new_domain)
                conn.execute(
                    "UPDATE signal_clusters SET domain = ?, last_signal_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (merged_domain, eid),
                )
                existing_domains[eid] = merged_domain
                assigned_count += len([s for s in sig_ids if isinstance(s, int)])
                merged = True
                break
        if merged:
            continue

        from db import sanitize_domain
        cluster_id = insert_signal_cluster(conn, {
            "domain": sanitize_domain(td.get("domain", "")),
            "title": title,
            "synthesis": td.get("summary", ""),
        })

        # Update last_signal_at on new thread
        conn.execute(
            "UPDATE signal_clusters SET last_signal_at = CURRENT_TIMESTAMP WHERE id = ?",
            (cluster_id,),
        )

        for sid in sig_ids:
            if isinstance(sid, int):
                link_signal_to_cluster(conn, cluster_id, sid)

        # Add to existing titles so subsequent new threads in this batch also dedup
        existing_titles[cluster_id] = title_lower
        new_thread_count += 1
        _cb("new_thread", {"thread_id": cluster_id, "title": title, "signal_count": len(sig_ids)})

    conn.commit()

    unassigned = len(new_signals) - assigned_count - sum(len(td.get("signal_ids", [])) for td in new_thread_defs)
    _cb("synthesize_complete", {
        "assigned": assigned_count,
        "new_threads": new_thread_count,
        "unassigned": max(0, unassigned),
    })

    return {
        "assigned_count": assigned_count,
        "new_thread_count": new_thread_count,
        "unassigned_count": max(0, unassigned),
    }


def enrich_thread_signals(conn, progress_cb=None, max_per_thread=5):
    """Fetch full article text for signals that belong to threads.

    Only fetches for signals that have a URL and a short/missing body (<500 chars).
    Updates signals.body in the DB so entity extraction gets richer input.

    Args:
        conn: DB connection
        progress_cb: optional callback(event_type, event_data)
        max_per_thread: max articles to fetch per thread (avoid hammering)

    Returns count of signals enriched.
    """
    from scraper.web_search import fetch_page_text

    _cb = progress_cb or (lambda *a: None)

    # Find signals in threads that need enrichment (short body + has URL)
    rows = conn.execute(
        """SELECT DISTINCT s.id, s.url, s.title, LENGTH(s.body) as body_len
           FROM signals s
           JOIN signal_cluster_items sci ON sci.signal_id = s.id
           WHERE s.url IS NOT NULL AND s.url != ''
             AND (s.body IS NULL OR LENGTH(s.body) < 500)
           ORDER BY s.collected_at DESC
           LIMIT ?""",
        (max_per_thread * 20,),  # reasonable cap
    ).fetchall()

    if not rows:
        _cb("enrich_skip", {"reason": "No signals need enrichment"})
        return 0

    to_fetch = [dict(r) for r in rows]
    _cb("enrich_start", {"count": len(to_fetch)})

    enriched = 0

    def _fetch_one(sig):
        try:
            text = fetch_page_text(sig["url"], max_chars=4000)
            return sig["id"], text
        except Exception as e:
            print(f"[enrich] Failed to fetch {sig['url'][:60]}: {e}")
            return sig["id"], ""

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_fetch_one, s): s for s in to_fetch}
        for future in as_completed(futures):
            sig_id, text = future.result()
            if text and len(text) > 100:
                conn.execute(
                    "UPDATE signals SET body = ? WHERE id = ?",
                    (text, sig_id),
                )
                enriched += 1
                if enriched % 5 == 0:
                    _cb("enrich_progress", {"enriched": enriched, "total": len(to_fetch)})

    conn.commit()
    _cb("enrich_complete", {"enriched": enriched, "total": len(to_fetch)})
    return enriched


def _update_thread_summary(conn, thread, new_signals):
    """Update a thread's summary to incorporate new signals."""
    signals_text = "\n".join(
        f"- {s['title']}" + (f": {s['body'][:100]}" if s.get("body") else "")
        for s in new_signals[:5]
    )
    prompt = build_thread_update_prompt(thread["title"], thread.get("synthesis", ""), signals_text)
    try:
        updated_summary, _ = generate_text(prompt, timeout=15, chain=CHEAP_CHAIN)
        if updated_summary and len(updated_summary) > 20:
            conn.execute(
                "UPDATE signal_clusters SET synthesis = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (updated_summary.strip(), thread["id"]),
            )
    except Exception as e:
        print(f"[synthesize] Summary update failed for thread {thread['id']}: {e}")


def extract_entities(conn, signals, progress_cb=None):
    """Extract named entities from signals and store them.

    Args:
        conn: DB connection
        signals: list of signal dicts with 'id' key
        progress_cb: optional callback

    Returns count of entities inserted.
    """
    from db import insert_signal_entity, get_or_create_dossier

    _cb = progress_cb or (lambda *a: None)

    if not signals:
        return 0

    _cb("entities_start", {"signal_count": len(signals)})

    # Use richer format for entity extraction — include body excerpt for concepts/events
    lines = []
    char_count = 0
    for s in signals:
        line = f"[{s['id']}] {s['title']}"
        body = (s.get('body') or '')[:300].strip()
        if body:
            line += f"\n  {body}"
        if char_count + len(line) > 8000:
            break
        lines.append(line)
        char_count += len(line)
    signals_text = "\n".join(lines)
    prompt = build_entity_extraction_prompt(signals_text)

    try:
        result = generate_json(prompt, timeout=30, chain=CHEAP_CHAIN)
    except Exception as e:
        print(f"[entities] LLM error: {e}")
        _cb("entities_error", {"error": str(e)})
        return 0

    if not result or "entities" not in result:
        return 0

    entity_count = 0
    for item in result["entities"]:
        sig_id = item.get("signal_id")
        for ent in item.get("entities", []):
            ent_type = ent.get("type", "")
            ent_value = ent.get("value", "").strip()
            if not ent_type or not ent_value:
                continue

            # Try to link company entities to existing dossiers
            dossier_id = None
            if ent_type == "company":
                try:
                    normalized = ent.get("normalized", ent_value)
                    dossier = conn.execute(
                        "SELECT id FROM dossiers WHERE company_name = ? COLLATE NOCASE",
                        (normalized,),
                    ).fetchone()
                    if not dossier:
                        dossier = conn.execute(
                            "SELECT id FROM dossiers WHERE company_name = ? COLLATE NOCASE",
                            (ent_value,),
                        ).fetchone()
                    if dossier:
                        dossier_id = dossier["id"]
                except Exception:
                    pass

            insert_signal_entity(conn, {
                "signal_id": sig_id,
                "entity_type": ent_type,
                "entity_value": ent_value,
                "normalized_value": ent.get("normalized"),
                "dossier_id": dossier_id,
            })
            entity_count += 1

    conn.commit()
    _cb("entities_complete", {"count": entity_count})
    return entity_count


def compute_thread_momentum(conn, thread_id, window_days=7):
    """Compute momentum for a thread: signals this period vs last period.

    Returns dict: {this_period, last_period, direction, lifecycle, days_since_last}
    direction: 'accelerating' | 'stable' | 'fading'
    lifecycle: 'active' | 'cooling' | 'dormant'
    """
    now_count = conn.execute(
        """SELECT COUNT(*) as cnt FROM signal_cluster_items sci
           JOIN signals s ON s.id = sci.signal_id
           WHERE sci.cluster_id = ? AND s.collected_at >= datetime('now', ?)""",
        (thread_id, f"-{window_days} days"),
    ).fetchone()["cnt"]

    prev_count = conn.execute(
        """SELECT COUNT(*) as cnt FROM signal_cluster_items sci
           JOIN signals s ON s.id = sci.signal_id
           WHERE sci.cluster_id = ?
             AND s.collected_at >= datetime('now', ?)
             AND s.collected_at < datetime('now', ?)""",
        (thread_id, f"-{window_days * 2} days", f"-{window_days} days"),
    ).fetchone()["cnt"]

    # Days since last signal in this thread
    last_signal = conn.execute(
        """SELECT MAX(s.collected_at) as last_at FROM signal_cluster_items sci
           JOIN signals s ON s.id = sci.signal_id
           WHERE sci.cluster_id = ?""",
        (thread_id,),
    ).fetchone()["last_at"]

    days_since = 0
    if last_signal:
        from datetime import datetime
        try:
            last_dt = datetime.fromisoformat(last_signal.replace("Z", "+00:00")) if "T" in last_signal else datetime.strptime(last_signal, "%Y-%m-%d %H:%M:%S")
            days_since = (datetime.now() - last_dt).days
        except Exception:
            pass

    # Direction
    if now_count > prev_count and now_count >= 2:
        direction = "accelerating"
    elif now_count < prev_count and prev_count >= 2:
        direction = "fading"
    else:
        direction = "stable"

    # Lifecycle based on recency
    if days_since >= 14:
        lifecycle = "dormant"
    elif days_since >= 7 or (now_count == 0 and prev_count == 0):
        lifecycle = "cooling"
    else:
        lifecycle = "active"

    return {
        "this_period": now_count,
        "last_period": prev_count,
        "direction": direction,
        "lifecycle": lifecycle,
        "days_since_last": days_since,
    }
