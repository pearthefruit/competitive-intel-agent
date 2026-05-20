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

def search_sources(
    conn,
    query: str,
    dossier_id: int,
    source_type=None,
    section_key=None,
    top_k: int = 8,
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
    scored = semantic_search(query_bytes, rows, top_k=top_k)

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
        if r["score"] >= SCORE_THRESHOLD
    ]
