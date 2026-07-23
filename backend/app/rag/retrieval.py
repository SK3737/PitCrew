"""
Hybrid retrieval for the RAG knowledge base: fuses a pgvector
cosine-similarity ranking with a Postgres full-text (`tsvector`/`ts_rank`)
ranking via Reciprocal Rank Fusion (RRF), producing the candidate set
`app.rag.rerank` narrows down to the final top few chunks.

Why hybrid: vector similarity finds paraphrases/synonyms the exact query
words don't contain (e.g. "how often should I change the oil" against a
chunk that says "oil and filter change... every 10,000 km"), while
full-text search reliably surfaces exact terms (part numbers, model names)
that embeddings can under-weight. Fusing both, rather than picking one,
covers both failure modes.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.embeddings import embed_texts
from app.models.kb import KBChunk, KBDocument

# Standard IR-literature default for Reciprocal Rank Fusion's smoothing
# constant (Cormack et al., 2009) - not tuned further per the brief's
# instruction to implement RRF plainly.
RRF_K = 60


@dataclass
class RetrievedChunk:
    """One candidate chunk, at any stage of the pipeline (raw ranking, RRF
    fusion, or post-rerank) - the same shape flows through all three, only
    `score` changes meaning as it goes (a per-ranker score isn't computed at
    all pre-fusion; RRF's fused score; then the reranker's cross-encoder
    score).

    `source` is `KBDocument.title` (e.g. "BMW 3 Series Service Guide
    (Synthetic)") - the specific, per-vehicle identifier a citation needs to
    distinguish *which* guide a fact came from - not `KBDocument.source`
    (a shared publisher label, "PitCrew Synthetic Knowledge Base", identical
    across every document and useless for that purpose).
    """

    chunk_id: int
    document_id: int
    source: str
    section: str
    text: str
    score: float = 0.0


async def _vector_candidates(
    session: AsyncSession, query_vector: list[float], limit: int
) -> list[RetrievedChunk]:
    stmt = (
        select(
            KBChunk.id,
            KBChunk.document_id,
            KBChunk.section,
            KBChunk.text,
            KBDocument.title,
        )
        .join(KBDocument, KBChunk.document_id == KBDocument.id)
        .order_by(KBChunk.embedding.cosine_distance(query_vector))
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [
        RetrievedChunk(
            chunk_id=row.id,
            document_id=row.document_id,
            source=row.title,
            section=row.section,
            text=row.text,
        )
        for row in rows
    ]


async def _fulltext_candidates(session: AsyncSession, query: str, limit: int) -> list[RetrievedChunk]:
    tsquery = func.plainto_tsquery("english", query)
    stmt = (
        select(
            KBChunk.id,
            KBChunk.document_id,
            KBChunk.section,
            KBChunk.text,
            KBDocument.title,
        )
        .join(KBDocument, KBChunk.document_id == KBDocument.id)
        .where(KBChunk.content_tsv.op("@@")(tsquery))
        .order_by(func.ts_rank(KBChunk.content_tsv, tsquery).desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [
        RetrievedChunk(
            chunk_id=row.id,
            document_id=row.document_id,
            source=row.title,
            section=row.section,
            text=row.text,
        )
        for row in rows
    ]


def reciprocal_rank_fusion(
    rankings: list[list[RetrievedChunk]], *, k: int = RRF_K
) -> list[RetrievedChunk]:
    """Fuse N independently-ranked candidate lists into one list, scoring
    each chunk by::

        score(d) = sum over rankers r of 1 / (k + rank_r(d))

    (rank is 1-indexed; a chunk absent from a given ranking simply
    contributes 0 for that ranker). A chunk that appears near the top of
    either ranking - or in both - floats to the top of the fused list.
    """
    scores: dict[int, float] = {}
    chunks_by_id: dict[int, RetrievedChunk] = {}
    for ranking in rankings:
        for rank, chunk in enumerate(ranking, start=1):
            scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + 1.0 / (k + rank)
            chunks_by_id.setdefault(chunk.chunk_id, chunk)

    fused = [
        RetrievedChunk(
            chunk_id=chunk.chunk_id,
            document_id=chunk.document_id,
            source=chunk.source,
            section=chunk.section,
            text=chunk.text,
            score=scores[chunk.chunk_id],
        )
        for chunk in chunks_by_id.values()
    ]
    fused.sort(key=lambda c: c.score, reverse=True)
    return fused


async def hybrid_search(
    session: AsyncSession, query: str, *, candidate_k: int = 20
) -> list[RetrievedChunk]:
    """Retrieve up to `candidate_k` RRF-fused candidates for `query`.

    The two rankers' queries run sequentially against the same
    `AsyncSession` (a single AsyncSession is not safe for concurrent use
    from two coroutines, so this deliberately does not `asyncio.gather`
    them) - both are cheap, indexed lookups against a small corpus.
    """
    query_vector = embed_texts([query])[0]
    vector_hits = await _vector_candidates(session, query_vector, candidate_k)
    text_hits = await _fulltext_candidates(session, query, candidate_k)
    return reciprocal_rank_fusion([vector_hits, text_hits])[:candidate_k]
