"""
TDD coverage for Phase 6 hybrid retrieval + rerank (tasks 6.3/6.4).

`test_hybrid_finds_known_fact` ingests the real authored corpus
(`backend/data/kb/*.md`) into the test database and checks that a query
with a known answer surfaces the right chunk in the top-k fused hybrid
results - this is the acceptance-gate check the brief names directly.

`test_rerank_improves_gold_chunk_position_vs_raw_fusion` is deliberately
*not* driven through the full pgvector+tsvector pipeline: on this small,
topically-distinct corpus, real hybrid_search rarely produces a wrong-first
raw fusion ordering to correct (see task-6-report.md's calibration table),
so a hand-built fixture - a lexically-similar decoy ranked ahead of the
true answer, exactly the failure mode RRF cannot see past because it never
looks at query/candidate text jointly - is what actually demonstrates the
reranker's value. This still runs the real `sentence-transformers`
cross-encoder, not a mock; only the "raw fusion" input ordering is
constructed by hand.
"""

from __future__ import annotations

from pathlib import Path

from app.rag.ingest import ingest_kb_directory
from app.rag.retrieval import RetrievedChunk, hybrid_search, reciprocal_rank_fusion
from app.rag.rerank import rerank_candidates

KB_DIR = Path(__file__).resolve().parents[1] / "data" / "kb"


async def test_hybrid_finds_known_fact(db_session):
    await ingest_kb_directory(db_session, KB_DIR)

    results = await hybrid_search(
        db_session, "How often should I flush the coolant on a BMW 3 Series?"
    )

    top_k = [(r.source, r.section) for r in results[:5]]
    assert any(
        "BMW" in source and section == "Coolant Service" for source, section in top_k
    ), f"expected the BMW 3 Series Coolant Service chunk in the top 5, got: {top_k}"


def test_reciprocal_rank_fusion_rewards_cross_ranker_agreement():
    """A chunk ranked #1 by both rankers should out-score one that only
    ever appears in a single ranking - that's RRF's whole point: combine
    independent evidence rather than trust either ranker alone."""
    agreed = RetrievedChunk(chunk_id=1, document_id=1, source="doc-a", section="s", text="a")
    runner_up = RetrievedChunk(chunk_id=2, document_id=1, source="doc-a", section="s", text="b")
    single_ranker_only = RetrievedChunk(chunk_id=3, document_id=2, source="doc-b", section="s", text="c")

    vector_ranking = [agreed, runner_up]
    text_ranking = [single_ranker_only, agreed, runner_up]

    fused = reciprocal_rank_fusion([vector_ranking, text_ranking])

    assert fused[0].chunk_id == agreed.chunk_id


async def test_rerank_improves_gold_chunk_position_vs_raw_fusion():
    query = "How many kilometers do Civic brake pads last before replacement?"

    gold = RetrievedChunk(
        chunk_id=1,
        document_id=1,
        source="Honda Civic Service Guide (Synthetic)",
        section="Brake Service",
        text="Front brake pads on a Civic typically last 35,000-45,000 km in mixed driving.",
        score=0.0,
    )
    decoy = RetrievedChunk(
        chunk_id=2,
        document_id=1,
        source="Honda Civic Service Guide (Synthetic)",
        section="Common Issues",
        text=(
            "Infotainment freezes/reboots have been reported on some Civic "
            "model years, usually resolved by a software update. A/C "
            "compressor clutch chatter at idle is a frequently reported "
            "minor issue on the Civic."
        ),
        score=0.0,
    )

    # Simulated raw fusion order: the lexically Civic-heavy decoy wrongly
    # ranks ahead of the actual answer.
    raw_fusion_order = [decoy, gold]
    raw_rank = {chunk.chunk_id: i for i, chunk in enumerate(raw_fusion_order, start=1)}
    assert raw_rank[decoy.chunk_id] < raw_rank[gold.chunk_id]

    reranked = rerank_candidates(query, raw_fusion_order, top_n=2)
    rerank_rank = {chunk.chunk_id: i for i, chunk in enumerate(reranked, start=1)}

    assert rerank_rank[gold.chunk_id] < rerank_rank[decoy.chunk_id]
    assert rerank_rank[gold.chunk_id] < raw_rank[gold.chunk_id]
