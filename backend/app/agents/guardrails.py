"""
Guardrails wired into the supervisor graph (app.agents.supervisor):

(a) Scheduling confirmation - enforced at the tool boundary itself
    (`app.agents.tools.schedule_service` never calls `Scheduler.schedule`
    unless `confirmed=True`), so it holds no matter what a specialist's
    prompt says or how a model behaves. See
    `backend/tests/test_guardrails.py::test_schedule_requires_confirmation`.

(b) Iteration budget - `MAX_ITERATIONS` bounds how many supervisor-graph
    node visits a single run may take. `enforce_iteration_budget` is called
    at the top of every node in `app.agents.supervisor` with the
    post-increment counter; once it's exceeded, `MaxIterationsExceeded`
    aborts the run rather than letting a routing loop hang.

(c) Rate-limit degrade - `run_with_rate_limit_guard` (used directly by
    tests) and the equivalent try/except wired into every specialist node
    in `app.agents.supervisor` catch `app.agents.llm_client.RateLimited`
    and return `FRIENDLY_RATE_LIMIT_MESSAGE` instead of letting the
    exception surface as a 500 at the FastAPI layer. See
    `backend/tests/test_guardrails.py::test_rate_limit_is_friendly`.
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable, TypeVar

from app.agents.llm_client import RateLimited

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 6

FRIENDLY_RATE_LIMIT_MESSAGE = (
    "The assistant is busy right now (rate limited by the LLM provider). "
    "Please try again in a moment."
)


class MaxIterationsExceeded(Exception):
    """Raised when a supervisor run exceeds MAX_ITERATIONS graph-node visits."""


def enforce_iteration_budget(iterations: int, *, limit: int = MAX_ITERATIONS) -> None:
    """Call with the post-increment node-visit count at the top of every
    supervisor graph node. Raises once a run has taken more steps than a
    normal (non-looping) trajectory ever should."""
    if iterations > limit:
        raise MaxIterationsExceeded(
            f"Supervisor run aborted after {iterations} graph-node visits "
            f"(limit {limit}) - likely a runaway routing loop."
        )


T = TypeVar("T")


async def run_with_rate_limit_guard(coro_fn: Callable[[], Awaitable[T]]) -> T | str:
    """Run an awaitable LLM-backed call, turning a RateLimited error into the
    friendly message instead of propagating it as an unhandled exception."""
    try:
        return await coro_fn()
    except RateLimited as exc:
        logger.warning("LLM backend rate limited: %s", exc)
        return FRIENDLY_RATE_LIMIT_MESSAGE
