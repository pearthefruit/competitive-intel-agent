"""Source capture service for SignalVault RAG — Phase 1a.

Handles deduplication, storage, section splitting, and embedding of all
sources fetched during analysis runs. Agents call capture_and_embed() and
search_sources() — all the plumbing is internal.
"""

import hashlib

# ── Constants ────────────────────────────────────────────────────────────────

CHUNK_WORDS = 400
CHUNK_OVERLAP_WORDS = 50
SHORT_SOURCE_CUTOFF = 600   # words; under this → single chunk, no split
SCORE_THRESHOLD = 0.30      # filter noise results in semantic search

# ── Retrieval diversity ──────────────────────────────────────────────────────
# Chunk counts are wildly uneven by source type: a 10-K averages ~160 chunks
# while a news article or patent is exactly 1 (both sit under
# SHORT_SOURCE_CUTOFF). Ranking on raw score alone therefore lets a single
# filing section monopolize every slot in the top_k, so the answer is built
# from one narrow slice of a 90k-word document while the news, hiring and
# sentiment sources for the same company are never seen. These caps spread the
# budget across documents and sections first, then fall back to score order.
DEFAULT_TOP_K = 8
MAX_CHUNKS_PER_DOC = 3
MAX_CHUNKS_PER_SECTION = 2

# Canonical source_type enum — every source_documents row must use one of
# these. Anything else (e.g. a publisher name leaking in from a news search
# result) is stored as "news_article" with the original string preserved in
# metadata_json under "publisher".
CANONICAL_SOURCE_TYPES = frozenset({
    "sec_10k", "sec_8k", "sec_xbrl", "yahoo_finance", "analyst", "propublica",
    "news_article", "google_news", "web", "web_crawl", "pricing_page",
    "reddit", "hackernews", "youtube", "blind", "fishbowl", "tiktok",
    "instagram", "1point3acres", "patent", "hiring_data", "data_point",
})

# Legacy/variant spellings collapsed into a single canonical value
SOURCE_TYPE_ALIASES = {
    "article": "news_article",
    "google news": "google_news",
}


def normalize_source_type(source_type) -> tuple:
    """Normalize a raw source_type to the canonical enum.

    Returns (canonical_type, publisher). publisher is the original string
    when the value was not canonical (e.g. 'Forbes') and should be stored in
    metadata under "publisher"; None when the value was already canonical.
    """
    raw = (source_type or "").strip().lower()
    raw = SOURCE_TYPE_ALIASES.get(raw, raw)
    if raw in CANONICAL_SOURCE_TYPES:
        return raw, None
    return "news_article", (str(source_type).strip() if source_type else None)


# ── Dedup key logic ──────────────────────────────────────────────────────────

def dedup_key(source_type: str, **kwargs) -> str:
    """Generate a collision-resistant identity key for a source.

    sec_10k : f"sec_10k|{company.lower()}|{fiscal_year}"
    sec_8k  : f"sec_8k|{company.lower()}|{accession_number}"
    other   : f"{source_type}|{sha256(url)[:20]}"
    """
    if source_type == "sec_10k":
        company = (kwargs.get("company") or "").lower().strip()
        fiscal_year = str(kwargs.get("fiscal_year", "")).strip()
        return f"sec_10k|{company}|{fiscal_year}"
    elif source_type == "sec_8k":
        company = (kwargs.get("company") or "").lower().strip()
        acc = (kwargs.get("accession_number") or "").strip()
        return f"sec_8k|{company}|{acc}"
    elif source_type == "analyst":
        ticker = (kwargs.get("ticker") or "").lower().strip()
        date = (kwargs.get("date") or "").strip()
        return f"analyst|{ticker}|{date}"
    elif source_type == "yahoo_finance":
        ticker = (kwargs.get("ticker") or "").lower().strip()
        date = (kwargs.get("source_date") or "").strip()
        return f"yahoo_finance|{ticker}|{date}"
    else:
        url = (kwargs.get("url") or "").strip().lower()
        h = hashlib.sha256(url.encode()).hexdigest()[:20]
        return f"{source_type}|{h}"


# ── Chunking ─────────────────────────────────────────────────────────────────

def chunk_text(text: str, chunk_words: int = CHUNK_WORDS,
               overlap_words: int = CHUNK_OVERLAP_WORDS) -> list:
    """Split text into overlapping word-window chunks.

    Sources under SHORT_SOURCE_CUTOFF words are returned as a single-element
    list so short 8-Ks and news articles stay as one coherent chunk.
    Section boundaries must be preserved by the caller — only pass one
    section at a time for structured documents like 10-Ks.
    """
    words = text.split()
    if len(words) <= SHORT_SOURCE_CUTOFF:
        return [text]

    chunks = []
    step = chunk_words - overlap_words
    i = 0
    while i < len(words):
        chunk = " ".join(words[i : i + chunk_words])
        chunks.append(chunk)
        i += step
        if i >= len(words):
            break
    return chunks


# ── Main entry point ─────────────────────────────────────────────────────────

def capture_and_embed(
    conn,
    dossier_id: int,
    source_type: str,
    title: str,
    url: str,
    content,               # str | None — None for 10-Ks (pass sections instead)
    metadata=None,         # dict — stored as JSON
    source_date=None,      # ISO date string
    sections=None,         # list of {section_key, section_label, content} for 10-Ks
    dedup_kwargs=None,     # dict passed to dedup_key()
) -> tuple:
    """Deduplicate, store, section, and embed a source document.

    Returns (source_doc_id, is_new).
    If is_new=False the source was already indexed — returns early without
    re-embedding. This makes repeated analysis runs for the same company
    idempotent for filing-type sources.
    """
    import json as _json
    from db import (
        get_source_by_dedup_key,
        upsert_source_document,
        save_source_sections,
        save_source_chunks,
    )
    from agents.embeddings import embed_batch

    # Enforce the canonical source_type enum (safety net for dynamic strings
    # like publisher names) — original value preserved as metadata publisher
    source_type, publisher = normalize_source_type(source_type)
    if publisher:
        metadata = dict(metadata) if metadata else {}
        metadata.setdefault("publisher", publisher)

    # Build the dedup key
    dk_kwargs = dict(dedup_kwargs or {})
    dk_kwargs.setdefault("url", url or "")
    dk = dedup_key(source_type, **dk_kwargs)

    # Check dedup — if already indexed, return early
    existing = get_source_by_dedup_key(conn, dk)
    if existing:
        return (existing["id"], False)

    # Serialize metadata
    meta_json = _json.dumps(metadata) if metadata else None

    # Insert source document
    source_doc_id, is_new = upsert_source_document(
        conn,
        dossier_id=dossier_id,
        source_type=source_type,
        url=url,
        title=title,
        content=content,
        raw_data=None,
        dedup_key=dk,
        source_date=source_date,
        metadata_json=meta_json,
    )

    if not is_new:
        # Race condition: another thread inserted between our check and upsert
        return (source_doc_id, False)

    # ── Embed and store chunks ────────────────────────────────────────────
    try:
        if sections:
            # Structured document (10-K): save sections first, then chunk each
            section_ids = save_source_sections(conn, source_doc_id, sections)
            for section, section_id in zip(sections, section_ids):
                sec_content = section.get("content") or ""
                if not sec_content.strip():
                    continue
                raw_chunks = chunk_text(sec_content)
                if not raw_chunks:
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
                save_source_chunks(conn, source_doc_id, chunk_rows,
                                   source_section_id=section_id)

        elif content:
            # Short source (8-K, news, Reddit): chunk the flat content
            raw_chunks = chunk_text(content)
            if raw_chunks:
                embeddings = embed_batch(raw_chunks)
                chunk_rows = [
                    {
                        "chunk_index": idx,
                        "chunk_text": raw_chunks[idx],
                        "embedding_bytes": embeddings[idx],
                    }
                    for idx in range(len(raw_chunks))
                ]
                save_source_chunks(conn, source_doc_id, chunk_rows,
                                   source_section_id=None)

    except Exception as e:
        print(f"[source_capture] Embedding failed for '{title}' (non-fatal): {e}")
        # Source row is still saved — it just won't be semantically searchable

    return (source_doc_id, True)


# ── Semantic search ───────────────────────────────────────────────────────────

def _select_diverse(scored: list, top_k: int) -> list:
    """Pick top_k chunks in score order, spread across source docs and sections.

    Two passes. The first walks the ranking and admits a chunk only while its
    document and section are under their caps; anything the caps reject is
    deferred. The second backfills unfilled slots from those deferrals, still
    in score order. Returning fewer passages than asked would be a worse trade
    than returning a concentrated tail, so the caps reshape the ranking without
    ever shrinking the result.
    """
    picked, deferred = [], []
    per_doc, per_section = {}, {}

    for row in scored:
        if len(picked) >= top_k:
            break
        doc_id = row.get("source_doc_id")
        if per_doc.get(doc_id, 0) >= MAX_CHUNKS_PER_DOC:
            deferred.append(row)
            continue
        # The section cap applies only to sectioned documents (10-Ks). Flat
        # sources leave section_key NULL on every chunk, so capping by section
        # there would just be a second, tighter document cap.
        sec_key = row.get("section_key")
        if sec_key:
            sk = (doc_id, sec_key)
            if per_section.get(sk, 0) >= MAX_CHUNKS_PER_SECTION:
                deferred.append(row)
                continue
            per_section[sk] = per_section.get(sk, 0) + 1
        per_doc[doc_id] = per_doc.get(doc_id, 0) + 1
        picked.append(row)

    if len(picked) < top_k:
        picked.extend(deferred[: top_k - len(picked)])
    # Backfilled rows are appended after picks that outrank them, so the caps
    # decide membership but not order. Re-sort so callers and citation numbering
    # still see strictly descending relevance.
    picked.sort(key=lambda r: r["score"], reverse=True)
    return picked


def search_sources(
    conn,
    query: str,
    dossier_id: int,
    source_type=None,
    section_key=None,
    top_k: int = DEFAULT_TOP_K,
) -> list:
    """Semantic search scoped to one company's captured sources.

    Returns top_k results with: source_doc_id, source_type, title, url,
    section_label, chunk_text, score. Filters out results below SCORE_THRESHOLD.
    """
    from db import get_chunks_for_company
    from agents.embeddings import embed_text, semantic_search

    rows = get_chunks_for_company(conn, dossier_id, source_type=source_type)
    if not rows:
        return []

    # Filter by section_key if requested
    if section_key:
        rows = [r for r in rows if r.get("section_key") == section_key]
    if not rows:
        return []

    query_bytes = embed_text(query)
    # Score the whole candidate set, drop noise, then let the diversity caps
    # choose the final top_k. Thresholding before selection matters: a
    # below-threshold chunk should never be admitted just to spread coverage.
    scored = semantic_search(query_bytes, rows, top_k=len(rows))
    scored = [r for r in scored if r["score"] >= SCORE_THRESHOLD]
    scored = _select_diverse(scored, top_k)

    return [
        {
            "source_doc_id": r["source_doc_id"],
            "source_type":   r["source_type"],
            "source_title":  r["title"],
            "url":           r["url"],
            "section_label": r.get("section_label"),
            "chunk_text":    r["chunk_text"],
            "score":         r["score"],
        }
        for r in scored
    ]
