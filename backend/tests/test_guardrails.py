"""
Guardrail tests - all offline (no LLM/network call anywhere in this file).

(a) Scheduling confirmation: exercises app.agents.tools.schedule_service
    directly, the way the graph invokes it (a RunContext-shaped stand-in
    exposing `.deps`, since the tool only ever reads `ctx.deps`).
(b) Iteration budget: exercises app.agents.guardrails.enforce_iteration_budget
    directly.
(c) Rate-limit degrade: exercises app.agents.guardrails.run_with_rate_limit_guard
    and the equivalent try/except wired into every supervisor graph node,
    using a fake LLMClient that raises RateLimited - never a real GroqClient
    or network call.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest

from app.agents.guardrails import (
    MAX_ITERATIONS,
    FRIENDLY_RATE_LIMIT_MESSAGE,
    MaxIterationsExceeded,
    enforce_iteration_budget,
    run_with_rate_limit_guard,
)
from app.agents.llm_client import LLMClient, RateLimited
from app.agents.supervisor import ask
from app.agents.tools import AgentDeps, InMemoryScheduler, schedule_service


@dataclass
class _FakeCtx:
    """schedule_service/predict_service only ever read `ctx.deps` - a bare
    stand-in is enough and avoids depending on PydanticAI's RunContext
    construction internals."""

    deps: AgentDeps


class _FakeVehicleData:
    async def get_snapshot(self, vehicle_id):
        return None


async def test_schedule_requires_confirmation():
    scheduler = InMemoryScheduler()
    deps = AgentDeps(vehicle_data=_FakeVehicleData(), scheduler=scheduler)
    ctx = _FakeCtx(deps=deps)

    result = await schedule_service(ctx, "V001", date(2026, 8, 1), confirmed=False)

    assert result.written is False
    assert scheduler.booked == []
    assert "confirm" in result.message.lower()


async def test_schedule_writes_once_confirmed():
    scheduler = InMemoryScheduler()
    deps = AgentDeps(vehicle_data=_FakeVehicleData(), scheduler=scheduler)
    ctx = _FakeCtx(deps=deps)

    result = await schedule_service(ctx, "V001", date(2026, 8, 1), confirmed=True)

    assert result.written is True
    assert scheduler.booked == [("V001", date(2026, 8, 1))]


def test_iteration_budget_allows_normal_runs():
    for i in range(1, MAX_ITERATIONS + 1):
        enforce_iteration_budget(i)  # must not raise


def test_iteration_budget_aborts_runaway_loop():
    with pytest.raises(MaxIterationsExceeded):
        enforce_iteration_budget(MAX_ITERATIONS + 1)


async def test_rate_limit_guard_returns_friendly_message_not_exception():
    async def _boom():
        raise RateLimited("HTTP 429 from Groq")

    result = await run_with_rate_limit_guard(_boom)

    assert result == FRIENDLY_RATE_LIMIT_MESSAGE


class _AlwaysRateLimitedClient(LLMClient):
    """Fake LLMClient - never a real GroqClient/network call - used to
    prove the supervisor graph degrades a RateLimited error gracefully."""

    def complete(self, messages, tools=None, *, temperature=0.0, seed=None, **params):
        raise RateLimited("HTTP 429 from Groq (fake, no network call made)")


async def test_rate_limit_from_classify_intent_degrades_gracefully():
    """classify_intent itself calls llm_client.complete() directly (see
    app.agents.supervisor) - a RateLimited error there must degrade to the
    same friendly message a specialist-level rate limit produces, not
    propagate as an unhandled exception (which would surface as a 500 at
    the FastAPI layer - see routers/assistant.py)."""
    deps = AgentDeps(vehicle_data=_FakeVehicleData())

    final_state = await ask(_AlwaysRateLimitedClient(), deps, "When does V001 need service?")

    assert final_state["answer"] == FRIENDLY_RATE_LIMIT_MESSAGE
    assert final_state["route"] == "degraded"
