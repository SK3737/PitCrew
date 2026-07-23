"""
POST /assistant/stream - SSE endpoint tests.

Two layers, mirroring test_assistant_route.py's split for /assistant/ask:

1. RBAC + wiring: `build_supervisor_graph` is monkeypatched to a stub graph
   so no LLM call happens - only the route's guard/event-framing is under
   test here.
2. A real, end-to-end replay of the knowledge golden scenario (see
   task-7-report.md / test_replay_mode.py for provenance) through the
   actual route, proving the SSE event stream this phase's frontend
   consumes is genuinely produced by the real supervisor graph + real KB
   retrieval, not just a mocked shape.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import app.routers.assistant as assistant_router
from app.agents.llm_client import GroqClient, ReplayClient
from app.config import settings
from app.rag.ingest import ingest_kb_directory
from tests.conftest import create_user_directly

PASSWORD = "correct horse battery staple"
GOLDEN_DIR = Path(__file__).resolve().parents[1] / "cassettes" / "golden"
KB_DIR = Path(__file__).resolve().parents[1] / "data" / "kb"
GOLDEN_KNOWLEDGE_QUESTION = "How often should I flush the coolant on a BMW 3 Series?"


async def _login(async_client, role: str) -> dict:
    email = f"{role}-{uuid.uuid4()}@example.com"
    await create_user_directly(email, PASSWORD, role=role)
    r = await async_client.post("/auth/login", json={"email": email, "password": PASSWORD})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    """Split a raw SSE response body into (event, data) pairs, in order."""
    events: list[tuple[str, dict]] = []
    for block in body.strip("\n").split("\n\n"):
        if not block.strip():
            continue
        event_line, data_line = block.split("\n", 1)
        assert event_line.startswith("event: ")
        assert data_line.startswith("data: ")
        events.append((event_line[len("event: ") :], json.loads(data_line[len("data: ") :])))
    return events


async def test_stream_requires_use_assistant_permission(async_client):
    headers = await _login(async_client, role="owner")  # owner has neither use_assistant permission

    response = await async_client.post("/assistant/stream", json={"question": "hi"}, headers=headers)

    assert response.status_code == 403


async def test_stream_emits_trace_token_sources_done_events_in_order(async_client, monkeypatch):
    """Wiring test: a stub graph with two nodes proves the route's SSE
    framing (event ordering, run_id tagging, token chunking) independent of
    the real LangGraph/LLM stack."""

    class _StubCompiledGraph:
        async def astream(self, initial, stream_mode="updates"):
            assert stream_mode == "updates"
            yield {"classify_intent": {"route": "knowledge", "iterations": 1}}
            yield {
                "knowledge": {
                    "answer": "Flush the coolant every 5 years.",
                    "citations": [{"chunk_id": 1, "source": "BMW Guide", "section": "Coolant Service"}],
                    "iterations": 2,
                }
            }

    monkeypatch.setattr(assistant_router, "build_supervisor_graph", lambda llm_client, deps: _StubCompiledGraph())

    headers = await _login(async_client, role="mechanic")
    response = await async_client.post(
        "/assistant/stream", json={"question": "How often should I flush the coolant?"}, headers=headers
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse(response.text)
    event_types = [e for e, _ in events]

    # Two trace events (one per stubbed node), then the token stream, then
    # exactly one sources event, then exactly one done event.
    assert event_types[0] == "trace"
    assert event_types[1] == "trace"
    assert event_types.count("sources") == 1
    assert event_types[-1] == "done"
    assert event_types.count("token") >= 1
    # every event carries the same run_id
    run_ids = {data["run_id"] for _, data in events}
    assert len(run_ids) == 1

    reconstructed = "".join(data["text"] for event, data in events if event == "token")
    assert reconstructed == "Flush the coolant every 5 years."

    sources_event = next(data for event, data in events if event == "sources")
    assert sources_event["citations"][0]["section"] == "Coolant Service"

    done_event = next(data for event, data in events if event == "done")
    assert done_event["route"] == "knowledge"
    assert done_event["answer"] == "Flush the coolant every 5 years."


async def test_stream_demo_role_is_forced_onto_replay_client_even_when_backend_is_groq(
    async_client, monkeypatch
):
    """Finding-1 regression test for the streaming sibling route: `demo`
    (holds only `use_assistant_replay`) must always be served via
    `ReplayClient`, regardless of the ambient `LLM_BACKEND` setting - see
    `assistant_router._llm_client_for_role`. Before the fix this route
    unconditionally called `build_default_client()`, which would have
    handed a `demo` caller a live `GroqClient` here."""
    monkeypatch.setattr(settings, "LLM_BACKEND", "groq")

    captured: dict[str, object] = {}

    class _StubCompiledGraph:
        async def astream(self, initial, stream_mode="updates"):
            yield {"knowledge": {"answer": "stub", "citations": [], "iterations": 1}}

    def _fake_build_supervisor_graph(llm_client, deps):
        captured["llm_client"] = llm_client
        return _StubCompiledGraph()

    monkeypatch.setattr(assistant_router, "build_supervisor_graph", _fake_build_supervisor_graph)

    headers = await _login(async_client, role="demo")
    response = await async_client.post("/assistant/stream", json={"question": "hi"}, headers=headers)

    assert response.status_code == 200
    assert isinstance(captured["llm_client"], ReplayClient)


async def test_stream_mechanic_role_honors_llm_backend_setting_when_set_to_groq(async_client, monkeypatch):
    """Companion to the demo-role test above: a role holding the full
    `use_assistant` permission (mechanic) is unaffected by the fix and
    still gets whatever `LLM_BACKEND` says."""
    monkeypatch.setattr(settings, "LLM_BACKEND", "groq")

    captured: dict[str, object] = {}

    class _StubCompiledGraph:
        async def astream(self, initial, stream_mode="updates"):
            yield {"knowledge": {"answer": "stub", "citations": [], "iterations": 1}}

    def _fake_build_supervisor_graph(llm_client, deps):
        captured["llm_client"] = llm_client
        return _StubCompiledGraph()

    monkeypatch.setattr(assistant_router, "build_supervisor_graph", _fake_build_supervisor_graph)

    headers = await _login(async_client, role="mechanic")
    response = await async_client.post("/assistant/stream", json={"question": "hi"}, headers=headers)

    assert response.status_code == 200
    assert isinstance(captured["llm_client"], GroqClient)


async def test_stream_off_script_question_emits_error_event_not_a_crash(async_client, monkeypatch):
    monkeypatch.setattr(assistant_router, "build_default_client", lambda: ReplayClient(cassette_dir=GOLDEN_DIR))

    headers = await _login(async_client, role="mechanic")
    response = await async_client.post(
        "/assistant/stream",
        json={"question": "This question was never recorded in any cassette"},
        headers=headers,
    )

    assert response.status_code == 200  # SSE headers already flushed; failure is an in-band `error` event
    events = _parse_sse(response.text)
    assert [e for e, _ in events] == ["error"]
    assert "No cassette recorded" in events[0][1]["message"]


async def test_stream_golden_knowledge_scenario_replays_deterministically(async_client, monkeypatch, db_session):
    """The same golden knowledge scenario test_replay_mode.py proves against
    `ask()` directly, now proven through the actual HTTP route this phase
    adds - the real supervisor graph, real hybrid retrieval/rerank against
    the real KB corpus, and the real ReplayClient cassette, all reachable
    only via the documented SSE event contract."""
    await ingest_kb_directory(db_session, KB_DIR)
    monkeypatch.setattr(assistant_router, "build_default_client", lambda: ReplayClient(cassette_dir=GOLDEN_DIR))

    headers = await _login(async_client, role="mechanic")
    response = await async_client.post(
        "/assistant/stream", json={"question": GOLDEN_KNOWLEDGE_QUESTION}, headers=headers
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    event_types = [e for e, _ in events]

    assert "trace" in event_types
    trace_nodes = [data["node"] for event, data in events if event == "trace"]
    assert "classify_intent" in trace_nodes
    assert "knowledge" in trace_nodes

    done_event = next(data for event, data in events if event == "done")
    assert done_event["route"] == "knowledge"
    assert "[1]" in done_event["answer"]

    sources_event = next(data for event, data in events if event == "sources")
    assert sources_event["citations"], "expected at least one grounded citation"
    top = sources_event["citations"][0]
    assert "BMW" in top["source"]
    assert top["section"] == "Coolant Service"

    reconstructed = "".join(data["text"] for event, data in events if event == "token")
    assert reconstructed == done_event["answer"]
