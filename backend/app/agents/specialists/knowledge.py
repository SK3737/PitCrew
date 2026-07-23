"""
Knowledge specialist - answers general questions by calling `search_kb`,
which (as of Phase 6) runs real hybrid retrieval + rerank against the
embedded synthetic corpus (see `app.rag.*`, `app.agents.tools.search_kb`).

Citation composition: `search_kb` returns `KBHit`s in reranked (most
relevant first) order. `run_knowledge` collects every hit returned across
the run, deduped by `chunk_id` and in first-seen order, into
`KnowledgeAnswer.citations` - that list's index (1-based) is exactly the
`[n]` numbering the system prompt asks the model to cite inline with, so
citation `n` always resolves to `citations[n-1]`. When `search_kb` returns
no hits at all - either because retrieval found nothing, or because
everything it found scored below the refusal threshold (see
`app.rag.rerank.REFUSAL_SCORE_THRESHOLD`) - the prompt requires an explicit
refusal instead of a guess.
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
    "question. If it returns no results, that means there is no supporting "
    "documentation for this question - say so plainly instead of guessing "
    "or fabricating an answer. If it returns hits, answer using ONLY what "
    "they say, and cite every fact you use with an inline [n] marker "
    "matching that hit's position in the results (the first hit is [1], "
    "the second is [2], and so on)."
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

    seen_chunk_ids: set[int] = set()
    citations: list[KBHit] = []
    for returned in collect_tool_returns(result.all_messages(), "search_kb"):
        # search_kb returns a list[KBHit]; ToolReturnPart wraps non-dict
        # values under RETURN_VALUE_KEY ("return_value") when dumping.
        hits = returned.get("return_value", returned if isinstance(returned, list) else [])
        for hit in hits or []:
            kb_hit = KBHit(**hit)
            # Dedup by chunk_id (not just object identity) - the same
            # chunk could come back from more than one search_kb call
            # within a single run, and citations[i] must map 1:1 to the
            # [n] markers the system prompt asks the model to use.
            if kb_hit.chunk_id in seen_chunk_ids:
                continue
            seen_chunk_ids.add(kb_hit.chunk_id)
            citations.append(kb_hit)

    return KnowledgeAnswer(answer=result.output, citations=citations)
