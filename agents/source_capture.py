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

# Per-source-type slot caps. The per-document cap cannot help when a type is
# spread across many documents: a company with 720 job postings has 720 separate
# hiring_data docs, so nothing stops them filling every slot. Same for our own
# analysis reports, which should yield to primary evidence when any exists.
# Types absent from this dict are uncapped. As with the other caps, an unfilled
# budget backfills from capped-out chunks — so a company whose only captured
# material is its reports still gets a full result set.
SLOT_CAPS_BY_TYPE = {
    "analysis_report": 2,
    "hiring_data": 3,
}

# Canonical source_type enum — every source_documents row must use one of
# these. Anything else (e.g. a publisher name leaking in from a news search
# result) is stored as "news_article" with the original string preserved in
# metadata_json under "publisher".
CANONICAL_SOURCE_TYPES = frozenset({
    "sec_10k", "sec_8k", "sec_xbrl", "yahoo_finance", "analyst", "propublica",
    "news_article", "google_news", "web", "web_crawl", "pricing_page",
    "reddit", "hackernews", "youtube", "blind", "fishbowl", "tiktok",
    "instagram", "1point3acres", "patent", "hiring_data", "data_point",
    "analysis_report", "revenue_estimate", "ops_maturity",
})

# Source types that are our own LLM synthesis rather than primary evidence.
# They are retrievable — for most companies the analysis reports are the only
# thing ever captured — but they must never be mistaken for a source. Callers
# render them with a distinct badge, and SLOT_CAPS_BY_TYPE keeps them from
# crowding out real evidence when real evidence exists.
SYNTHESIS_SOURCE_TYPES = frozenset({"analysis_report", "revenue_estimate"})

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


# ── Hybrid document ranking (for the Sources pane) ───────────────────────────
# Semantic search alone cannot do verification. Measured on this corpus, asking
# for '$600 million' returned 3 passages of which 0 contained the string, and
# '4.3%' returned nothing at all — cosine similarity has no notion of exact
# tokens, and checking whether a specific figure is real is precisely a
# literal-token question. So literal substring matching runs first and ranks
# above semantic, which stays for paraphrased/conceptual queries.
#
# Unlike search_sources (which feeds an LLM a handful of chunks), this ranks
# whole documents for a browsable list, with a snippet showing the match.

SNIPPET_WIDTH = 240


def _literal_snippet(text: str, needle: str, width: int = SNIPPET_WIDTH) -> str:
    """Return a window of `text` centred on the first case-insensitive hit."""
    if not text:
        return ""
    lo = text.lower().find(needle.lower())
    if lo < 0:
        return text[:width].strip()
    start = max(0, lo - width // 3)
    end = min(len(text), lo + len(needle) + (2 * width) // 3)
    snip = text[start:end].strip().replace("\n", " ")
    return ("…" if start > 0 else "") + snip + ("…" if end < len(text) else "")


def search_sources_ranked(conn, query: str, dossier_id: int,
                          top_k_docs: int = 15, semantic_pool: int = 60) -> list:
    """Rank a company's source *documents* against a query, literal matches first.

    Returns dicts with id, source_type, title, url, source_date, match_kind
    ('literal' | 'semantic'), hits (literal occurrence count), score and snippet.

    No LLM is involved on either path — literal is a SQL LIKE and semantic is a
    local MiniLM embedding plus a dot product, so this is fast enough to drive a
    search box rather than a chat turn.
    """
    query = (query or "").strip()
    if not query:
        return []

    # Escape LIKE metacharacters so a query containing % or _ is taken literally
    esc = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{esc.lower()}%"

    docs = {}

    # ── Literal pass: chunk bodies ────────────────────────────────────────────
    rows = conn.execute(
        """SELECT sc.source_doc_id, sc.chunk_text,
                  sd.source_type, sd.title, sd.url, sd.source_date
             FROM source_chunks sc
             JOIN source_documents sd ON sd.id = sc.source_doc_id
            WHERE sd.dossier_id = ?
              AND lower(sc.chunk_text) LIKE ? ESCAPE '\\'
              AND (sd.status IS NULL OR sd.status != 'rejected')""",
        (dossier_id, pattern),
    ).fetchall()

    for r in rows:
        doc_id = r["source_doc_id"]
        text = r["chunk_text"] or ""
        hits = text.lower().count(query.lower())
        entry = docs.get(doc_id)
        if entry is None:
            docs[doc_id] = {
                "id": doc_id,
                "source_type": r["source_type"],
                "title": r["title"],
                "url": r["url"],
                "source_date": r["source_date"],
                "match_kind": "literal",
                "hits": hits,
                "score": 1.0,
                "snippet": _literal_snippet(text, query),
            }
        else:
            entry["hits"] += hits

    # ── Literal pass: titles ──────────────────────────────────────────────────
    # A document whose title matches is relevant even when no chunk body does
    # (short sources, or a company name that only appears in the heading).
    trows = conn.execute(
        """SELECT id, source_type, title, url, source_date, content
             FROM source_documents
            WHERE dossier_id = ? AND lower(title) LIKE ? ESCAPE '\\'
              AND (status IS NULL OR status != 'rejected')""",
        (dossier_id, pattern),
    ).fetchall()
    for r in trows:
        if r["id"] in docs:
            docs[r["id"]]["hits"] += 1
            continue
        docs[r["id"]] = {
            "id": r["id"],
            "source_type": r["source_type"],
            "title": r["title"],
            "url": r["url"],
            "source_date": r["source_date"],
            "match_kind": "literal",
            "hits": 1,
            "score": 1.0,
            "snippet": _literal_snippet(r["content"] or r["title"] or "", query),
        }

    # ── Semantic pass ─────────────────────────────────────────────────────────
    # Caps off: they protect an LLM context budget, not a browsable list.
    try:
        sem = search_sources(conn, query, dossier_id,
                             top_k=semantic_pool, apply_caps=False)
    except Exception as e:
        print(f"[source_capture] Semantic pass failed, literal only: {e}")
        sem = []

    for r in sem:
        doc_id = r.get("source_doc_id")
        if doc_id in docs:
            continue  # already a literal hit — the stronger signal, keep it
        docs[doc_id] = {
            "id": doc_id,
            "source_type": r.get("source_type"),
            "title": r.get("source_title"),
            "url": r.get("url"),
            "source_date": None,
            "match_kind": "semantic",
            "hits": 0,
            "score": r.get("score", 0.0),
            "section_label": r.get("section_label"),
            "snippet": (r.get("chunk_text") or "")[:SNIPPET_WIDTH].replace("\n", " ").strip(),
        }

    literal = sorted((d for d in docs.values() if d["match_kind"] == "literal"),
                     key=lambda d: (-d["hits"], (d["title"] or "").lower()))
    semantic = sorted((d for d in docs.values() if d["match_kind"] == "semantic"),
                      key=lambda d: -d["score"])
    return (literal + semantic)[:top_k_docs]


# ── Analysis reports as sources ───────────────────────────────────────────────
# Our own reports are the only material most companies ever have: 197 of the 232
# analyzed dossiers were analyzed before source capture existed, so retrieval
# finds nothing for them and chat silently falls back to web search. Indexing the
# reports closes that, but they are synthesis — kept in a separate source_type,
# slot-capped, and badged so they can never pass as primary evidence.

# Headings whose bodies are link lists rather than prose. Retrieving them returns
# a wall of URLs that matches everything and informs nothing; the links are far
# more useful parsed out into metadata as provenance.
_LINKLIST_HEADINGS = {"sources", "source", "references", "citations", "individual reports"}


def _slugify_heading(text: str) -> str:
    import re
    s = re.sub(r"[*_`#]", "", text or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s or "section"


def split_report_sections(text: str) -> tuple:
    """Split a markdown analysis report into (sections, cited_urls).

    Reports average ~4.7 `##` headings, so they section as naturally as a 10-K
    and reuse the same sectioned-capture path. Content before the first heading
    (title block and executive summary) is kept as a leading 'summary' section
    rather than dropped — for many reports it is the densest part.

    Link-list sections are excluded from the returned sections and their URLs
    returned separately. A report with no headings at all falls through the same
    preamble path and comes back as one 'summary' section; the 'report' fallback
    below only fires for input that is empty or whitespace.
    """
    import re

    lines = (text or "").splitlines()
    sections, cited = [], []
    cur_label, cur_buf = None, []

    def flush():
        if not cur_buf:
            return
        body = "\n".join(cur_buf).strip()
        if not body:
            return
        label = (cur_label or "Summary").strip()
        clean = re.sub(r"[*_`]", "", label).strip()
        if clean.lower() in _LINKLIST_HEADINGS:
            cited.extend(re.findall(r"https?://[^\s)\]]+", body))
            return
        sections.append({
            "section_key": _slugify_heading(clean),
            "section_label": clean,
            "content": body,
            "word_count": len(body.split()),
        })

    for line in lines:
        m = re.match(r"^##\s+(.*)$", line)
        if m:
            flush()
            cur_label, cur_buf = m.group(1), []
        else:
            cur_buf.append(line)
    flush()

    if not sections:
        body = (text or "").strip()
        if body:
            sections = [{
                "section_key": "report",
                "section_label": "Report",
                "content": body,
                "word_count": len(body.split()),
            }]

    # Dedup URLs, order-stable
    seen, urls = set(), []
    for u in cited:
        u = u.rstrip(".,;")
        if u not in seen:
            seen.add(u)
            urls.append(u)
    return sections, urls


def _supersede_prior_reports(conn, dossier_id: int, analysis_type: str, keep_doc_id=None):
    """Un-index older analysis_report docs for this dossier + analysis_type.

    Analyses accumulate one row per run, so a company can hold a March and a July
    financial report. Indexing both would leave chat arbitrating between two
    versions of the same synthesis and citing superseded numbers with full
    confidence. Only the newest is retrievable; the older files stay on disk and
    in dossier_analyses, they simply leave the search corpus.

    Deletes chunks and sections explicitly rather than trusting ON DELETE CASCADE,
    which needs a per-connection `PRAGMA foreign_keys=ON` that is not guaranteed.
    Returns the number of documents removed.
    """
    import json as _json

    rows = conn.execute(
        "SELECT id, metadata_json FROM source_documents "
        "WHERE dossier_id = ? AND source_type = 'analysis_report'",
        (dossier_id,),
    ).fetchall()

    victims = []
    for r in rows:
        doc_id = r["id"] if not isinstance(r, tuple) else r[0]
        if keep_doc_id is not None and doc_id == keep_doc_id:
            continue
        raw = r["metadata_json"] if not isinstance(r, tuple) else r[1]
        try:
            meta = _json.loads(raw) if raw else {}
        except Exception:
            meta = {}
        if meta.get("analysis_type") == analysis_type:
            victims.append(doc_id)

    for doc_id in victims:
        conn.execute("DELETE FROM source_chunks WHERE source_doc_id = ?", (doc_id,))
        conn.execute("DELETE FROM source_sections WHERE source_doc_id = ?", (doc_id,))
        conn.execute("DELETE FROM source_documents WHERE id = ?", (doc_id,))
    if victims:
        conn.commit()
    return len(victims)


def capture_analysis_report(conn, dossier_id: int, company: str, analysis_type: str,
                            report_file: str, report_text=None, report_date=None) -> tuple:
    """Index an analysis report as a (synthesis-tier) source. Returns (id, is_new).

    Idempotent per report file. Supersedes older reports of the same type for
    this dossier once the new one is safely indexed.
    """
    import os
    from db import get_source_by_dedup_key

    if not report_file:
        return (None, False)

    basename = os.path.basename(report_file)
    url = f"report://{basename}"
    dk = dedup_key("analysis_report", url=url)

    # Already indexed — return before superseding anything, so a repeated run is
    # a genuine no-op rather than a delete-and-re-embed cycle.
    existing = get_source_by_dedup_key(conn, dk)
    if existing:
        return (existing["id"], False)

    if report_text is None:
        try:
            with open(report_file, "r", encoding="utf-8", errors="ignore") as fh:
                report_text = fh.read()
        except Exception as e:
            print(f"[source_capture] Cannot read report {report_file}: {e}")
            return (None, False)

    if not (report_text or "").strip():
        return (None, False)

    sections, cited_urls = split_report_sections(report_text)
    if not sections:
        return (None, False)

    title = f"{analysis_type.replace('_', ' ').title()} analysis: {company}"
    if report_date:
        title += f" ({report_date})"

    doc_id, is_new = capture_and_embed(
        conn,
        dossier_id=dossier_id,
        source_type="analysis_report",
        title=title,
        url=url,
        content=None,          # sectioned path
        sections=sections,
        metadata={
            "analysis_type": analysis_type,
            "company": company,
            "report_file": report_file,
            "synthesis": True,     # not primary evidence — badge accordingly
            "cited_urls": cited_urls,
            "section_count": len(sections),
        },
        source_date=report_date,
        dedup_kwargs={"url": url},
    )

    if is_new and doc_id:
        _supersede_prior_reports(conn, dossier_id, analysis_type, keep_doc_id=doc_id)

    return (doc_id, is_new)


# ── Semantic search ───────────────────────────────────────────────────────────

def _select_diverse(scored: list, top_k: int) -> list:
    """Pick top_k chunks in score order, spread across docs, sections and types.

    Two passes. The first walks the ranking and admits a chunk only while its
    document, section and source type are under their caps; anything rejected is
    deferred. The second backfills unfilled slots from those deferrals, still
    in score order. Returning fewer passages than asked would be a worse trade
    than returning a concentrated tail, so the caps reshape the ranking without
    ever shrinking the result.
    """
    picked, deferred = [], []
    per_doc, per_section, per_type = {}, {}, {}

    for row in scored:
        if len(picked) >= top_k:
            break
        doc_id = row.get("source_doc_id")
        stype = row.get("source_type")
        type_cap = SLOT_CAPS_BY_TYPE.get(stype)
        if type_cap is not None and per_type.get(stype, 0) >= type_cap:
            deferred.append(row)
            continue
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
        per_type[stype] = per_type.get(stype, 0) + 1
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
    apply_caps: bool = True,
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
    # Caps exist to protect a small LLM context budget. A browsable list wants
    # every match it can get, so callers rendering UI pass apply_caps=False.
    scored = _select_diverse(scored, top_k) if apply_caps else scored[:top_k]

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
