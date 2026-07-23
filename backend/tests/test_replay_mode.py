"""
Task 7.3: prove the assistant runs deterministically end to end under
`LLM_BACKEND=replay`, entirely offline, against the curated "golden
scenarios" committed at `backend/cassettes/golden/*.json` - the same
cassettes Phase 8 (frontend e2e) and Phase 9 (evals-in-CI) run against by
name, so these two scenarios (and their exact question text/answer shape)
are a stable contract other phases depend on. See task-7-report.md for how
these particular cassette files were authored (hand-synthesized via the
real predictor/RAG pipeline, not a live Groq recording - no API key is
available in this environment) and `backend/scripts/record_cassettes.py`
for the record-mode script a human would run against a live key to
refresh them for real.

Unlike `test_supervisor_routing.py`/`test_knowledge_agent.py` (which seed
their own throwaway cassette set into `tmp_path` on every run, proving the
*mechanism* works), this file replays the actual committed
`cassettes/golden/` fixtures with no recording pass of its own - proving the
fixtures themselves are valid and will keep working for every later phase
that depends on them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pytest

from app.agents.llm_client import CassetteMiss, ReplayClient
from app.agents.supervisor import ask
from app.agents.tools import AgentDeps, RepositoryKBSearchProvider, VehicleServiceSnapshot
from app.rag.ingest import ingest_kb_directory

GOLDEN_DIR = Path(__file__).resolve().parents[1] / "cassettes" / "golden"
KB_DIR = Path(__file__).resolve().parents[1] / "data" / "kb"

GOLDEN_DIAGNOSTICS_QUESTION = "When does V001 need its next service?"
GOLDEN_KNOWLEDGE_QUESTION = "How often should I flush the coolant on a BMW 3 Series?"


class _GoldenVehicleData:
    """Fixed, date-independent snapshot for vehicle V001 - must match the
    snapshot `scripts/record_cassettes.py` (and this cassette's authoring
    pass) drove `predict_service` with, or the tool-call turn's recorded
    message history won't match what this replay reproduces."""

    async def get_snapshot(self, vehicle_id: str) -> Optional[VehicleServiceSnapshot]:
        if vehicle_id != "V001":
            return None
        return VehicleServiceSnapshot(
            vehicle_id="V001",
            months_driven=5.0,
            kms_driven=6000.0,
            make="Toyota",
            vehicle_model="Corolla",
            year=2020,
            fuel_type="petrol",
            last_service_type="oil_change",
        )


async def test_golden_diagnostics_scenario_replays_deterministically():
    """The diagnostics golden scenario: "When does V001 need its next
    service?" against a known, fixed vehicle snapshot. Expected shape: the
    supervisor routes to diagnostics, predict_service returns a real
    (model_v2) prediction, and the answer cites both the day and km
    estimate - the exact fields Phase 8/9 will assert on."""
    replay = ReplayClient(cassette_dir=GOLDEN_DIR)
    deps = AgentDeps(vehicle_data=_GoldenVehicleData())

    final_state = await ask(replay, deps, GOLDEN_DIAGNOSTICS_QUESTION)

    assert final_state["route"] == "diagnostics"
    prediction = final_state["tool_results"]["predict_service"]
    assert prediction == {
        "vehicle_id": "V001",
        "predicted_days_until_service": 38,
        "predicted_kms_until_service": 1474.2,
        "earlier_trigger": "km",
        "source": "model_v2",
    }
    assert "38" in final_state["answer"]
    assert "1474" in final_state["answer"]


async def test_golden_knowledge_scenario_replays_deterministically(db_session):
    """The knowledge golden scenario: "How often should I flush the coolant
    on a BMW 3 Series?" - answered from the real, checked-in KB corpus.
    Expected shape: the supervisor routes to knowledge, the top citation is
    the BMW 3 Series Coolant Service chunk, and the answer cites it inline
    with [1]. Real hybrid retrieval + rerank runs here (same as
    test_knowledge_agent.py) - only the LLM side is cassette-backed - so
    `chunk_id` is only stable because `conftest.py`'s autouse
    `_clean_database` fixture guarantees a freshly recreated schema (and
    thus KBChunk's id sequence restarting) before this ingest, exactly as
    it was when this cassette was authored."""
    await ingest_kb_directory(db_session, KB_DIR)

    replay = ReplayClient(cassette_dir=GOLDEN_DIR)
    deps = AgentDeps(vehicle_data=_GoldenVehicleData(), kb=RepositoryKBSearchProvider(db_session))

    final_state = await ask(replay, deps, GOLDEN_KNOWLEDGE_QUESTION)

    assert final_state["route"] == "knowledge"
    assert final_state["citations"], "expected at least one grounded citation"
    top = final_state["citations"][0]
    assert "BMW" in top["source"]
    assert top["section"] == "Coolant Service"
    assert "[1]" in final_state["answer"]


async def test_off_script_prompt_raises_cassette_miss_not_a_live_call():
    """The core replay-mode guarantee (task 7.3's acceptance gate): a
    prompt with no matching cassette raises `CassetteMiss` - it never
    silently falls back to a live network call, in either the golden
    directory or the default one `build_default_client()` uses."""
    replay = ReplayClient(cassette_dir=GOLDEN_DIR)
    deps = AgentDeps(vehicle_data=_GoldenVehicleData())

    with pytest.raises(CassetteMiss):
        await ask(replay, deps, "This question was never recorded in any cassette")


async def test_off_script_prompt_raises_cassette_miss_against_default_cassette_dir():
    """Same guarantee against `ReplayClient()`'s default directory
    (`backend/cassettes/`, what `build_default_client()` uses in prod/CI
    under `LLM_BACKEND=replay`) - not just the golden subdirectory."""
    replay = ReplayClient()
    deps = AgentDeps(vehicle_data=_GoldenVehicleData())

    with pytest.raises(CassetteMiss):
        await ask(replay, deps, "Also never recorded anywhere, ever")
