"""
Bridges our ``LLMClient`` abstraction to PydanticAI's ``Model`` protocol.

PydanticAI ships ``pydantic_ai.models.function.FunctionModel`` precisely for
this: a model backed by an arbitrary Python callable instead of a provider
SDK. Every specialist agent in ``app.agents.specialists`` is constructed
with one of these (via ``llm_client_model`` below), never with a "real"
PydanticAI provider model - so the exact same agent code runs unchanged
whether the injected ``LLMClient`` is a ``ReplayClient`` (tests, CI) or a
``GroqClient`` (dev/hosted demo); only ``app.agents.llm_client.build_default_client``
differs based on ``settings.LLM_BACKEND``.

The adapter is intentionally "dumb": it flattens PydanticAI's structured
message history into the same OpenAI-style plain-dict messages every
``LLMClient.complete()`` implementation already speaks, forwards the
agent's tool definitions as a tools schema, and converts the response back.
No PydanticAI-specific behaviour (retries, streaming, structured "final
result" tool-calling) is implemented here - specialists use ``output_type=str``
for exactly this reason (see ``app.agents.specialists`` docstrings).
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.tools import ToolDefinition

from app.agents.llm_client import LLMClient


def _tool_schema(tool_def: ToolDefinition) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool_def.name,
            "description": tool_def.description or "",
            "parameters": tool_def.parameters_json_schema,
        },
    }


def to_plain_messages(messages: list[ModelMessage]) -> list[dict[str, Any]]:
    """Flatten PydanticAI's structured message history into OpenAI-style
    role/content dicts - the wire format every ``LLMClient.complete()``
    implementation speaks, and the same shape ``request_hash`` hashes over.
    """
    plain: list[dict[str, Any]] = []
    for message in messages:
        if isinstance(message, ModelRequest):
            for part in message.parts:
                if isinstance(part, SystemPromptPart):
                    plain.append({"role": "system", "content": part.content})
                elif isinstance(part, UserPromptPart):
                    plain.append({"role": "user", "content": part.content})
                elif isinstance(part, ToolReturnPart):
                    plain.append(
                        {
                            "role": "tool",
                            "tool_call_id": part.tool_call_id,
                            "content": part.model_response_str(),
                        }
                    )
                elif isinstance(part, RetryPromptPart):
                    plain.append(
                        {
                            "role": "tool",
                            "tool_call_id": part.tool_call_id,
                            "content": part.model_response(),
                        }
                    )
        elif isinstance(message, ModelResponse):
            tool_calls = [
                {"id": p.tool_call_id, "name": p.tool_name, "arguments": p.args_as_dict()}
                for p in message.parts
                if isinstance(p, ToolCallPart)
            ]
            text = "".join(p.content for p in message.parts if isinstance(p, TextPart))
            entry: dict[str, Any] = {"role": "assistant", "content": text or None}
            if tool_calls:
                entry["tool_calls"] = tool_calls
            plain.append(entry)
    return plain


def llm_client_model(
    llm_client: LLMClient,
    *,
    model_name: str,
    temperature: float = 0.0,
    seed: Optional[int] = 0,
) -> FunctionModel:
    """Wrap ``llm_client`` as a PydanticAI ``Model`` any ``Agent(...)`` can use.

    ``model_name`` becomes part of the ReplayClient cassette hash (see
    ``app.agents.llm_client.request_hash``) - use a stable, specialist-specific
    name (e.g. ``"diagnostics"``) so cassettes for different specialists never
    collide even if their prompts happen to coincide.
    """

    async def _call(messages: list[ModelMessage], agent_info: AgentInfo) -> ModelResponse:
        plain_messages = to_plain_messages(messages)
        tool_defs = list(agent_info.function_tools) + list(agent_info.output_tools)
        tools = [_tool_schema(t) for t in tool_defs] or None

        response = llm_client.complete(
            plain_messages,
            tools=tools,
            temperature=temperature,
            seed=seed,
        )

        if response.tool_calls:
            parts: list[Any] = [
                ToolCallPart(tool_name=tc.name, args=tc.arguments, tool_call_id=tc.id)
                for tc in response.tool_calls
            ]
            return ModelResponse(parts=parts)
        return ModelResponse(parts=[TextPart(content=response.content or "")])

    return FunctionModel(_call, model_name=model_name)
