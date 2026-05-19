"""Embedding utilities for SignalVault source memory (RAG).

Model: all-MiniLM-L6-v2 — 80MB, 384-dim, ~50ms/chunk on CPU, fully offline.
Lazy-loads on first call so import never blocks startup.
"""

import numpy as np

_model_cache = {}
_MODEL_NAME = "all-MiniLM-L6-v2"


def _get_model(name=_MODEL_NAME):
    if name not in _model_cache:
        from sentence_transformers import SentenceTransformer
        _model_cache[name] = SentenceTransformer(name)
    return _model_cache[name]


def embed_text(text: str) -> bytes:
    """Embed a single string. Returns float32 bytes (L2-normalized)."""
    model = _get_model()
    vec = model.encode(text, normalize_embeddings=True)
    return vec.astype(np.float32).tobytes()


def embed_batch(texts: list) -> list:
    """Embed a list of strings. Returns list of float32 bytes (each L2-normalized)."""
    model = _get_model()
    vecs = model.encode(texts, normalize_embeddings=True, batch_size=32, show_progress_bar=False)
    return [v.astype(np.float32).tobytes() for v in vecs]


def semantic_search(query_bytes: bytes, rows: list, top_k: int = 10) -> list:
    """
    Rank rows by cosine similarity to query embedding.

    rows: list of dicts, each must have 'embedding' (bytes) + any metadata.
    Returns top_k rows sorted by score descending, with 'score' key added.
    Vectors are L2-normalized so dot product == cosine similarity.
    """
    q = np.frombuffer(query_bytes, dtype=np.float32)
    scored = []
    for row in rows:
        emb = np.frombuffer(row["embedding"], dtype=np.float32)
        score = float(np.dot(q, emb))
        scored.append({**row, "score": score})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]
