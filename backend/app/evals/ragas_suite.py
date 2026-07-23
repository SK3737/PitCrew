"""
Task 9.1: Ragas suite over the fixed KB question set (`app.evals.dataset.EVAL_CASES`).

Computes faithfulness, answer relevancy, context precision, and context
recall for each case using `app.evals.judge_adapter.RagasReplayLLM` as the
judge - which is backed by `app.agents.llm_client.build_default_client()`,
so this suite runs under `LLM_BACKEND=replay` (this environment, CI,
deterministic, free - cassettes at `backend/cassettes/evals/`, see
`backend/scripts/record_eval_cassettes.py`) and, unmodified, under
`LLM_BACKEND=groq` for a real/manual eval run once a human has a live
`GROQ_API_KEY`.

Run directly: `python -m app.evals.ragas_suite` (what `make eval` invokes).
Exits non-zero - the CI gate - if any metric's mean score across the case
set drops below its threshold in `THRESHOLDS`.

"Print + write scores to eval_runs" (task 9.1): scores are printed to
stdout as a table and written to `backend/eval_runs/<UTC timestamp>.json` -
a plain append-only run log, not a database table. This project's `Files`
list for this phase names no new Alembic migration/ORM model for eval
results, and provisioning one wasn't requested - a file-based run log keeps
this suite runnable with zero database dependency (this project's Ragas
eval cases are themselves DB-free by design, see `app.evals.dataset`'s own
docstring), which matters because `make eval` must stay runnable even
outside the Postgres-backed CI job. If a later phase wants queryable eval
history in Postgres, `eval_runs/*.json` is the input to backfill it from.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.agents.llm_client import GroqClient, ReplayClient
from app.config import settings
from app.evals.dataset import EVAL_CASES
from app.evals.judge_adapter import RagasLocalEmbedding, RagasReplayLLM

EVAL_RUNS_DIR = Path(__file__).resolve().parents[2] / "eval_runs"
EVALS_CASSETTE_DIR = Path(__file__).resolve().parents[2] / "cassettes" / "evals"


def _build_judge_client():
    """Same `LLM_BACKEND` branch `build_default_client()` itself makes (see
    `app.agents.llm_client`), except the replay branch points at this
    suite's own dedicated `cassettes/evals/` directory rather than
    `build_default_client()`'s default `cassettes/` root - exactly the
    pattern `backend/tests/test_replay_mode.py` already established for the
    golden scenarios (`ReplayClient(cassette_dir=GOLDEN_DIR)`), since the
    eval judge cassettes are their own fixture set, not part of the app's
    general replay corpus."""
    if settings.LLM_BACKEND == "groq":
        return GroqClient()
    return ReplayClient(cassette_dir=EVALS_CASSETTE_DIR)


#: Minimum acceptable mean score per metric across the whole case set - the
#: CI gate task 9.4 requires ("fail the build if eval scores drop below
#: thresholds"). Set below this suite's actual current scores (see
#: task-9-report.md for the real numbers this suite produces) with margin
#: for the deliberately-imperfect cases in the dataset, not at a trivial 0.0.
THRESHOLDS: dict[str, float] = {
    "faithfulness": 0.70,
    "context_precision": 0.60,
    "context_recall": 0.70,
    "answer_relevancy": 0.70,
}


async def run_ragas_suite() -> dict[str, Any]:
    """Runs all four metrics over every case in `EVAL_CASES` and returns a
    results dict: per-case scores plus the mean per metric. Pure computation
    - no printing, no file I/O, no process exit - so tests can call this
    directly and assert on the returned scores."""
    from ragas.metrics.collections import AnswerRelevancy, ContextPrecision, ContextRecall, Faithfulness

    client = _build_judge_client()
    judge = RagasReplayLLM(client)
    embeddings = RagasLocalEmbedding()

    faithfulness = Faithfulness(llm=judge)
    context_precision = ContextPrecision(llm=judge)
    context_recall = ContextRecall(llm=judge)
    answer_relevancy = AnswerRelevancy(llm=judge, embeddings=embeddings, strictness=1)

    per_case: list[dict[str, Any]] = []
    for case in EVAL_CASES:
        f = await faithfulness.ascore(
            user_input=case.question, response=case.response, retrieved_contexts=case.retrieved_contexts
        )
        p = await context_precision.ascore(
            user_input=case.question, reference=case.reference, retrieved_contexts=case.retrieved_contexts
        )
        r = await context_recall.ascore(
            user_input=case.question, retrieved_contexts=case.retrieved_contexts, reference=case.reference
        )
        a = await answer_relevancy.ascore(user_input=case.question, response=case.response)
        per_case.append(
            {
                "case_id": case.case_id,
                "faithfulness": f.value,
                "context_precision": p.value,
                "context_recall": r.value,
                "answer_relevancy": a.value,
            }
        )

    means = {
        metric: sum(c[metric] for c in per_case) / len(per_case)
        for metric in ("faithfulness", "context_precision", "context_recall", "answer_relevancy")
    }
    return {"per_case": per_case, "means": means}


def _print_report(results: dict[str, Any]) -> None:
    header = f"{'case':<22}{'faithfulness':>14}{'ctx_precision':>15}{'ctx_recall':>12}{'ans_relevancy':>15}"
    print(header)
    print("-" * len(header))
    for c in results["per_case"]:
        print(
            f"{c['case_id']:<22}{c['faithfulness']:>14.4f}{c['context_precision']:>15.4f}"
            f"{c['context_recall']:>12.4f}{c['answer_relevancy']:>15.4f}"
        )
    print("-" * len(header))
    means = results["means"]
    print(
        f"{'MEAN':<22}{means['faithfulness']:>14.4f}{means['context_precision']:>15.4f}"
        f"{means['context_recall']:>12.4f}{means['answer_relevancy']:>15.4f}"
    )


def _write_run_log(results: dict[str, Any]) -> Path:
    EVAL_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = EVAL_RUNS_DIR / f"ragas-{timestamp}.json"
    path.write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _check_thresholds(results: dict[str, Any]) -> list[str]:
    failures = []
    for metric, threshold in THRESHOLDS.items():
        actual = results["means"][metric]
        if actual < threshold:
            failures.append(f"{metric} mean {actual:.4f} is below threshold {threshold:.4f}")
    return failures


def main() -> int:
    import asyncio

    results = asyncio.run(run_ragas_suite())
    _print_report(results)
    log_path = _write_run_log(results)
    print(f"\nWrote run log to {log_path}")

    failures = _check_thresholds(results)
    if failures:
        print("\nRagas suite FAILED - scores below threshold:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nRagas suite PASSED - all metrics at or above threshold.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
