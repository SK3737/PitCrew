"""
Task 6.5/6.6 coverage: the Knowledge specialist, wired to the real RAG
pipeline (`RepositoryKBSearchProvider` -> `search_kb`), returns real
citations for an in-corpus question and refuses rather than fabricates an
answer for one with no supporting chunk.

Pattern follows `test_supervisor_routing.py`: a `_ScriptedClient` "records"
a fixed script of LLM responses into a cassette dir, then a real
`ReplayClient` replays it deterministically - the LLM side is offline and
scripted either way, so what these tests actually exercise is `search_kb`'s
real retrieval against the real ingested corpus, not the LLM's wording.
"""

from __future__ import annotations

from pathlib import Path

from app.agents.llm_client import LLMResponse, ReplayClient, ToolCall
from app.agents.specialists.knowledge import run_knowledge
from app.agents.tools import AgentDeps, RepositoryKBSearchProvider
from app.rag.ingest import ingest_kb_directory
from tests.test_supervisor_routing import _ScriptedClient

KB_DIR = Path(__file__).resolve().parents[1] / "data" / "kb"
QUESTION_MODEL = "replay"


class _NullVehicleData:
    """AgentDeps.vehicle_data is required but unused by the Knowledge
    specialist - a minimal stand-in that raises if a test accidentally
    exercises it."""

    async def get_snapshot(self, vehicle_id: str):
        raise AssertionError("Knowledge specialist should never call vehicle_data")


async def _seed_and_replay_knowledge(tmp_path, db_session, question: str, script: list[LLMResponse]):
    deps = AgentDeps(vehicle_data=_NullVehicleData(), kb=RepositoryKBSearchProvider(db_session))

    director = _ScriptedClient(tmp_path, script)
    await run_knowledge(director, deps, question)  # recording pass

    replay_client = ReplayClient(cassette_dir=tmp_path)
    return await run_knowledge(replay_client, deps, question)


async def test_refuses_when_no_context(tmp_path, db_session):
    """A question with no supporting chunk anywhere in the corpus - real
    retrieval scores everything below REFUSAL_SCORE_THRESHOLD (see
    app.rag.rerank and task-6-report.md's calibration table) - makes
    search_kb return [], so the specialist has nothing to cite and must
    say so rather than guess."""
    await ingest_kb_directory(db_session, KB_DIR)

    question = "What is the recommended spark plug gap?"
    script = [
        LLMResponse(tool_calls=[ToolCall(id="call_1", name="search_kb", arguments={"query": question})]),
        LLMResponse(content="I don't have documentation to answer that."),
    ]

    result = await _seed_and_replay_knowledge(tmp_path, db_session, question, script)

    assert result.citations == []
    assert "documentation" in result.answer.lower()


async def test_search_kb_returns_grounded_citations_for_in_corpus_question(tmp_path, db_session):
    """The mirror-image positive control: a question the corpus does
    answer comes back with real, non-fabricated citations carrying the
    fields the specialist's [n] composition needs."""
    await ingest_kb_directory(db_session, KB_DIR)

    question = "How often should I flush the coolant on a BMW 3 Series?"
    script = [
        LLMResponse(tool_calls=[ToolCall(id="call_1", name="search_kb", arguments={"query": question})]),
        LLMResponse(content="Roughly every 4-6 years or 100,000-150,000 km [1]."),
    ]

    result = await _seed_and_replay_knowledge(tmp_path, db_session, question, script)

    assert result.citations, "expected at least one grounded citation"
    top = result.citations[0]
    assert top.source and top.section and top.text
    assert isinstance(top.chunk_id, int)
    assert "BMW" in top.source
