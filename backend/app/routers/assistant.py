"""POST /assistant/ask - runs the LangGraph supervisor and returns the
answer plus its trajectory. Guarded by `use_assistant`/`use_assistant_replay`
(mechanic and demo roles - see app.auth.rbac.ROLE_PERMISSIONS)."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.llm_client import build_default_client
from app.agents.supervisor import ask
from app.agents.tools import AgentDeps, RepositoryVehicleDataProvider
from app.auth.rbac import require_permission
from app.db.session import get_session
from app.models.user import User

router = APIRouter(prefix="/assistant", tags=["assistant"])


class AssistantAskRequest(BaseModel):
    question: str


class AssistantAskResponse(BaseModel):
    run_id: str
    route: Optional[str] = None
    answer: str
    tool_results: dict[str, Any] = {}
    citations: list[dict[str, Any]] = []


@router.post("/ask", response_model=AssistantAskResponse)
async def ask_assistant(
    payload: AssistantAskRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_permission("use_assistant", "use_assistant_replay")),
) -> AssistantAskResponse:
    llm_client = build_default_client()
    deps = AgentDeps(vehicle_data=RepositoryVehicleDataProvider(session))

    final_state = await ask(llm_client, deps, payload.question)

    return AssistantAskResponse(
        run_id=final_state.get("run_id", ""),
        route=final_state.get("route"),
        answer=final_state.get("answer", ""),
        tool_results=final_state.get("tool_results") or {},
        citations=final_state.get("citations") or [],
    )
