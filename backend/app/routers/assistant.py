"""POST /assistant/ask - runs the LangGraph supervisor and returns the
answer plus its trajectory. Guarded by `use_assistant`/`use_assistant_replay`
(mechanic and demo roles - see app.auth.rbac.ROLE_PERMISSIONS).

POST /assistant/stream is the streaming sibling added in Phase 8 - see its
own docstring below for the SSE event contract."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, AsyncIterator, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.llm_client import CassetteMiss, LLMClient, ReplayClient, build_default_client
from app.agents.supervisor import ask, build_supervisor_graph
from app.agents.tools import AgentDeps, RepositoryKBSearchProvider, RepositoryVehicleDataProvider
from app.auth.rbac import ROLE_PERMISSIONS, require_permission
from app.db.session import get_session
from app.models.user import User

router = APIRouter(prefix="/assistant", tags=["assistant"])


def _llm_client_for_role(role: str) -> LLMClient:
    """Pick the LLMClient for the authenticated user's role.

    A role granted the full ``use_assistant`` permission (mechanic, admin)
    gets whatever ``settings.LLM_BACKEND`` says (``build_default_client()``).
    A role holding only ``use_assistant_replay`` (demo - the untrusted
    public-facing role) is always forced onto ``ReplayClient``, regardless
    of the ambient ``LLM_BACKEND`` setting. Without this, a future live
    deploy (``LLM_BACKEND=groq``) would transparently give `demo` users
    live Groq calls despite the permission name promising replay-only
    isolation.
    """
    if "use_assistant" in ROLE_PERMISSIONS.get(role, frozenset()):
        return build_default_client()
    return ReplayClient()


class AssistantAskRequest(BaseModel):
    question: str


class AssistantAskResponse(BaseModel):
    run_id: str
    route: Optional[str] = None
    answer: str
    tool_results: dict[str, Any] = {}
    citations: list[dict[str, Any]] = []


@router.post("/ask", response_model=AssistantAskResponse)
async def ask_assistant(
    payload: AssistantAskRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_permission("use_assistant", "use_assistant_replay")),
) -> AssistantAskResponse:
    llm_client = _llm_client_for_role(current_user.role)
    deps = AgentDeps(
        vehicle_data=RepositoryVehicleDataProvider(session),
        kb=RepositoryKBSearchProvider(session),
    )

    final_state = await ask(llm_client, deps, payload.question)

    return AssistantAskResponse(
        run_id=final_state.get("run_id", ""),
        route=final_state.get("route"),
        answer=final_state.get("answer", ""),
        tool_results=final_state.get("tool_results") or {},
        citations=final_state.get("citations") or [],
    )


class AssistantStreamRequest(BaseModel):
    question: str


# Display labels for AgentTrace.tsx - the raw LangGraph node name is always
# included in the event too, so a frontend that doesn't recognize a future
# node name can still fall back to it.
_NODE_LABELS: dict[str, str] = {
    "classify_intent": "Supervisor - classify intent",
    "diagnostics": "Diagnostics specialist",
    "scheduling": "Scheduling specialist",
    "knowledge": "Knowledge specialist",
    "compose": "Supervisor - compose answer",
}


def _sse(event: str, data: dict[str, Any]) -> str:
    """Format one Server-Sent Event message.

    Every event this endpoint emits is tagged with the run's `run_id` inside
    `data` (never only in a separate SSE `id:` field) so the frontend can
    correlate `token`/`trace`/`sources`/`done`/`error` events from the same
    request without depending on SSE's own `id:`/`retry:` machinery, which
    `fetch().body.getReader()` consumers don't get for free the way a real
    `EventSource` would.
    """
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _answer_chunks(answer: str) -> list[str]:
    """Split the composed answer into word-sized pieces for the `token`
    stream.

    No LLMClient implementation in this codebase streams token-by-token yet
    (see app.agents.llm_client's module docstring - both ReplayClient and
    GroqClient return one complete LLMResponse per call), and the
    supervisor graph resolves `answer` in a single specialist node rather
    than incrementally. Rather than block the whole SSE response until the
    graph finishes and then emit one giant `token` event, this simulates a
    live-typing stream over the final text - a documented, coarser
    alternative to true token-level streaming (see task-8-report.md).
    """
    if not answer:
        return []
    words = answer.split(" ")
    return [f"{w} " for w in words[:-1]] + [words[-1]]


async def _stream_assistant_events(
    llm_client: Any, deps: AgentDeps, question: str, run_id: str
) -> AsyncIterator[str]:
    """Run the supervisor graph via `astream(..., stream_mode="updates")`
    and translate its real per-node trajectory into SSE events.

    `stream_mode="updates"` yields one `{node_name: node_output}` dict right
    after each LangGraph node finishes - this is genuine node-level
    streaming (Supervisor's `classify_intent`/`compose` and whichever
    specialist node the route picked), not a simulation, and is what powers
    AgentTrace.tsx's live steps-with-timings view. Only the final answer
    text (no per-token model output exists to stream - see
    `_answer_chunks`) is chunked after the fact.
    """
    graph = build_supervisor_graph(llm_client, deps)
    initial: dict[str, Any] = {"question": question, "run_id": run_id, "iterations": 0}
    state: dict[str, Any] = dict(initial)
    last_ts = time.monotonic()

    try:
        async for update in graph.astream(initial, stream_mode="updates"):
            now = time.monotonic()
            duration_ms = round((now - last_ts) * 1000, 1)
            last_ts = now
            for node_name, node_output in update.items():
                state.update(node_output or {})
                yield _sse(
                    "trace",
                    {
                        "run_id": run_id,
                        "node": node_name,
                        "label": _NODE_LABELS.get(node_name, node_name),
                        "duration_ms": duration_ms,
                    },
                )
    except CassetteMiss as exc:
        # Replay mode's off-script guardrail (Phase 7): never fall back to a
        # live call, never crash the stream silently - tell the client.
        yield _sse("error", {"run_id": run_id, "message": str(exc)})
        return

    answer = state.get("answer", "")
    for chunk in _answer_chunks(answer):
        yield _sse("token", {"run_id": run_id, "text": chunk})

    yield _sse("sources", {"run_id": run_id, "citations": state.get("citations") or []})
    yield _sse(
        "done",
        {
            "run_id": run_id,
            "route": state.get("route"),
            "answer": answer,
            "tool_results": state.get("tool_results") or {},
        },
    )


@router.post("/stream")
async def stream_assistant(
    payload: AssistantStreamRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_permission("use_assistant", "use_assistant_replay")),
) -> StreamingResponse:
    """SSE sibling of POST /assistant/ask - same RBAC guard, same
    `AgentDeps` construction, same underlying supervisor graph. Emits (in
    order): zero or more `trace` events (one per LangGraph node actually
    visited), then either an `error` event (cassette miss in replay mode -
    stream ends there) or the `token` stream, a final `sources` event, and a
    `done` event carrying the full answer/route/tool_results as a
    convenience for consumers that don't want to reconstruct the answer by
    concatenating `token` events themselves.
    """
    llm_client = _llm_client_for_role(current_user.role)
    deps = AgentDeps(
        vehicle_data=RepositoryVehicleDataProvider(session),
        kb=RepositoryKBSearchProvider(session),
    )
    run_id = str(uuid.uuid4())

    return StreamingResponse(
        _stream_assistant_events(llm_client, deps, payload.question, run_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
