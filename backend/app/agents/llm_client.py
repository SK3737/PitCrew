"""
LLMClient: the single abstraction every chat/reasoning call in this codebase
must go through. No provider SDK (``groq``, or any future addition) is ever
imported outside this module.

Two implementations exist:

- ``ReplayClient`` - deterministic, offline, cassette-backed. This is the
  default backend (``LLM_BACKEND=replay``, see ``app.config.settings``) and
  the *only* backend exercised by this repo's test suite. It never opens a
  socket: an unknown request raises ``CassetteMiss`` instead of falling
  back to a live call.
- ``GroqClient`` - thin wrapper around the ``groq`` SDK's chat completions
  API. Only reachable when ``LLM_BACKEND=groq`` and ``GROQ_API_KEY`` is set
  (dev/hosted demo use, using Groq's free tier). Never invoked from tests.

Cassette convention
--------------------
``CASSETTE_DIR`` (``app.config.settings.CASSETTE_DIR``) points at a
directory holding one JSON file per recorded request, named
``<sha256-hash>.json``. If ``CASSETTE_DIR`` is blank (the Phase 1 default),
``ReplayClient`` falls back to ``backend/cassettes/`` - a fixed, repo-local
path so cassettes committed for tests are found the same way in every
environment (dev machine, CI). Phase 7 (replay mode for CI) builds directly
on this convention.

The hash is computed over a canonical JSON encoding of every input that
would change what a real LLM provider was asked: ``model``, ``messages``,
``tools``, ``temperature``, ``seed``. Same request in -> same filename ->
same recorded response, forever. A cassette file holds both the request
(for human debugging / diffing) and the response:

    {
      "request":  {"model": ..., "messages": [...], "tools": [...],
                    "temperature": 0.0, "seed": 0},
      "response": {"content": "..." | null,
                    "tool_calls": [{"id": "...", "name": "...", "arguments": {...}}]}
    }
"""

from __future__ import annotations

import hashlib
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from app.config import settings

logger = logging.getLogger(__name__)

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CASSETTE_DIR = _BACKEND_ROOT / "cassettes"


class CassetteMiss(Exception):
    """Raised by ReplayClient when no recorded cassette matches the request hash.

    Never raised by GroqClient - a cassette miss is purely a replay-mode
    concept (it means "record this interaction," not "the provider failed").
    """


class RateLimited(Exception):
    """Raised by GroqClient when the provider returns HTTP 429.

    Deliberately NOT retried automatically - callers (the supervisor graph's
    guardrails, see app.agents.guardrails) decide how to degrade instead of
    this client silently hammering a rate-limited endpoint.
    """


@dataclass(frozen=True)
class ToolCall:
    """A single tool invocation requested by the model."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class LLMResponse:
    """Normalized response shape returned by every LLMClient implementation."""

    content: Optional[str] = None
    tool_calls: list[ToolCall] = field(default_factory=list)


class LLMClient(ABC):
    """Every chat/reasoning call in this codebase goes through this interface."""

    @abstractmethod
    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        *,
        temperature: float = 0.0,
        seed: Optional[int] = None,
        **params: Any,
    ) -> LLMResponse:
        """Send ``messages`` (OpenAI-style role/content dicts) plus an optional
        ``tools`` schema and return a normalized ``LLMResponse``."""
        raise NotImplementedError


def request_hash(
    model: str,
    messages: list[dict[str, Any]],
    tools: Optional[list[dict[str, Any]]],
    temperature: float,
    seed: Optional[int],
) -> str:
    """Canonical hash identifying an LLM request - the ReplayClient cassette key.

    Exposed (not private) so tests and the cassette-recording helper below
    can compute the same key the client will look up at read time.
    """
    payload = {
        "model": model,
        "messages": messages,
        "tools": tools or [],
        "temperature": temperature,
        "seed": seed,
    }
    encoded = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ReplayClient(LLMClient):
    """Deterministic, offline LLMClient backed by a directory of JSON cassettes."""

    def __init__(self, cassette_dir: Optional[Path | str] = None, model: str = "replay") -> None:
        self._dir = Path(cassette_dir) if cassette_dir else Path(settings.CASSETTE_DIR or DEFAULT_CASSETTE_DIR)
        self._model = model

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        *,
        temperature: float = 0.0,
        seed: Optional[int] = None,
        **params: Any,
    ) -> LLMResponse:
        h = request_hash(self._model, messages, tools, temperature, seed)
        path = self._dir / f"{h}.json"
        if not path.exists():
            raise CassetteMiss(
                f"No cassette recorded for request hash {h} (looked in {self._dir}). "
                "Record one with app.agents.llm_client.record_cassette(...) - "
                "ReplayClient never falls back to a live call."
            )
        data = json.loads(path.read_text(encoding="utf-8"))
        resp = data["response"]
        tool_calls = [ToolCall(**tc) for tc in resp.get("tool_calls", [])]
        return LLMResponse(content=resp.get("content"), tool_calls=tool_calls)


def record_cassette(
    cassette_dir: Path | str,
    model: str,
    messages: list[dict[str, Any]],
    tools: Optional[list[dict[str, Any]]],
    response: LLMResponse,
    *,
    temperature: float = 0.0,
    seed: Optional[int] = None,
) -> Path:
    """Authoring helper: write a cassette file for a given request+response pair.

    Used by tests (and, in Phase 7, a record-mode script) to build fixtures
    without hand-computing hashes.
    """
    directory = Path(cassette_dir)
    directory.mkdir(parents=True, exist_ok=True)
    h = request_hash(model, messages, tools, temperature, seed)
    path = directory / f"{h}.json"
    payload = {
        "request": {
            "model": model,
            "messages": messages,
            "tools": tools or [],
            "temperature": temperature,
            "seed": seed,
        },
        "response": {
            "content": response.content,
            "tool_calls": [
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in response.tool_calls
            ],
        },
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


#: Every call site in this codebase already pins these two values
#: (``classify_intent_text``, ``llm_client_model``'s defaults) - record mode
#: enforces the same convention so a recording pass is reproducible: the
#: same prompt always yields the same cassette key, forever, regardless of
#: what a careless caller happened to pass in.
RECORD_MODE_TEMPERATURE = 0.0
RECORD_MODE_SEED = 0


class GroqClient(LLMClient):
    """Live backend - calls Groq's chat completions API via the ``groq`` SDK.

    Never invoked in this repo's tests or CI; only reachable in a real
    deployment with ``LLM_BACKEND=groq`` and a ``GROQ_API_KEY`` set. Groq's
    free tier is the only live LLM path in this project (see project-wide
    constraint: no paid LLM API is ever called anywhere in this codebase).

    Record mode
    -----------
    Pass ``record_dir`` to turn this into a *recorder*: every live call is
    still made for real, but its request+response is also written to a
    cassette under ``record_dir`` via ``record_cassette`` - using the exact
    same ``request_hash`` key ``ReplayClient`` looks up at replay time, so a
    cassette recorded this way is immediately replayable offline with no
    translation step. Record mode always pins ``temperature``/``seed`` to
    ``RECORD_MODE_TEMPERATURE``/``RECORD_MODE_SEED`` (overriding whatever the
    caller passed) so re-running a recording session reproduces the same
    cassette keys/content rather than drifting. This is the mechanism
    ``scripts/record_cassettes.py`` drives against a real Groq API key to
    populate/refresh the committed cassettes in ``backend/cassettes/``.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        client: Any = None,
        record_dir: Optional[Path | str] = None,
    ) -> None:
        self._model = model or settings.GROQ_MODEL
        self._record_dir = Path(record_dir) if record_dir else None
        if client is not None:
            self._client = client
        else:
            import groq  # local import: keep `groq` optional for pure-replay environments

            self._client = groq.Groq(api_key=api_key or settings.GROQ_API_KEY)

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        *,
        temperature: float = 0.0,
        seed: Optional[int] = None,
        **params: Any,
    ) -> LLMResponse:
        import groq

        if self._record_dir is not None:
            temperature, seed = RECORD_MODE_TEMPERATURE, RECORD_MODE_SEED

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools
        if seed is not None:
            kwargs["seed"] = seed
        kwargs.update(params)

        try:
            completion = self._client.chat.completions.create(**kwargs)
        except groq.RateLimitError as exc:
            raise RateLimited(
                "Groq API rate limit (HTTP 429) - not retried automatically; "
                "the caller decides how to degrade (see app.agents.guardrails)."
            ) from exc

        message = completion.choices[0].message
        tool_calls = [
            ToolCall(id=tc.id, name=tc.function.name, arguments=json.loads(tc.function.arguments or "{}"))
            for tc in (message.tool_calls or [])
        ]
        response = LLMResponse(content=message.content, tool_calls=tool_calls)

        if self._record_dir is not None:
            record_cassette(
                self._record_dir,
                self._model,
                messages,
                tools,
                response,
                temperature=temperature,
                seed=seed,
            )

        return response


def build_default_client() -> LLMClient:
    """Factory: pick the LLMClient implementation from ``settings.LLM_BACKEND``.

    This is the only place in the app that branches on ``LLM_BACKEND`` -
    every specialist/supervisor consumer takes an already-constructed
    ``LLMClient`` and never checks the backend itself.
    """
    if settings.LLM_BACKEND == "groq":
        return GroqClient()
    return ReplayClient()
