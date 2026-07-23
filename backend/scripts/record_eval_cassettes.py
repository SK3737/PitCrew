"""
Task 9.1 fixture authoring: produces the committed judge-LLM cassettes under
`backend/cassettes/evals/` that let `make eval`'s Ragas suite
(`app.evals.ragas_suite`) run deterministically offline under
`LLM_BACKEND=replay`.

Same convention Phase 7 established for `backend/cassettes/golden/` (see
`.superpowers/sdd/task-7-report.md`, "How the golden cassettes were
produced") and this repo's own routing tests
(`backend/tests/test_supervisor_routing.py`'s `_ScriptedClient`): a scripted
`LLMClient` returns a hand-written list of judge responses in the exact
order the real Ragas metric code calls `agenerate()`, recording each one via
`app.agents.llm_client.record_cassette` as the *real* `ascore()` methods run
- so every cassette's filename is the real `request_hash` of the real prompt
Ragas built (via `BasePrompt.to_string`), never a hand-computed hash. Only
the judge's *answers* (the JSON payloads below) are authored by hand; the
prompts themselves, the eval cases they're built from
(`app.evals.dataset.EVAL_CASES`), and the final metric scores are all real,
computed output.

Not run automatically by `make eval` or CI - this is the one-time (or
re-run-on-dataset-change) authoring step, exactly like
`backend/scripts/record_cassettes.py` is for the golden scenarios. Run it
directly (`python -m scripts.record_eval_cassettes`) after changing
`app.evals.dataset.EVAL_CASES`, then commit the regenerated
`backend/cassettes/evals/*.json` files.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.agents.llm_client import LLMClient, LLMResponse, ReplayClient, ToolCall, record_cassette
from app.evals.dataset import EVAL_CASES
from app.evals.judge_adapter import RagasReplayLLM

EVALS_CASSETTE_DIR = Path(__file__).resolve().parents[1] / "cassettes" / "evals"
DEEPEVAL_CASSETTE_DIR = Path(__file__).resolve().parents[1] / "cassettes" / "evals" / "deepeval"
JUDGE_MODEL = "replay"

# Task 9.2's second (knowledge/search_kb) trajectory scenario. Deliberately
# NOT the committed `cassettes/golden/` knowledge scenario: that fixture's
# replayability depends on `KBChunk.chunk_id` being a fresh auto-increment
# sequence, which only holds under pytest's autouse `_clean_database`
# fixture (see task-7-report.md, "Important coupling to document") - a
# concrete gap for `make eval`, which the brief allows running standalone
# outside pytest, potentially against a dev database that already has KB
# rows ingested. This scenario uses a fake, DB-free `KBSearchProvider`
# instead (grounded in the same real Honda Civic KB text
# `app.evals.dataset` uses), so the DeepEval suite never touches Postgres.
DEEPEVAL_KNOWLEDGE_QUESTION = "How often should Honda Civic brake fluid be replaced?"


class _ScriptedClient(LLMClient):
    """Same pattern as `tests/test_supervisor_routing.py`'s `_ScriptedClient`:
    replays a pre-scripted list of responses in call order, recording each
    into `cassette_dir` as it goes."""

    def __init__(self, cassette_dir: Path, script: list[LLMResponse]) -> None:
        self._dir = cassette_dir
        self._script = list(script)
        self._i = 0

    def complete(self, messages, tools=None, *, temperature=0.0, seed=None, **params):
        response = self._script[self._i]
        self._i += 1
        record_cassette(self._dir, JUDGE_MODEL, messages, tools, response, temperature=temperature, seed=seed)
        return response


def _json_response(payload: dict) -> LLMResponse:
    return LLMResponse(content=json.dumps(payload))


# ---------------------------------------------------------------------------
# Hand-authored judge outputs, one script per (case, metric) pair. Statement
# text is deliberately reused verbatim between a case's Faithfulness
# statement-generator output and its NLI/ContextRecall verdicts, since a
# real judge would decompose the same answer the same way each time it's
# asked to reference "the statements below" - this is the one place the
# script must stay internally consistent by hand, since each cassette is
# independently keyed by its own prompt content.
# ---------------------------------------------------------------------------

_CASE_SCRIPTS: dict[str, dict] = {
    "bmw_coolant_flush": {
        "statements": [
            "BMW's factory long-life coolant is rated for roughly 4-6 years or 100,000-150,000 km.",
            "After that period, a full flush is recommended to protect the aluminium engine block from corrosion as seals age.",
            "The full flush also protects plastic coolant system components from corrosion as seals age.",
        ],
        "faithfulness_verdicts": [1, 1, 1],  # all three grounded in the real BMW passage
        "context_precision_verdicts": [0, 1],  # distractor (ranked first) not useful, real passage useful
        "context_recall_attributed": [1, 1, 1],
        "generated_question": "How frequently does a BMW 3 Series need a coolant flush?",
        "noncommittal": 0,
    },
    "civic_brake_fluid": {
        "statements": [
            "Honda Civic brake fluid is commonly replaced every 3 years or 60,000 km.",
            "This is a conservative interval because Honda's DOT 3 fluid absorbs moisture faster than DOT 4 fluid.",
        ],
        "faithfulness_verdicts": [1, 1],
        "context_precision_verdicts": [1],
        "context_recall_attributed": [1, 1],
        "generated_question": "How often does Honda recommend changing Civic brake fluid?",
        "noncommittal": 0,
    },
    "corolla_oil_change": {
        "statements": [
            "The Corolla's engines typically run on 0W-16 or 0W-20 full-synthetic oil.",
            "An oil and filter change is recommended every 10,000 km or 12 months under normal driving.",
            "Vehicles under severe conditions such as short trips, towing, or dust should be serviced closer to every 5,000 km.",
            "Using synthetic oil also improves fuel economy by roughly 5%.",
        ],
        # The 4th statement (fuel economy) is not supported by the retrieved
        # context - the deliberately-unfaithful claim, see dataset.py.
        "faithfulness_verdicts": [1, 1, 1, 0],
        "context_precision_verdicts": [1],
        "context_recall_attributed": [1, 1, 1, 0],
        "generated_question": "How often does a Toyota Corolla need an oil change?",
        "noncommittal": 0,
    },
}


def _faithfulness_script(case_id: str) -> list[LLMResponse]:
    script = _CASE_SCRIPTS[case_id]
    statements = script["statements"]
    verdicts = script["faithfulness_verdicts"]
    return [
        _json_response({"statements": statements}),
        _json_response(
            {
                "statements": [
                    {"statement": s, "reason": "See retrieved context.", "verdict": v}
                    for s, v in zip(statements, verdicts)
                ]
            }
        ),
    ]


def _context_precision_script(case_id: str) -> list[LLMResponse]:
    verdicts = _CASE_SCRIPTS[case_id]["context_precision_verdicts"]
    return [
        _json_response({"reason": "See judgment for this retrieved passage.", "verdict": v})
        for v in verdicts
    ]


def _context_recall_script(case_id: str) -> list[LLMResponse]:
    script = _CASE_SCRIPTS[case_id]
    statements = script["statements"]
    attributed = script["context_recall_attributed"]
    return [
        _json_response(
            {
                "classifications": [
                    {"statement": s, "reason": "See retrieved context.", "attributed": a}
                    for s, a in zip(statements, attributed)
                ]
            }
        )
    ]


def _answer_relevancy_script(case_id: str) -> list[LLMResponse]:
    script = _CASE_SCRIPTS[case_id]
    return [_json_response({"question": script["generated_question"], "noncommittal": script["noncommittal"]})]


async def _record_all() -> None:
    from ragas.metrics.collections import AnswerRelevancy, ContextPrecision, ContextRecall, Faithfulness

    from app.evals.judge_adapter import RagasLocalEmbedding

    EVALS_CASSETTE_DIR.mkdir(parents=True, exist_ok=True)
    embeddings = RagasLocalEmbedding()

    for case in EVAL_CASES:
        faithfulness = Faithfulness(llm=RagasReplayLLM(_ScriptedClient(EVALS_CASSETTE_DIR, _faithfulness_script(case.case_id))))
        result = await faithfulness.ascore(
            user_input=case.question, response=case.response, retrieved_contexts=case.retrieved_contexts
        )
        print(f"[record] {case.case_id} faithfulness = {result.value:.4f}")

        precision = ContextPrecision(
            llm=RagasReplayLLM(_ScriptedClient(EVALS_CASSETTE_DIR, _context_precision_script(case.case_id)))
        )
        result = await precision.ascore(
            user_input=case.question, reference=case.reference, retrieved_contexts=case.retrieved_contexts
        )
        print(f"[record] {case.case_id} context_precision = {result.value:.4f}")

        recall = ContextRecall(llm=RagasReplayLLM(_ScriptedClient(EVALS_CASSETTE_DIR, _context_recall_script(case.case_id))))
        result = await recall.ascore(
            user_input=case.question, retrieved_contexts=case.retrieved_contexts, reference=case.reference
        )
        print(f"[record] {case.case_id} context_recall = {result.value:.4f}")

        relevancy = AnswerRelevancy(
            llm=RagasReplayLLM(_ScriptedClient(EVALS_CASSETTE_DIR, _answer_relevancy_script(case.case_id))),
            embeddings=embeddings,
            strictness=1,
        )
        result = await relevancy.ascore(user_input=case.question, response=case.response)
        print(f"[record] {case.case_id} answer_relevancy = {result.value:.4f}")


async def _verify_replay() -> None:
    """Second, independent pass (Phase 7 convention): a fresh `ReplayClient`
    pointed at the just-recorded directory reproduces every score with no
    scripted client involved at all."""
    from ragas.metrics.collections import AnswerRelevancy, ContextPrecision, ContextRecall, Faithfulness

    from app.evals.judge_adapter import RagasLocalEmbedding

    embeddings = RagasLocalEmbedding()
    replay = ReplayClient(cassette_dir=EVALS_CASSETTE_DIR, model=JUDGE_MODEL)

    for case in EVAL_CASES:
        judge = RagasReplayLLM(replay)
        f = await Faithfulness(llm=judge).ascore(
            user_input=case.question, response=case.response, retrieved_contexts=case.retrieved_contexts
        )
        p = await ContextPrecision(llm=judge).ascore(
            user_input=case.question, reference=case.reference, retrieved_contexts=case.retrieved_contexts
        )
        r = await ContextRecall(llm=judge).ascore(
            user_input=case.question, retrieved_contexts=case.retrieved_contexts, reference=case.reference
        )
        a = await AnswerRelevancy(llm=judge, embeddings=embeddings, strictness=1).ascore(
            user_input=case.question, response=case.response
        )
        print(
            f"[verify] {case.case_id}: faithfulness={f.value:.4f} "
            f"context_precision={p.value:.4f} context_recall={r.value:.4f} answer_relevancy={a.value:.4f}"
        )


async def _record_deepeval_knowledge_scenario() -> None:
    """Records the DB-free knowledge/`search_kb` trajectory scenario DeepEval's
    suite (`app.evals.deepeval_suite`) replays - see module docstring for
    why this isn't just the committed `cassettes/golden/` knowledge scenario.
    Same `_ScriptedClient`-records-as-the-real-`ask()`-graph-runs-once
    convention as `tests/test_supervisor_routing.py`."""
    from app.agents.supervisor import ask
    from app.agents.tools import AgentDeps, KBHit

    class _NoVehicleData:
        async def get_snapshot(self, vehicle_id: str):
            return None

    class _FakeKBSearchProvider:
        def __init__(self, hits: list[KBHit]) -> None:
            self._hits = hits

        async def search(self, query: str) -> list[KBHit]:
            return self._hits

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
    deps = AgentDeps(vehicle_data=_NoVehicleData(), kb=_FakeKBSearchProvider(hits))

    script = [
        LLMResponse(content="knowledge"),  # classify_intent
        LLMResponse(
            tool_calls=[ToolCall(id="call_1", name="search_kb", arguments={"query": DEEPEVAL_KNOWLEDGE_QUESTION})]
        ),  # turn 1: call the tool
        LLMResponse(
            content=(
                "Honda Civic brake fluid is commonly replaced every 3 years or 60,000 km, "
                "a conservative interval since Honda's DOT 3 fluid absorbs moisture faster "
                "than DOT 4. [1]"
            )
        ),  # turn 2: final answer
    ]

    DEEPEVAL_CASSETTE_DIR.mkdir(parents=True, exist_ok=True)
    scripted = _ScriptedClient(DEEPEVAL_CASSETTE_DIR, script)
    # Pinned run_id: `ask()` auto-generates a fresh uuid4 per call otherwise
    # (see `app.agents.supervisor.ask`), which would make the record vs.
    # replay `final_state` dicts differ on that field alone even though
    # everything cassette-derived is identical.
    final_state = await ask(scripted, deps, DEEPEVAL_KNOWLEDGE_QUESTION, run_id="deepeval-knowledge-fixture")

    # Verify: fresh ReplayClient, no scripted client, same real ask() entrypoint.
    replay = ReplayClient(cassette_dir=DEEPEVAL_CASSETTE_DIR)
    verified_state = await ask(replay, deps, DEEPEVAL_KNOWLEDGE_QUESTION, run_id="deepeval-knowledge-fixture")
    assert verified_state == final_state, "deepeval knowledge scenario did not replay deterministically"
    print(f"[verify] deepeval knowledge scenario replayed identically: route={verified_state['route']!r}")


def _record_deepeval_tool_selection_judge_cassette() -> None:
    """Records the one DeepEval judge-LLM cassette this suite exercises:
    `ToolCorrectnessMetric`'s optional `available_tools` path, which - unlike
    its default deterministic tool-name comparison, see
    `deepeval.metrics.tool_correctness.tool_correctness.ToolCorrectnessMetric._generate_reason`
    - genuinely calls the configured judge LLM (here,
    `app.evals.judge_adapter.build_deepeval_judge`) to score whether the
    tool the supervisor picked was the *right* one out of the tools it could
    have picked. Demonstrates the DeepEval side of the judge adapter
    actually being exercised end-to-end under replay, not just imported.

    Synchronous (not `asyncio.run`) - `ToolCorrectnessMetric.measure()`
    manages its own event loop internally (see its `async_mode` branch) and
    raises if called from inside one already running.
    """
    from deepeval.metrics import ToolCorrectnessMetric
    from deepeval.test_case import LLMTestCase
    from deepeval.test_case import ToolCall as DeepEvalToolCall

    from app.evals.judge_adapter import build_deepeval_judge

    question = "When does V001 need its next service?"
    answer = "V001 needs service in about 38 days or 1474 km, whichever comes first."
    available_tools = [
        DeepEvalToolCall(name="predict_service"),
        DeepEvalToolCall(name="search_kb"),
        DeepEvalToolCall(name="schedule_service"),
    ]
    test_case = LLMTestCase(
        input=question,
        actual_output=answer,
        tools_called=[DeepEvalToolCall(name="predict_service")],
        expected_tools=[DeepEvalToolCall(name="predict_service")],
    )

    judge_response = LLMResponse(
        content=json.dumps(
            {
                "score": 1.0,
                "reason": (
                    "predict_service is the correct tool for a question about when a "
                    "specific vehicle needs its next service, out of the tools available."
                ),
            }
        )
    )
    scripted = _ScriptedClient(DEEPEVAL_CASSETTE_DIR, [judge_response])
    metric = ToolCorrectnessMetric(
        available_tools=available_tools, model=build_deepeval_judge(scripted), include_reason=True
    )
    metric.measure(test_case)
    score = metric.score
    print(f"[record] deepeval tool_selection_score judge cassette -> score={score:.4f} reason={metric.reason!r}")

    replay = ReplayClient(cassette_dir=DEEPEVAL_CASSETTE_DIR)
    verify_metric = ToolCorrectnessMetric(
        available_tools=available_tools, model=build_deepeval_judge(replay), include_reason=True
    )
    verify_metric.measure(test_case)
    assert verify_metric.score == score, "deepeval tool_selection_score cassette did not replay deterministically"
    print(f"[verify] deepeval tool_selection_score replayed identically: score={verify_metric.score:.4f}")


def main() -> None:
    asyncio.run(_record_all())
    print("\n--- verifying replay from the just-recorded cassette directory ---\n")
    asyncio.run(_verify_replay())
    print("\n--- recording the DeepEval DB-free knowledge trajectory scenario ---\n")
    asyncio.run(_record_deepeval_knowledge_scenario())
    print("\n--- recording the DeepEval tool-selection judge cassette ---\n")
    _record_deepeval_tool_selection_judge_cassette()


if __name__ == "__main__":
    main()
