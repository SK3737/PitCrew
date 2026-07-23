"""
Supervisor routing tests - fully deterministic and offline via ReplayClient.

Pattern: each test first "records" a fixed cassette set into a temp
directory by driving the graph once through a scripted `_ScriptedClient`
(an LLMClient that returns pre-baked responses in call order and writes
each one to disk via `record_cassette` as it goes - see
app.agents.llm_client's cassette convention). It then constructs a real
`ReplayClient` pointed at that same directory and re-runs the graph,
asserting on the resulting trajectory. This guarantees the cassette hashes
match exactly what the graph actually requests (no hand-computed hashes)
while keeping the assertions themselves running against the real,
production `ReplayClient` - never a network call anywhere in this file.
"""

from __future__ import annotations

from app.agents.llm_client import LLMClient, LLMResponse, ReplayClient, ToolCall, record_cassette
from app.agents.supervisor import ask
from app.agents.tools import AgentDeps, VehicleServiceSnapshot

QUESTION_MODEL = "replay"


class _ScriptedClient(LLMClient):
    """Test-only LLMClient: replays a pre-scripted list of responses in call
    order, recording each into `cassette_dir` as it goes."""

    def __init__(self, cassette_dir, script):
        self._dir = cassette_dir
        self._script = list(script)
        self._i = 0

    def complete(self, messages, tools=None, *, temperature=0.0, seed=None, **params):
        response = self._script[self._i]
        self._i += 1
        record_cassette(self._dir, QUESTION_MODEL, messages, tools, response, temperature=temperature, seed=seed)
        return response


class _FakeVehicleData:
    """Offline stand-in for RepositoryVehicleDataProvider - no Postgres
    involved in these routing tests, only the tool's own logic + the
    Phase 3 predictor/registry (which loads local model files)."""

    async def get_snapshot(self, vehicle_id):
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


async def _seed_and_replay(tmp_path, question: str, script: list[LLMResponse]):
    director = _ScriptedClient(tmp_path, script)
    deps = AgentDeps(vehicle_data=_FakeVehicleData())
    await ask(director, deps, question)  # recording pass

    replay_client = ReplayClient(cassette_dir=tmp_path)
    return await ask(replay_client, deps, question)  # deterministic, offline replay


async def test_diagnostics_question_routes_to_diagnostics_and_calls_predict_service(tmp_path):
    question = "When does V001 need its next service?"
    script = [
        LLMResponse(content="diagnostics"),  # classify_intent
        LLMResponse(
            tool_calls=[ToolCall(id="call_1", name="predict_service", arguments={"vehicle_id": "V001"})]
        ),  # diagnostics turn 1: call the tool
        LLMResponse(content="V001 needs service in about 38 days or 1474 km, whichever comes first."),  # turn 2
    ]

    final_state = await _seed_and_replay(tmp_path, question, script)

    assert final_state["route"] == "diagnostics"
    prediction = final_state["tool_results"]["predict_service"]
    assert prediction is not None
    assert prediction["vehicle_id"] == "V001"
    assert prediction["source"] in ("model_v2", "model_v1", "rules")
    assert "38" in final_state["answer"] or prediction["predicted_days_until_service"] is not None


async def test_knowledge_question_routes_to_knowledge_and_calls_search_kb(tmp_path):
    question = "What's the recommended tyre pressure for a sedan?"
    script = [
        LLMResponse(content="knowledge"),  # classify_intent
        LLMResponse(tool_calls=[ToolCall(id="call_1", name="search_kb", arguments={"query": question})]),  # turn 1
        LLMResponse(content="I don't have documentation indexed yet to answer that."),  # turn 2
    ]

    final_state = await _seed_and_replay(tmp_path, question, script)

    assert final_state["route"] == "knowledge"
    assert final_state["citations"] == []
    assert "documentation" in final_state["answer"].lower()


async def test_unparseable_classification_defaults_to_knowledge(tmp_path):
    """classify_intent's fallback (see app.agents.supervisor.classify_intent_text)
    - a garbled/off-script classifier response degrades to the safe route
    rather than crashing or guessing a write-capable one."""
    question = "asdkjaslkdj not a real question"
    script = [
        LLMResponse(content="I'm not sure what category this is"),  # unparseable -> falls back to knowledge
        LLMResponse(tool_calls=[ToolCall(id="call_1", name="search_kb", arguments={"query": question})]),
        LLMResponse(content="I don't have documentation indexed yet to answer that."),
    ]

    final_state = await _seed_and_replay(tmp_path, question, script)

    assert final_state["route"] == "knowledge"
