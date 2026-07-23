"""
Task 9.2: DeepEval trajectory/tool-selection suite - asserts the supervisor
graph (`app.agents.supervisor.ask`) routes to the correct specialist *and*
calls the correct tool, over two scenarios:

1. **Diagnostics** - the committed Phase 7 golden scenario
   (`backend/cassettes/golden/`, see `.superpowers/sdd/task-7-report.md`),
   reused as-is per the brief's own instruction. `expected_tools=[predict_service]`.
2. **Knowledge** - a dedicated, DB-free scenario recorded into
   `backend/cassettes/evals/deepeval/` (see
   `backend/scripts/record_eval_cassettes.py`), *not* the committed golden
   knowledge scenario. Concrete gap found and documented there: the golden
   knowledge cassette's replayability depends on `KBChunk.chunk_id` being a
   fresh auto-increment sequence, which only holds under pytest's autouse
   `_clean_database` fixture - not guaranteed for a standalone `make eval`
   run against a dev database that may already have KB rows ingested (or
   none at all). This scenario uses a fake, DB-free `KBSearchProvider`
   instead, grounded in the same real Honda Civic KB text
   `app.evals.dataset` uses for its Ragas case. `expected_tools=[search_kb]`.

Each scenario's `tools_called` comes from actually running the real
`ask()` graph and recording every tool_call the (replayed) judge/specialist
LLM emitted (`_ToolCallRecordingClient` below) - not asserted from cassette
introspection or hand-typed, so a future change to either fixture that
altered the real trajectory would be caught here.

`ToolCorrectnessMetric`'s core score (`_calculate_score`) is a deterministic
set comparison - no LLM involved. Its optional `available_tools` path (which
*does* call a judge LLM, to score whether the tool picked was the best
choice among alternatives) is exercised for the diagnostics scenario only,
via `app.evals.judge_adapter.build_deepeval_judge` - demonstrating the
DeepEval side of the judge adapter is wired in and cassette-backed, not
just imported. The knowledge scenario uses the deterministic-only path to
keep this suite's judge-cassette surface area small; see task-9-report.md.

Run directly: `python -m app.evals.deepeval_suite` (what `make eval` invokes).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from app.agents.llm_client import GroqClient, LLMClient, ReplayClient
from app.agents.supervisor import ask
from app.agents.tools import AgentDeps, KBHit, VehicleServiceSnapshot
from app.config import settings

GOLDEN_DIR = Path(__file__).resolve().parents[2] / "cassettes" / "golden"
DEEPEVAL_CASSETTE_DIR = Path(__file__).resolve().parents[2] / "cassettes" / "evals" / "deepeval"

DIAGNOSTICS_QUESTION = "When does V001 need its next service?"
KNOWLEDGE_QUESTION = "How often should Honda Civic brake fluid be replaced?"


class _ToolCallRecordingClient(LLMClient):
    """Wraps a real `LLMClient`, forwarding every `complete()` call
    unchanged but recording each response's `tool_calls` - so this suite can
    build a DeepEval `tools_called` trajectory without needing
    `SupervisorState` itself to expose tool-call history (out of scope for
    this phase to change; `tool_results`/`citations` are the only trajectory
    signal it currently carries, see `app.agents.supervisor`)."""

    def __init__(self, inner: LLMClient) -> None:
        self._inner = inner
        self.tool_calls_seen: list[str] = []

    def complete(self, messages, tools=None, *, temperature=0.0, seed=None, **params):
        response = self._inner.complete(messages, tools, temperature=temperature, seed=seed, **params)
        self.tool_calls_seen.extend(tc.name for tc in response.tool_calls)
        return response


class _GoldenVehicleData:
    """Same fixed snapshot as `backend/tests/test_replay_mode.py` - must
    match what the golden cassette was authored against."""

    async def get_snapshot(self, vehicle_id: str):
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


class _NoVehicleData:
    async def get_snapshot(self, vehicle_id: str):
        return None


class _FakeKBSearchProvider:
    def __init__(self, hits: list[KBHit]) -> None:
        self._hits = hits

    async def search(self, query: str) -> list[KBHit]:
        return self._hits


def _build_judge_client():
    """Same `LLM_BACKEND` branch as `app.evals.ragas_suite._build_judge_client` -
    replay points at this suite's own dedicated cassette directory."""
    if settings.LLM_BACKEND == "groq":
        return GroqClient()
    return ReplayClient(cassette_dir=DEEPEVAL_CASSETTE_DIR)


async def _run_diagnostics_scenario() -> dict[str, Any]:
    from deepeval.metrics import ToolCorrectnessMetric
    from deepeval.test_case import LLMTestCase
    from deepeval.test_case import ToolCall as DeepEvalToolCall

    from app.evals.judge_adapter import build_deepeval_judge

    recorder = _ToolCallRecordingClient(ReplayClient(cassette_dir=GOLDEN_DIR))
    deps = AgentDeps(vehicle_data=_GoldenVehicleData())
    final_state = await ask(recorder, deps, DIAGNOSTICS_QUESTION)

    expected_tools = [DeepEvalToolCall(name="predict_service")]
    available_tools = [
        DeepEvalToolCall(name="predict_service"),
        DeepEvalToolCall(name="search_kb"),
        DeepEvalToolCall(name="schedule_service"),
    ]
    test_case = LLMTestCase(
        input=DIAGNOSTICS_QUESTION,
        actual_output=final_state["answer"],
        tools_called=[DeepEvalToolCall(name=n) for n in recorder.tool_calls_seen],
        expected_tools=expected_tools,
    )
    metric = ToolCorrectnessMetric(
        available_tools=available_tools, model=build_deepeval_judge(_build_judge_client()), include_reason=True
    )
    metric.measure(test_case)

    return {
        "scenario": "diagnostics",
        "route": final_state["route"],
        "expected_route": "diagnostics",
        "tools_called": recorder.tool_calls_seen,
        "expected_tools": [t.name for t in expected_tools],
        "tool_correctness_score": metric.score,
        "tool_correctness_reason": metric.reason,
    }


async def _run_knowledge_scenario() -> dict[str, Any]:
    from deepeval.metrics import ToolCorrectnessMetric
    from deepeval.test_case import LLMTestCase
    from deepeval.test_case import ToolCall as DeepEvalToolCall

    from app.evals.judge_adapter import build_deepeval_judge

    hits = [
        KBHit(
            chunk_id=1,
            source="Honda Civic Service Guide (Synthetic)",
            section="Brake Service",
            text=(
                "Front brake pads on a Civic typically last 35,000-45,000 km in mixed "
                "driving. Brake fluid is commonly replaced every 3 years or 60,000 km as a "
                "conservative interval, since Honda's own fluid spec is DOT 3 which absorbs "
                "moisture faster than DOT 4."
            ),
            score=0.91,
        )
    ]
    recorder = _ToolCallRecordingClient(ReplayClient(cassette_dir=DEEPEVAL_CASSETTE_DIR))
    deps = AgentDeps(vehicle_data=_NoVehicleData(), kb=_FakeKBSearchProvider(hits))
    final_state = await ask(recorder, deps, KNOWLEDGE_QUESTION, run_id="deepeval-knowledge-fixture")

    expected_tools = [DeepEvalToolCall(name="search_kb")]
    test_case = LLMTestCase(
        input=KNOWLEDGE_QUESTION,
        actual_output=final_state["answer"],
        tools_called=[DeepEvalToolCall(name=n) for n in recorder.tool_calls_seen],
        expected_tools=expected_tools,
    )
    # Deterministic-only path here (no `available_tools`, so the judge LLM
    # is never actually invoked for scoring - see module docstring for why
    # that path is exercised once, on the diagnostics scenario, rather than
    # on both) - `model=` is still always this project's own adapter,
    # never DeepEval's own default, to avoid `initialize_model(None)`
    # eagerly constructing a real `GPTModel` (which requires
    # `OPENAI_API_KEY`) purely to sit unused; see this phase's report.
    metric = ToolCorrectnessMetric(model=build_deepeval_judge(_build_judge_client()), include_reason=True)
    metric.measure(test_case)

    return {
        "scenario": "knowledge",
        "route": final_state["route"],
        "expected_route": "knowledge",
        "tools_called": recorder.tool_calls_seen,
        "expected_tools": [t.name for t in expected_tools],
        "tool_correctness_score": metric.score,
        "tool_correctness_reason": metric.reason,
    }


async def run_deepeval_suite() -> dict[str, Any]:
    """Pure computation, no printing/exit - so tests can call this directly."""
    diagnostics = await _run_diagnostics_scenario()
    knowledge = await _run_knowledge_scenario()
    return {"scenarios": [diagnostics, knowledge]}


def _print_report(results: dict[str, Any]) -> None:
    for scenario in results["scenarios"]:
        route_ok = scenario["route"] == scenario["expected_route"]
        tools_ok = scenario["tools_called"] == scenario["expected_tools"]
        print(
            f"{scenario['scenario']:<12} route={scenario['route']!r} "
            f"(expected {scenario['expected_route']!r}, {'OK' if route_ok else 'MISMATCH'})  "
            f"tools_called={scenario['tools_called']} (expected {scenario['expected_tools']}, "
            f"{'OK' if tools_ok else 'MISMATCH'})  tool_correctness_score={scenario['tool_correctness_score']:.4f}"
        )


def _check_scenarios(results: dict[str, Any]) -> list[str]:
    failures = []
    for scenario in results["scenarios"]:
        name = scenario["scenario"]
        if scenario["route"] != scenario["expected_route"]:
            failures.append(f"{name}: route {scenario['route']!r} != expected {scenario['expected_route']!r}")
        if scenario["tools_called"] != scenario["expected_tools"]:
            failures.append(
                f"{name}: tools_called {scenario['tools_called']} != expected {scenario['expected_tools']}"
            )
        if scenario["tool_correctness_score"] < 1.0:
            failures.append(f"{name}: tool_correctness_score {scenario['tool_correctness_score']:.4f} < 1.0")
    return failures


def main() -> int:
    import asyncio

    results = asyncio.run(run_deepeval_suite())
    _print_report(results)

    failures = _check_scenarios(results)
    if failures:
        print("\nDeepEval suite FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nDeepEval suite PASSED - supervisor picked the right specialist and tool in every scenario.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
