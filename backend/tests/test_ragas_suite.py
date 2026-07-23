"""
Task 9.1: the Ragas suite must run deterministically offline under
`LLM_BACKEND=replay` and produce the expected discriminating scores against
`app.evals.dataset.EVAL_CASES` - not a trivial 1.0 everywhere (see that
module's docstring for the two deliberately-imperfect cases).

These are the actual scores this suite produces in this environment (see
`.superpowers/sdd/task-9-report.md` for the full breakdown); asserted with a
small tolerance since `answer_relevancy` depends on the real local
sentence-transformers embedding model's cosine similarity, not a
hand-scripted number.
"""

from __future__ import annotations

import pytest

from app.evals.ragas_suite import THRESHOLDS, run_ragas_suite


@pytest.fixture
def results():
    import asyncio

    return asyncio.run(run_ragas_suite())


def test_produces_one_row_per_eval_case(results):
    case_ids = {c["case_id"] for c in results["per_case"]}
    assert case_ids == {"bmw_coolant_flush", "civic_brake_fluid", "corolla_oil_change"}


def test_bmw_case_has_reduced_context_precision_from_the_ranked_distractor(results):
    """`bmw_coolant_flush` ranks an irrelevant distractor passage first (see
    `app.evals.dataset`), so average precision must be below 1.0."""
    case = next(c for c in results["per_case"] if c["case_id"] == "bmw_coolant_flush")
    assert case["context_precision"] == pytest.approx(0.5, abs=1e-6)
    assert case["faithfulness"] == pytest.approx(1.0, abs=1e-6)
    assert case["context_recall"] == pytest.approx(1.0, abs=1e-6)


def test_corolla_case_has_reduced_faithfulness_and_recall_from_the_unsupported_claim(results):
    """`corolla_oil_change`'s response includes one claim the retrieved
    context doesn't support (see `app.evals.dataset`), so both faithfulness
    and context recall must be below 1.0."""
    case = next(c for c in results["per_case"] if c["case_id"] == "corolla_oil_change")
    assert case["faithfulness"] == pytest.approx(0.75, abs=1e-6)
    assert case["context_recall"] == pytest.approx(0.75, abs=1e-6)
    assert case["context_precision"] == pytest.approx(1.0, abs=1e-6)


def test_civic_case_is_fully_faithful_and_precise(results):
    case = next(c for c in results["per_case"] if c["case_id"] == "civic_brake_fluid")
    assert case["faithfulness"] == pytest.approx(1.0, abs=1e-6)
    assert case["context_precision"] == pytest.approx(1.0, abs=1e-6)
    assert case["context_recall"] == pytest.approx(1.0, abs=1e-6)


def test_answer_relevancy_is_high_for_every_case_via_real_local_embeddings(results):
    """Not cassette-backed (see `app.evals.judge_adapter.RagasLocalEmbedding`)
    - a real local sentence-transformers cosine similarity between each
    case's original question and its (hand-scripted) generated question, so
    the exact value depends on model internals; only the range is asserted."""
    for case in results["per_case"]:
        assert 0.7 <= case["answer_relevancy"] <= 1.0


def test_mean_scores_all_clear_the_ci_gate_thresholds(results):
    """Task 9.4's CI gate: `make eval` must fail the build if any metric's
    mean score drops below its threshold - confirm the suite's own means
    clear `THRESHOLDS` today, so this test would go red first if a future
    dataset change regressed a metric below its gate."""
    for metric, threshold in THRESHOLDS.items():
        assert results["means"][metric] >= threshold, f"{metric} mean below its own CI threshold"


def test_deliberately_regressed_thresholds_would_fail_the_gate():
    """Proves `_check_thresholds` actually gates - not just decorative
    constants nothing reads."""
    from app.evals.ragas_suite import _check_thresholds

    fake_results = {"means": {"faithfulness": 0.1, "context_precision": 0.1, "context_recall": 0.1, "answer_relevancy": 0.1}}
    failures = _check_thresholds(fake_results)
    assert len(failures) == 4
