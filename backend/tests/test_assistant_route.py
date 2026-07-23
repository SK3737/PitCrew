"""
POST /assistant/ask - router-level tests (RBAC + response shaping).

The supervisor graph's own behaviour (routing, tool calls, guardrails) is
already covered by test_supervisor_routing.py and test_guardrails.py
against ReplayClient; this file only checks the route's wiring: does it
enforce `use_assistant`/`use_assistant_replay`, and does it shape the
graph's final state into the documented response schema. `app.agents.supervisor.ask`
is monkeypatched to a stub so no LLM call (real or replayed) happens here.
"""

from __future__ import annotations

import uuid

import app.routers.assistant as assistant_router
from app.agents.llm_client import GroqClient, ReplayClient
from app.config import settings
from tests.conftest import create_user_directly

PASSWORD = "correct horse battery staple"


async def _login(async_client, role: str) -> dict:
    email = f"{role}-{uuid.uuid4()}@example.com"
    await create_user_directly(email, PASSWORD, role=role)
    r = await async_client.post("/auth/login", json={"email": email, "password": PASSWORD})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def test_ask_requires_use_assistant_permission(async_client):
    headers = await _login(async_client, role="owner")  # owner has neither use_assistant permission

    response = await async_client.post("/assistant/ask", json={"question": "hi"}, headers=headers)

    assert response.status_code == 403


async def test_mechanic_can_ask_and_gets_shaped_response(async_client, monkeypatch):
    async def _fake_ask(llm_client, deps, question, run_id=None):
        return {
            "question": question,
            "route": "diagnostics",
            "answer": "V001 needs service in 38 days.",
            "tool_results": {"predict_service": {"vehicle_id": "V001"}},
            "citations": [],
            "run_id": "fixed-run-id",
            "iterations": 2,
        }

    monkeypatch.setattr(assistant_router, "ask", _fake_ask)

    headers = await _login(async_client, role="mechanic")
    response = await async_client.post(
        "/assistant/ask", json={"question": "When does V001 need service?"}, headers=headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == "fixed-run-id"
    assert body["route"] == "diagnostics"
    assert body["answer"] == "V001 needs service in 38 days."
    assert body["tool_results"] == {"predict_service": {"vehicle_id": "V001"}}
    assert body["citations"] == []


async def test_demo_role_can_ask_via_replay_permission(async_client, monkeypatch):
    async def _fake_ask(llm_client, deps, question, run_id=None):
        return {"route": "knowledge", "answer": "stub", "run_id": "r", "tool_results": {}, "citations": []}

    monkeypatch.setattr(assistant_router, "ask", _fake_ask)

    headers = await _login(async_client, role="demo")
    response = await async_client.post("/assistant/ask", json={"question": "hi"}, headers=headers)

    assert response.status_code == 200


async def test_demo_role_is_forced_onto_replay_client_even_when_backend_is_groq(
    async_client, monkeypatch
):
    """Finding-1 regression test: `use_assistant_replay` (demo) must always
    be served via `ReplayClient`, regardless of the ambient `LLM_BACKEND`
    setting - see `assistant_router._llm_client_for_role`. Before the fix,
    both routes unconditionally called `build_default_client()`, which
    would have handed a `demo` caller a live `GroqClient` here."""
    monkeypatch.setattr(settings, "LLM_BACKEND", "groq")

    captured: dict[str, object] = {}

    async def _fake_ask(llm_client, deps, question, run_id=None):
        captured["llm_client"] = llm_client
        return {"route": "knowledge", "answer": "stub", "run_id": "r", "tool_results": {}, "citations": []}

    monkeypatch.setattr(assistant_router, "ask", _fake_ask)

    headers = await _login(async_client, role="demo")
    response = await async_client.post("/assistant/ask", json={"question": "hi"}, headers=headers)

    assert response.status_code == 200
    assert isinstance(captured["llm_client"], ReplayClient)


async def test_mechanic_role_honors_llm_backend_setting_when_set_to_groq(async_client, monkeypatch):
    """Companion to the demo-role test above: a role holding the full
    `use_assistant` permission (mechanic) is unaffected by the fix and
    still gets whatever `LLM_BACKEND` says."""
    monkeypatch.setattr(settings, "LLM_BACKEND", "groq")

    captured: dict[str, object] = {}

    async def _fake_ask(llm_client, deps, question, run_id=None):
        captured["llm_client"] = llm_client
        return {"route": "knowledge", "answer": "stub", "run_id": "r", "tool_results": {}, "citations": []}

    monkeypatch.setattr(assistant_router, "ask", _fake_ask)

    headers = await _login(async_client, role="mechanic")
    response = await async_client.post("/assistant/ask", json={"question": "hi"}, headers=headers)

    assert response.status_code == 200
    assert isinstance(captured["llm_client"], GroqClient)
