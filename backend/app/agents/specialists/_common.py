"""Shared helpers for the three specialist agents."""

from __future__ import annotations

from typing import Any

from pydantic_ai.messages import ModelMessage, ModelRequest, ToolReturnPart


def collect_tool_returns(messages: list[ModelMessage], tool_name: str) -> list[dict[str, Any]]:
    """Pull every recorded return value of `tool_name` out of a finished
    Agent.run()'s message history, as plain dicts.

    Used by the specialist wrapper functions to populate their typed output
    models (e.g. DiagnosticsAnswer.prediction) from what the tool actually
    returned during the run, since specialists use `output_type=str` (see
    app.agents.model_adapter for why) rather than PydanticAI's structured
    output tool-calling.
    """
    returns: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, ModelRequest):
            continue
        for part in message.parts:
            if isinstance(part, ToolReturnPart) and part.tool_name == tool_name:
                returns.append(part.model_response_object())
    return returns
