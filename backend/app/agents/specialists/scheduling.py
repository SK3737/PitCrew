"""
Scheduling specialist - books a service appointment via `schedule_service`.

Guardrail ownership: the actual "never write without confirmation" rule
lives in the tool itself (app.agents.tools.schedule_service checks
`confirmed` before touching the Scheduler port) so it holds even if a
model ignores the system prompt's instructions below. The prompt exists to
make the *first* turn of a real conversation ask for confirmation rather
than assuming it - see app.agents.guardrails for the enforcement layer this
specialist is wired through.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel
from pydantic_ai import Agent

from app.agents.llm_client import LLMClient
from app.agents.model_adapter import llm_client_model
from app.agents.specialists._common import collect_tool_returns
from app.agents.tools import AgentDeps, ScheduleServiceResult, schedule_service

SYSTEM_PROMPT = (
    "You are PitCrew's scheduling specialist. The user wants to book a "
    "service appointment. Call schedule_service with the vehicle_id and "
    "date they mentioned. Only pass confirmed=true if the user has "
    "explicitly confirmed the booking in this conversation; otherwise pass "
    "confirmed=false and relay the confirmation prompt schedule_service "
    "returns instead of claiming the booking is made."
)


class SchedulingAnswer(BaseModel):
    """Typed output of the Scheduling specialist."""

    answer: str
    booking: Optional[ScheduleServiceResult] = None


def build_scheduling_agent(llm_client: LLMClient, *, seed: Optional[int] = 0) -> Agent[AgentDeps, str]:
    model = llm_client_model(llm_client, model_name="scheduling", seed=seed)
    return Agent(
        model,
        deps_type=AgentDeps,
        output_type=str,
        system_prompt=SYSTEM_PROMPT,
        tools=[schedule_service],
        name="scheduling",
    )


async def run_scheduling(llm_client: LLMClient, deps: AgentDeps, question: str) -> SchedulingAnswer:
    agent = build_scheduling_agent(llm_client)
    result = await agent.run(question, deps=deps)

    booking: Optional[ScheduleServiceResult] = None
    for returned in collect_tool_returns(result.all_messages(), "schedule_service"):
        booking = ScheduleServiceResult(**returned)

    return SchedulingAnswer(answer=result.output, booking=booking)
