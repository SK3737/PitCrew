"""
Supervisor graph: a LangGraph `StateGraph` whose entry node classifies the
user's question's intent (diagnostics / scheduling / knowledge) and routes
to the matching specialist node, then a compose node shapes the final
answer.

Node/edge shape
----------------
::

    START -> classify_intent --route--> diagnostics  -\
                              --route--> scheduling   --> compose -> END
                              --route--> knowledge    -/

`classify_intent` is the only node that calls `LLMClient.complete()`
directly rather than through a PydanticAI agent - it asks the model to name
the route in one word. This keeps intent classification provable via
`ReplayClient` exactly like every other LLM call in the app: a test only
needs a cassette recorded for the classification request, same as for a
specialist's cassette (see `backend/tests/test_supervisor_routing.py`). If
the model's answer doesn't parse cleanly into one of the three routes,
classification falls back to `"knowledge"` - the safest default, since it
degrades to "no documentation on this" rather than misfiring a write path
(scheduling) or a wrong prediction claim (diagnostics).

State
-----
`SupervisorState` carries the question, the resolved route, each
specialist's tool results, the `iterations` counter the guardrails module
checks every node visit against, and a `run_id` used to correlate the whole
trajectory (and, if Langfuse keys are configured, its trace spans - see
`app.agents.tracing`).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Literal, Optional, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.guardrails import FRIENDLY_RATE_LIMIT_MESSAGE, enforce_iteration_budget
from app.agents.llm_client import LLMClient, RateLimited
from app.agents.specialists.diagnostics import run_diagnostics
from app.agents.specialists.knowledge import run_knowledge
from app.agents.specialists.scheduling import run_scheduling
from app.agents.tools import AgentDeps
from app.agents.tracing import trace_span

logger = logging.getLogger(__name__)

Route = Literal["diagnostics", "scheduling", "knowledge"]
ROUTES: tuple[Route, ...] = ("diagnostics", "scheduling", "knowledge")

CLASSIFY_SYSTEM_PROMPT = (
    "Classify the user's question into exactly one route. Respond with "
    "only that one word, lowercase, nothing else.\n"
    "- diagnostics: questions about when or whether a specific vehicle "
    "needs service, based on its mileage or history.\n"
    "- scheduling: requests to book, confirm, or cancel a service "
    "appointment.\n"
    "- knowledge: general questions about maintenance, procedures, or "
    "policy that aren't about one specific vehicle's due date or a "
    "booking."
)


class SupervisorState(TypedDict, total=False):
    question: str
    route: Route | Literal["degraded"]
    answer: str
    tool_results: dict[str, Any]
    citations: list[dict[str, Any]]
    run_id: str
    iterations: int


def classify_intent_text(llm_client: LLMClient, question: str) -> Route:
    """Direct `LLMClient.complete()` call - see module docstring for why
    this isn't a PydanticAI agent."""
    response = llm_client.complete(
        [
            {"role": "system", "content": CLASSIFY_SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ],
        temperature=0.0,
        seed=0,
    )
    text = (response.content or "").strip().lower()
    for route in ROUTES:
        if route in text:
            return route
    logger.warning("Could not parse intent %r - defaulting to knowledge", text)
    return "knowledge"


def build_supervisor_graph(llm_client: LLMClient, deps: AgentDeps) -> CompiledStateGraph:
    """Construct the compiled supervisor StateGraph, closing over
    `llm_client` and `deps` so node functions need no extra wiring from
    LangGraph itself (LangGraph nodes only ever receive `state`)."""

    async def classify_intent(state: SupervisorState) -> dict[str, Any]:
        iterations = state.get("iterations", 0) + 1
        enforce_iteration_budget(iterations)
        try:
            with trace_span("classify_intent", run_id=state.get("run_id")):
                route = classify_intent_text(llm_client, state["question"])
        except RateLimited:
            # Guardrail (c): a rate limit here must degrade exactly like a
            # rate limit inside a specialist does - never an unhandled
            # exception / 500. Route straight to compose with the friendly
            # message instead of attempting a specialist that would almost
            # certainly hit the same rate limit immediately after.
            return {"route": "degraded", "answer": FRIENDLY_RATE_LIMIT_MESSAGE, "iterations": iterations}
        return {"route": route, "iterations": iterations}

    def route_from_state(state: SupervisorState) -> str:
        return state["route"]

    async def diagnostics_node(state: SupervisorState) -> dict[str, Any]:
        iterations = state.get("iterations", 0) + 1
        enforce_iteration_budget(iterations)
        try:
            with trace_span("diagnostics", run_id=state.get("run_id")):
                result = await run_diagnostics(llm_client, deps, state["question"])
        except RateLimited:
            return {"answer": FRIENDLY_RATE_LIMIT_MESSAGE, "iterations": iterations}
        return {
            "answer": result.answer,
            "tool_results": {"predict_service": result.prediction.model_dump() if result.prediction else None},
            "iterations": iterations,
        }

    async def scheduling_node(state: SupervisorState) -> dict[str, Any]:
        iterations = state.get("iterations", 0) + 1
        enforce_iteration_budget(iterations)
        try:
            with trace_span("scheduling", run_id=state.get("run_id")):
                result = await run_scheduling(llm_client, deps, state["question"])
        except RateLimited:
            return {"answer": FRIENDLY_RATE_LIMIT_MESSAGE, "iterations": iterations}
        return {
            "answer": result.answer,
            "tool_results": {"schedule_service": result.booking.model_dump() if result.booking else None},
            "iterations": iterations,
        }

    async def knowledge_node(state: SupervisorState) -> dict[str, Any]:
        iterations = state.get("iterations", 0) + 1
        enforce_iteration_budget(iterations)
        try:
            with trace_span("knowledge", run_id=state.get("run_id")):
                result = await run_knowledge(llm_client, deps, state["question"])
        except RateLimited:
            return {"answer": FRIENDLY_RATE_LIMIT_MESSAGE, "iterations": iterations}
        return {
            "answer": result.answer,
            "citations": [c.model_dump() for c in result.citations],
            "iterations": iterations,
        }

    def compose(state: SupervisorState) -> dict[str, Any]:
        # Pass-through today - each specialist already produces a citable,
        # typed answer - kept as its own node so a later phase (e.g. RAG
        # citation footnotes) can add cross-specialist formatting without
        # touching routing.
        return {"answer": state.get("answer", "")}

    graph: StateGraph[SupervisorState] = StateGraph(SupervisorState)
    graph.add_node("classify_intent", classify_intent)
    graph.add_node("diagnostics", diagnostics_node)
    graph.add_node("scheduling", scheduling_node)
    graph.add_node("knowledge", knowledge_node)
    graph.add_node("compose", compose)

    graph.add_edge(START, "classify_intent")
    graph.add_conditional_edges(
        "classify_intent",
        route_from_state,
        {
            "diagnostics": "diagnostics",
            "scheduling": "scheduling",
            "knowledge": "knowledge",
            "degraded": "compose",
        },
    )
    graph.add_edge("diagnostics", "compose")
    graph.add_edge("scheduling", "compose")
    graph.add_edge("knowledge", "compose")
    graph.add_edge("compose", END)

    return graph.compile()


async def ask(
    llm_client: LLMClient,
    deps: AgentDeps,
    question: str,
    run_id: Optional[str] = None,
) -> SupervisorState:
    """Entry point `routers/assistant.py` uses: run the compiled graph once
    end to end and return its final state (answer + full trajectory)."""
    compiled = build_supervisor_graph(llm_client, deps)
    initial: SupervisorState = {
        "question": question,
        "run_id": run_id or str(uuid.uuid4()),
        "iterations": 0,
    }
    final_state = await compiled.ainvoke(initial)
    return final_state
