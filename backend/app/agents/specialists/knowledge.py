"""
Knowledge specialist - answers general questions by calling `search_kb`.

`search_kb` is a stub in Phase 5 (always returns []) - Phase 6 (RAG) fills
in real retrieval against an embedded corpus. Until then this specialist
truthfully reports it has no knowledge base to search rather than
hallucinating an answer.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel
from pydantic_ai import Agent

from app.agents.llm_client import LLMClient
from app.agents.model_adapter import llm_client_model
from app.agents.specialists._common import collect_tool_returns
from app.agents.tools import AgentDeps, KBHit, search_kb

SYSTEM_PROMPT = (
    "You are PitCrew's knowledge specialist. Call search_kb with the user's "
    "question. If it returns no results (the knowledge base is not built "
    "yet), say plainly that you don't have documentation to answer this yet "
    "instead of guessing. If it returns hits, answer using them and cite "
    "each hit's source."
)


class KnowledgeAnswer(BaseModel):
    """Typed output of the Knowledge specialist."""

    answer: str
    citations: list[KBHit] = []


def build_knowledge_agent(llm_client: LLMClient, *, seed: Optional[int] = 0) -> Agent[AgentDeps, str]:
    model = llm_client_model(llm_client, model_name="knowledge", seed=seed)
    return Agent(
        model,
        deps_type=AgentDeps,
        output_type=str,
        system_prompt=SYSTEM_PROMPT,
        tools=[search_kb],
        name="knowledge",
    )


async def run_knowledge(llm_client: LLMClient, deps: AgentDeps, question: str) -> KnowledgeAnswer:
    agent = build_knowledge_agent(llm_client)
    result = await agent.run(question, deps=deps)

    citations: list[KBHit] = []
    for returned in collect_tool_returns(result.all_messages(), "search_kb"):
        # search_kb returns a list[KBHit]; ToolReturnPart wraps non-dict
        # values under RETURN_VALUE_KEY ("return_value") when dumping.
        hits = returned.get("return_value", returned if isinstance(returned, list) else [])
        for hit in hits or []:
            citations.append(KBHit(**hit))

    return KnowledgeAnswer(answer=result.output, citations=citations)
