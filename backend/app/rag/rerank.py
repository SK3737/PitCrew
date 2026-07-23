"""
Cross-encoder rerank: narrows the ~20 RRF-fused hybrid retrieval candidates
(`app.rag.retrieval.hybrid_search`) down to the final top few chunks handed
to the Knowledge specialist, using `app.agents.embeddings.rerank`.

Why rerank at all when RRF already ranks the candidates: RRF only combines
two *independent* rankers' rank positions - it never looks at the query and
a candidate's text together. A cross-encoder does exactly that (scores the
actual query/candidate pair jointly), which is a strictly more accurate
relevance judgment than fusing two rank orders - see
`backend/tests/test_retrieval.py::test_rerank_improves_gold_chunk_position`
for the concrete evidence this task requires.
"""

from __future__ import annotations

from app.agents.embeddings import rerank as cross_encoder_rerank
from app.rag.retrieval import RetrievedChunk

DEFAULT_TOP_N = 5

# Below this cross-encoder score, a chunk is not treated as real supporting
# evidence - the Knowledge specialist refuses rather than cites it. See
# app.agents.tools.search_kb and test_knowledge_agent.py::test_refuses_when_no_context
# for where this threshold is applied.
#
# Chosen empirically against this corpus (see task-6-report.md for the full
# calibration table): 8 genuinely answerable questions - including
# paraphrased ones whose gold chunk uses quite different wording - all
# scored >= 1.95, while 7 questions with no supporting chunk in the corpus
# at all (tyre pressure, spark plug gap, capital of France, ...) all scored
# <= -6.52. 0.0 sits in the middle of that ~8-point gap with a large margin
# on both sides.
REFUSAL_SCORE_THRESHOLD = 0.0


def rerank_candidates(
    query: str, candidates: list[RetrievedChunk], *, top_n: int = DEFAULT_TOP_N
) -> list[RetrievedChunk]:
    """Score every fused candidate against `query` with the cross-encoder
    and return the top `top_n`, sorted descending.

    Each returned chunk's `score` is overwritten with the reranker's score
    (RRF's fused score and the cross-encoder's score are not the same scale
    and are not comparable) - this is the score `search_kb` checks against
    `REFUSAL_SCORE_THRESHOLD`.
    """
    if not candidates:
        return []
    scored = cross_encoder_rerank(query, candidates, text_of=lambda c: c.text)
    reranked = [
        RetrievedChunk(
            chunk_id=c.chunk_id,
            document_id=c.document_id,
            source=c.source,
            section=c.section,
            text=c.text,
            score=score,
        )
        for c, score in scored
    ]
    return reranked[:top_n]
