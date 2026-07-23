"""
Diagnostics specialist - answers "when/why does my vehicle need service"
questions by calling `predict_service` (Phase 3's registry, thinly wrapped).
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel
from pydantic_ai import Agent

from app.agents.llm_client import LLMClient
from app.agents.model_adapter import llm_client_model
from app.agents.specialists._common import collect_tool_returns
from app.agents.tools import AgentDeps, PredictServiceResult, predict_service

SYSTEM_PROMPT = (
    "You are PitCrew's diagnostics specialist. The user is asking about a "
    "vehicle's service needs. Call predict_service with the vehicle_id "
    "mentioned in the question, then answer in one or two plain-language "
    "sentences citing the predicted days and kilometres until service, and "
    "which threshold (time or km) will be hit first. If predict_service "
    "reports no history for the vehicle, say so plainly instead of guessing."
)


class DiagnosticsAnswer(BaseModel):
    """Typed output of the Diagnostics specialist."""

    answer: str
    prediction: Optional[PredictServiceResult] = None


def build_diagnostics_agent(llm_client: LLMClient, *, seed: Optional[int] = 0) -> Agent[AgentDeps, str]:
    model = llm_client_model(llm_client, model_name="diagnostics", seed=seed)
    return Agent(
        model,
        deps_type=AgentDeps,
        output_type=str,
        system_prompt=SYSTEM_PROMPT,
        tools=[predict_service],
        name="diagnostics",
    )


async def run_diagnostics(llm_client: LLMClient, deps: AgentDeps, question: str) -> DiagnosticsAnswer:
    agent = build_diagnostics_agent(llm_client)
    result = await agent.run(question, deps=deps)

    prediction: Optional[PredictServiceResult] = None
    for returned in collect_tool_returns(result.all_messages(), "predict_service"):
        if "predicted_days_until_service" in returned:
            prediction = PredictServiceResult(**returned)

    return DiagnosticsAnswer(answer=result.output, prediction=prediction)
