"""
Local, CPU-only embedding and reranking helpers for the RAG pipeline
(``app.rag.*``).

Both models here run entirely on-device via ``sentence-transformers``: they
are downloaded once from Hugging Face (a one-time, first-run fetch cached
under the usual HF cache directory) and every subsequent call is pure local
CPU inference - no network call, no GPU, and critically not the same
category of "live API call" the rest of this codebase forbids (that
constraint is about paid/hosted LLM providers - see ``app.agents.llm_client``
- not about local model weights). Nothing in this module ever imports a
provider SDK or opens a socket at inference time.

Both the embedder and the reranker are loaded lazily and cached at module
scope, so the (relatively expensive) model load happens once per process
regardless of how many times ``embed_texts``/``rerank`` are called - the
same pattern ``app.services.predictor`` already uses for the ML model
registry.
"""

from __future__ import annotations

from typing import TypeVar

from app.config import settings

_embedder = None
_reranker = None


def _get_embedder():
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer

        _embedder = SentenceTransformer(settings.EMBED_MODEL, device="cpu")
    return _embedder


def _get_reranker():
    global _reranker
    if _reranker is None:
        from sentence_transformers import CrossEncoder

        _reranker = CrossEncoder(settings.RERANK_MODEL, device="cpu")
    return _reranker


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Encode `texts` into dense embedding vectors on CPU.

    Returns one vector (as a plain list of floats, ready to bind into a
    pgvector column) per input text, in the same order.
    """
    if not texts:
        return []
    embedder = _get_embedder()
    vectors = embedder.encode(texts, convert_to_numpy=True, show_progress_bar=False)
    return [vector.tolist() for vector in vectors]


T = TypeVar("T")


def rerank(query: str, candidates: list[T], *, text_of=lambda c: c) -> list[tuple[T, float]]:
    """Score each candidate against `query` with a cross-encoder and return
    `(candidate, score)` pairs sorted by score, descending (higher = more
    relevant).

    `candidates` may be plain strings or any object; pass `text_of` to
    extract the text to score when candidates aren't already strings (e.g.
    the fused-retrieval result objects in `app.rag.retrieval`).
    """
    if not candidates:
        return []
    reranker = _get_reranker()
    pairs = [(query, text_of(candidate)) for candidate in candidates]
    scores = reranker.predict(pairs, show_progress_bar=False)
    scored = list(zip(candidates, (float(s) for s in scores)))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored
