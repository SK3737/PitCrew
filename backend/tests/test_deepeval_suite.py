"""
Task 9.2: the DeepEval suite must run deterministically offline under
`LLM_BACKEND=replay`, over both scenarios, and confirm the supervisor picked
the right specialist (`route`) and the right tool (`ToolCorrectnessMetric`).
"""

from __future__ import annotations

import pytest

from app.evals.deepeval_suite import _check_scenarios, run_deepeval_suite


@pytest.fixture
def results():
    import asyncio

    return asyncio.run(run_deepeval_suite())


def test_both_scenarios_are_present(results):
    names = {s["scenario"] for s in results["scenarios"]}
    assert names == {"diagnostics", "knowledge"}


def test_diagnostics_scenario_routes_to_diagnostics_and_calls_predict_service(results):
    scenario = next(s for s in results["scenarios"] if s["scenario"] == "diagnostics")
    assert scenario["route"] == "diagnostics"
    assert scenario["tools_called"] == ["predict_service"]
    assert scenario["tool_correctness_score"] == 1.0


def test_knowledge_scenario_routes_to_knowledge_and_calls_search_kb(results):
    scenario = next(s for s in results["scenarios"] if s["scenario"] == "knowledge")
    assert scenario["route"] == "knowledge"
    assert scenario["tools_called"] == ["search_kb"]
    assert scenario["tool_correctness_score"] == 1.0


def test_no_scenario_failures_reported(results):
    assert _check_scenarios(results) == []


def test_check_scenarios_actually_catches_a_wrong_tool():
    """Proves the gate is load-bearing, not decorative."""
    broken = {
        "scenarios": [
            {
                "scenario": "diagnostics",
                "route": "diagnostics",
                "expected_route": "diagnostics",
                "tools_called": ["search_kb"],
                "expected_tools": ["predict_service"],
                "tool_correctness_score": 0.0,
            }
        ]
    }
    failures = _check_scenarios(broken)
    assert len(failures) == 2  # tools_called mismatch + score < 1.0
