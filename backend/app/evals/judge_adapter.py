"""
The one adapter layer connecting Ragas/DeepEval's "bring your own judge LLM"
interfaces to this codebase's own `LLMClient` (`app.agents.llm_client`) -
never a second LLM-calling mechanism. Both eval libraries evolve their
judge-LLM interface between releases (this project pins `ragas==0.4.3`,
`deepeval==4.1.3` - see `backend/requirements.txt`), so this module exists to
be the single place that adapts *today's* installed interface to
`LLMClient`; a future upgrade only needs a change here.

Every adapter below sends exactly one user-role message through
`LLMClient.complete()` at the pinned `temperature=0.0, seed=0` -
`app.agents.llm_client`'s own `RECORD_MODE_TEMPERATURE`/`RECORD_MODE_SEED`
convention for reproducible cassette keys - so the same judge prompt always
hashes to the same cassette file, exactly like every other LLM call in this
app. Under `LLM_BACKEND=replay` (this environment, CI) that cassette is one
of the hand-authored fixtures in `backend/cassettes/evals/` (see
`backend/scripts/record_eval_cassettes.py` for how they were produced -
same "_ScriptedClient records as the real code runs once" convention Phase 7
established for `cassettes/golden/`). Under `LLM_BACKEND=groq` the exact same
adapter code drives a real judge call instead - no branching in this module,
the same `build_default_client()` factory used everywhere else in the app
decides which backend is live.
"""

from __future__ import annotations

import json
import os
import sys
import types
from typing import Any, Optional, Type, TypeVar

from pydantic import BaseModel

from app.agents.llm_client import LLMClient

# DeepEval phones home anonymous usage telemetry by default (a plain HTTP
# call, unrelated to judging - see `deepeval.telemetry`). Opted out here,
# at the first point anything in this codebase might import `deepeval`,
# so this suite never depends on outbound network access being available
# (matters for CI runners that block egress) and stays consistent with this
# project's "no live network call in tests" ethos even though this
# particular call was never an LLM request. `setdefault` so a human
# explicitly opting back in (env var already set) is respected.
os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")

T = TypeVar("T", bound=BaseModel)


def _shim_langchain_community_vertexai() -> None:
    """
    `ragas==0.4.3` unconditionally imports `ChatVertexAI` from
    `langchain_community.chat_models.vertexai` at module load time (purely
    to build an internal isinstance() allowlist for a provider this project
    never uses). `langchain-community>=0.4` - the version this project's own
    `requirements.txt` already pins for the RAG/agent stack, see
    `app.agents.llm_client`'s neighbours - dropped that submodule entirely
    (moved to the standalone `langchain-google-vertexai` package, never
    installed here), so a bare `import ragas` raises `ModuleNotFoundError`
    before this project's own adapter code ever runs. This is a confirmed,
    real version mismatch between two of ragas's own transitive
    dependencies as currently pinned on PyPI - not a design choice made
    here, and not fixable by changing anything in this project's own code
    (downgrading `langchain-community` to a version that still has the
    submodule pulls in a `langchain-core` too old for this project's pinned
    `langgraph`, see this phase's report for the exact conflict).

    Since this project never uses VertexAI as a judge backend, a harmless
    stub module is enough to satisfy ragas's own import statement. Guarded
    by a real import attempt first, so the moment a compatible pair of
    these two packages ships, this function becomes a silent no-op.
    """
    try:
        import langchain_community.chat_models.vertexai  # noqa: F401

        return
    except ModuleNotFoundError:
        pass

    stub = types.ModuleType("langchain_community.chat_models.vertexai")

    class ChatVertexAI:  # pragma: no cover - never instantiated, isinstance target only
        pass

    stub.ChatVertexAI = ChatVertexAI
    sys.modules["langchain_community.chat_models.vertexai"] = stub


_shim_langchain_community_vertexai()

from ragas.embeddings.base import BaseRagasEmbedding  # noqa: E402
from ragas.llms.base import InstructorBaseRagasLLM  # noqa: E402


class RagasReplayLLM(InstructorBaseRagasLLM):
    """Adapts `LLMClient` to ragas's current (`ragas.metrics.collections`,
    ragas>=0.4) judge interface: `generate(prompt, response_model)` /
    `agenerate(...)`, both expected to return a populated instance of
    `response_model` (ragas's own "instructor" structured-output pattern -
    see `ragas.llms.base.InstructorBaseRagasLLM`).

    `LLMClient` has no notion of structured output/instructor by design
    (see its own module docstring - it only ever returns `LLMResponse`).
    This adapter does the translation: the prompt ragas built (already a
    fully-formatted instruction+examples+input string, see
    `ragas.prompt.metrics.base_prompt.BasePrompt.to_string`) is sent as a
    single user message; the judge is expected to reply with the JSON
    encoding of `response_model` as `LLMResponse.content`, which this
    adapter parses back into that model.
    """

    def __init__(self, llm_client: LLMClient) -> None:
        self._client = llm_client

    def generate(self, prompt: str, response_model: Type[T]) -> T:
        response = self._client.complete(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            seed=0,
        )
        if not response.content:
            raise ValueError(
                f"Judge LLM returned no content for a ragas {response_model.__name__} prompt."
            )
        return response_model.model_validate(json.loads(response.content))

    async def agenerate(self, prompt: str, response_model: Type[T]) -> T:
        # LLMClient.complete() is itself synchronous (see its own ABC) -
        # nothing here actually awaits I/O, this just satisfies ragas's
        # async-first InstructorBaseRagasLLM interface.
        return self.generate(prompt, response_model)


class RagasLocalEmbedding(BaseRagasEmbedding):
    """Adapts this project's local, CPU-only sentence-transformers embedder
    (`app.agents.embeddings.embed_texts` - already used by the real RAG
    pipeline, see that module's own docstring) to ragas's `BaseRagasEmbedding`.

    Not judge-LLM traffic, so no cassette is involved: local model-weight
    inference is deterministic given a fixed model version, exactly like
    every other embedding call in this app - see `app.agents.embeddings`'s
    own docstring on why that category is exempt from the "no live network
    call" rule that governs `LLMClient`.
    """

    def embed_text(self, text: str, **kwargs: Any) -> list[float]:
        from app.agents.embeddings import embed_texts

        return embed_texts([text])[0]

    async def aembed_text(self, text: str, **kwargs: Any) -> list[float]:
        return self.embed_text(text, **kwargs)


def _build_deepeval_replay_llm_class():
    """Builds (and the caller below caches) the `DeepEvalBaseLLM` subclass
    adapting `LLMClient` to DeepEval's judge-LLM interface: `generate`/
    `a_generate`, each optionally given a pydantic `schema` to structure the
    reply as. `deepeval` is imported lazily, inside this function, rather
    than at module scope, so importing `app.evals.judge_adapter` never
    requires `deepeval` to be installed unless a caller actually builds one
    - consistent with `app.agents.llm_client`'s own "no provider SDK import
    outside this module" discipline, just applied to the optional
    eval-library dependency instead of a paid LLM provider."""
    from deepeval.models.base_model import DeepEvalBaseLLM

    class _DeepEvalReplayLLM(DeepEvalBaseLLM):
        def __init__(self, llm_client: LLMClient, model_name: str = "pitcrew-replay-judge") -> None:
            self._llm_client = llm_client
            super().__init__(model=model_name)

        def load_model(self):
            return self._llm_client

        def get_model_name(self, *args: Any, **kwargs: Any) -> str:
            return self.name

        def _complete(self, prompt: str, schema: Optional[Type[BaseModel]]) -> Any:
            response = self._llm_client.complete(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                seed=0,
            )
            content = response.content or ""
            if schema is not None:
                return schema.model_validate_json(content)
            return content

        def generate(self, prompt: str, schema: Optional[Type[BaseModel]] = None, **kwargs: Any) -> Any:
            return self._complete(prompt, schema)

        async def a_generate(self, prompt: str, schema: Optional[Type[BaseModel]] = None, **kwargs: Any) -> Any:
            return self._complete(prompt, schema)

    return _DeepEvalReplayLLM


# Built once, lazily, the first time a caller needs it - keeps `deepeval`
# an optional import at module scope, matching every other optional
# provider/eval dependency in this codebase.
_DeepEvalReplayLLMClass = None


def build_deepeval_judge(llm_client: LLMClient):
    """Factory: wrap `llm_client` as a `deepeval.models.base_model.DeepEvalBaseLLM`."""
    global _DeepEvalReplayLLMClass
    if _DeepEvalReplayLLMClass is None:
        _DeepEvalReplayLLMClass = _build_deepeval_replay_llm_class()
    return _DeepEvalReplayLLMClass(llm_client)
