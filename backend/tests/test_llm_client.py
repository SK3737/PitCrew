"""
LLMClient interface tests.

Hard constraint (project-wide, not just this file): no live/paid LLM API
call is ever made anywhere in this test suite. `GroqClient` is tested by
mocking the `groq` SDK client it wraps - the mock never touches a socket.
`ReplayClient` never touches a socket by construction (a cassette miss
raises, it never falls back to a live call).
"""

from __future__ import annotations

import httpx
import pytest

from app.agents.llm_client import (
    CassetteMiss,
    GroqClient,
    LLMResponse,
    RateLimited,
    ReplayClient,
    ToolCall,
    build_default_client,
    record_cassette,
    request_hash,
)
from app.config import settings

MESSAGES = [{"role": "user", "content": "When does V001 need service?"}]


def test_replay_client_returns_recorded_response_for_known_hash(tmp_path):
    response = LLMResponse(content="diagnostics")
    record_cassette(tmp_path, "replay", MESSAGES, None, response, temperature=0.0, seed=0)

    client = ReplayClient(cassette_dir=tmp_path)
    result = client.complete(MESSAGES, temperature=0.0, seed=0)

    assert result.content == "diagnostics"
    assert result.tool_calls == []


def test_replay_client_raises_cassette_miss_for_unknown_request(tmp_path):
    client = ReplayClient(cassette_dir=tmp_path)

    with pytest.raises(CassetteMiss):
        client.complete(MESSAGES, temperature=0.0, seed=0)


def test_replay_client_defaults_to_backend_cassette_dir_when_unset(monkeypatch):
    """CASSETTE_DIR is '' by default (Phase 1) - ReplayClient must fall back
    to backend/cassettes/, not crash or silently use the CWD."""
    monkeypatch.setattr(settings, "CASSETTE_DIR", "")
    client = ReplayClient()
    assert client._dir.name == "cassettes"
    assert client._dir.parent.name == "backend"


def test_request_hash_is_stable_and_content_sensitive():
    h1 = request_hash("replay", MESSAGES, None, 0.0, 0)
    h2 = request_hash("replay", MESSAGES, None, 0.0, 0)
    h3 = request_hash("replay", MESSAGES, None, 0.7, 0)

    assert h1 == h2
    assert h1 != h3


def test_groq_client_maps_rate_limit_error_to_typed_exception():
    """The `groq` SDK is mocked - `.create()` never makes an HTTP call."""

    class _FakeCompletions:
        def create(self, **kwargs):
            request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
            response = httpx.Response(429, request=request)
            import groq

            raise groq.RateLimitError("rate limited", response=response, body=None)

    class _FakeChat:
        completions = _FakeCompletions()

    class _FakeGroqSDKClient:
        chat = _FakeChat()

    client = GroqClient(client=_FakeGroqSDKClient())

    with pytest.raises(RateLimited):
        client.complete(MESSAGES)


def test_groq_client_builds_request_and_parses_tool_calls():
    """Verifies request shape + tool-call parsing against a mocked SDK
    response object - never a live call."""

    captured_kwargs = {}

    class _ToolCallFunction:
        name = "predict_service"
        arguments = '{"vehicle_id": "V001"}'

    class _ToolCall:
        id = "call_1"
        function = _ToolCallFunction()

    class _Message:
        content = None
        tool_calls = [_ToolCall()]

    class _Choice:
        message = _Message()

    class _Completion:
        choices = [_Choice()]

    class _FakeCompletions:
        def create(self, **kwargs):
            captured_kwargs.update(kwargs)
            return _Completion()

    class _FakeChat:
        completions = _FakeCompletions()

    class _FakeGroqSDKClient:
        chat = _FakeChat()

    client = GroqClient(model="llama-3.3-70b-versatile", client=_FakeGroqSDKClient())
    result = client.complete(MESSAGES, tools=[{"type": "function", "function": {"name": "predict_service"}}], temperature=0.2, seed=7)

    assert captured_kwargs["model"] == "llama-3.3-70b-versatile"
    assert captured_kwargs["messages"] == MESSAGES
    assert captured_kwargs["temperature"] == 0.2
    assert captured_kwargs["seed"] == 7
    assert captured_kwargs["tools"][0]["function"]["name"] == "predict_service"

    assert result.content is None
    assert result.tool_calls == [ToolCall(id="call_1", name="predict_service", arguments={"vehicle_id": "V001"})]


def test_build_default_client_selects_backend_from_settings(monkeypatch):
    monkeypatch.setattr(settings, "LLM_BACKEND", "replay")
    assert isinstance(build_default_client(), ReplayClient)

    monkeypatch.setattr(settings, "LLM_BACKEND", "groq")
    monkeypatch.setattr(settings, "GROQ_API_KEY", "test-key-never-used-live")
    assert isinstance(build_default_client(), GroqClient)
