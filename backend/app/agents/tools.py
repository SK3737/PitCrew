"""
Typed tools the specialist agents (app.agents.specialists) can call.

Each tool is a plain async function taking a PydanticAI ``RunContext[AgentDeps]``
plus typed arguments, and returning a typed pydantic model - PydanticAI infers
the tool's JSON schema straight from these signatures. Nothing here talks to
an LLM provider; tools are ordinary application code the model is allowed to
invoke.

``AgentDeps`` carries everything a tool needs that must NOT come from the
model (the DB session, effectively) behind two small ports so tests can
supply an in-memory fake instead of a real Postgres-backed repository:

- ``VehicleDataProvider`` - resolves a vehicle_id to the fields
  ``predict_service`` needs (months/kms driven since last service, plus the
  optional v2 fields). ``RepositoryVehicleDataProvider`` is the production
  implementation, built from the same two repositories
  ``routers/vehicles.py`` already uses (``VehicleRepository``,
  ``ServiceHistoryRepository``).
- ``Scheduler`` - persists a confirmed service booking. No appointments
  table exists yet in this schema (out of scope for this phase - see the
  Phase 5 report); ``InMemoryScheduler`` is a documented stub a future phase
  can replace with a real repository without touching the tool's signature.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Annotated, Literal, Optional, Protocol

from pydantic import BaseModel, Field
from pydantic_ai import RunContext

from app.services.predictor import predict


class VehicleServiceSnapshot(BaseModel):
    """Everything predict_service needs about a vehicle's service history."""

    vehicle_id: str
    months_driven: float
    kms_driven: float
    make: Optional[str] = None
    vehicle_model: Optional[str] = None
    year: Optional[int] = None
    fuel_type: Optional[str] = None
    last_service_type: Optional[str] = None


class VehicleDataProvider(Protocol):
    async def get_snapshot(self, vehicle_id: str) -> Optional[VehicleServiceSnapshot]: ...


class RepositoryVehicleDataProvider:
    """Production VehicleDataProvider - reads from Postgres via the same
    repositories routers/vehicles.py uses, computing months/kms driven the
    same way `predict_for_vehicle` does (relative to today)."""

    def __init__(self, session) -> None:
        # Imported lazily to avoid a hard dependency on SQLAlchemy for
        # callers (e.g. tests) that only ever construct a FakeVehicleDataProvider.
        from app.repositories.service_history import (
            ServiceHistoryRepository,
            compute_empirical_km_per_month,
        )
        from app.repositories.vehicles import VehicleRepository

        self._compute_empirical_km_per_month = compute_empirical_km_per_month

        self._history_repo = ServiceHistoryRepository(session)
        self._vehicle_repo = VehicleRepository(session)

    async def get_snapshot(self, vehicle_id: str) -> Optional[VehicleServiceSnapshot]:
        last = await self._history_repo.get_last_for_vehicle(vehicle_id)
        if last is None:
            return None

        vehicle = await self._vehicle_repo.get(vehicle_id)
        months_driven = max((date.today() - last.serviced_at).days / 30.44, 0.0)

        # The assistant's predict_service(vehicle_id) tool has no live
        # odometer input the way POST /vehicles/{id}/predict does (that
        # endpoint takes current_odometer_km directly from the caller), so
        # there is no genuine "kms since last service" reading available
        # here. Rather than feed a fabricated 0.0 into the real ML tiers as
        # if it were an actual measurement, estimate it from the vehicle's
        # own service-history cadence: km/month derived from the deltas
        # between past service events (the same empirical estimate already
        # surfaced on GET /vehicles/{id}/history), projected across the
        # months elapsed since the last service. This is a genuine
        # data-derived estimate, not a live reading - if there's not enough
        # history to derive one (fewer than two service events), we fall
        # back to 0.0, which is honestly what's known in that case.
        events = await self._history_repo.list_for_vehicle(vehicle_id)
        empirical_km_per_month = self._compute_empirical_km_per_month(events)
        kms_driven = (
            round(empirical_km_per_month * months_driven, 1)
            if empirical_km_per_month is not None
            else 0.0
        )

        return VehicleServiceSnapshot(
            vehicle_id=vehicle_id,
            months_driven=months_driven,
            kms_driven=kms_driven,
            make=vehicle.make if vehicle else None,
            vehicle_model=vehicle.model if vehicle else None,
            year=vehicle.year if vehicle else None,
            fuel_type=vehicle.fuel_type if vehicle else None,
            last_service_type=last.service_type,
        )


class Scheduler(Protocol):
    async def schedule(self, vehicle_id: str, service_date: date) -> None: ...


@dataclass
class InMemoryScheduler:
    """Stub Scheduler - records confirmed bookings in memory. Real persistence
    (an `appointments` table + repository) is out of scope for Phase 5; see
    the guardrail this backs in app.agents.guardrails / tools.schedule_service."""

    booked: list[tuple[str, date]] = field(default_factory=list)

    async def schedule(self, vehicle_id: str, service_date: date) -> None:
        self.booked.append((vehicle_id, service_date))


class KBSearchProvider(Protocol):
    async def search(self, query: str) -> list["KBHit"]: ...


class RepositoryKBSearchProvider:
    """Production KBSearchProvider - Phase 6's real RAG pipeline: hybrid
    (pgvector cosine + Postgres full-text) retrieval, RRF-fused, then
    cross-encoder reranked down to the final few chunks. Chunks that don't
    clear `REFUSAL_SCORE_THRESHOLD` are dropped entirely - an empty return
    here is exactly what makes the Knowledge specialist refuse rather than
    answer from weak/irrelevant context (see app.rag.rerank)."""

    def __init__(self, session) -> None:
        self._session = session

    async def search(self, query: str) -> list["KBHit"]:
        from app.rag.rerank import REFUSAL_SCORE_THRESHOLD, rerank_candidates
        from app.rag.retrieval import hybrid_search

        fused = await hybrid_search(self._session, query)
        reranked = rerank_candidates(query, fused)
        return [
            KBHit(
                chunk_id=chunk.chunk_id,
                source=chunk.source,
                section=chunk.section,
                text=chunk.text,
                score=chunk.score,
            )
            for chunk in reranked
            if chunk.score >= REFUSAL_SCORE_THRESHOLD
        ]


@dataclass
class AgentDeps:
    """Dependencies injected into every specialist agent's RunContext."""

    vehicle_data: VehicleDataProvider
    scheduler: Scheduler = field(default_factory=InMemoryScheduler)
    kb: Optional[KBSearchProvider] = None


class PredictServiceResult(BaseModel):
    vehicle_id: str
    predicted_days_until_service: int
    predicted_kms_until_service: float
    earlier_trigger: Literal["time", "km"]
    source: Literal["model_v2", "model_v1", "rules"]


class PredictServiceError(BaseModel):
    vehicle_id: str
    error: str


async def predict_service(
    ctx: RunContext[AgentDeps], vehicle_id: str
) -> PredictServiceResult | PredictServiceError:
    """Predict the next service due date/odometer for a known vehicle.

    Thin wrapper over app.services.predictor.predict / the Phase 3 model
    registry - no prediction logic lives here.
    """
    snapshot = await ctx.deps.vehicle_data.get_snapshot(vehicle_id)
    if snapshot is None:
        return PredictServiceError(
            vehicle_id=vehicle_id,
            error=f"No service history on file for vehicle '{vehicle_id}'.",
        )

    response = predict(
        months_driven=snapshot.months_driven,
        kms_driven=snapshot.kms_driven,
        make=snapshot.make,
        vehicle_model=snapshot.vehicle_model,
        year=snapshot.year,
        fuel_type=snapshot.fuel_type,
        last_service_type=snapshot.last_service_type,
    )
    return PredictServiceResult(
        vehicle_id=vehicle_id,
        predicted_days_until_service=response.predicted_days_until_service,
        predicted_kms_until_service=response.predicted_kms_until_service,
        earlier_trigger=response.earlier_trigger,
        source=response.source,
    )


class KBHit(BaseModel):
    """One retrieved-and-reranked knowledge-base chunk, shaped for the
    Knowledge specialist's citation composition (task 6.5): `chunk_id`
    dedupes/numbers sources across possibly-repeated hits within one run,
    `source` + `section` render a human-readable citation (e.g. "Toyota
    Corolla Service Guide (Synthetic) - Oil and Filter Change"), and `text`
    is the actual chunk content the answer must be grounded in.

    This replaces Phase 5's stub shape (`{title, snippet, source}` - never
    populated, since search_kb always returned `[]`) now that real
    retrieval exists and citations need to reference a specific chunk, not
    just a document title.
    """

    chunk_id: int
    source: str
    section: str
    text: str
    score: float


async def search_kb(ctx: RunContext[AgentDeps], query: str) -> list[KBHit]:
    """Search the knowledge base for `query`.

    Delegates to `ctx.deps.kb` (a `KBSearchProvider` - `RepositoryKBSearchProvider`
    in production, wired in `routers/assistant.py`). Returns `[]` when no
    provider is configured (kept for callers/tests that don't need KB
    behaviour, mirroring Phase 5's stub) *or* when real retrieval ran but
    found nothing that clears the refusal threshold - either way, an empty
    list is what makes the Knowledge specialist say it has no documentation
    rather than fabricate an answer (see app.agents.specialists.knowledge).
    """
    if ctx.deps.kb is None:
        return []
    return await ctx.deps.kb.search(query)


class ScheduleServiceResult(BaseModel):
    vehicle_id: str
    service_date: date
    written: bool
    message: str


async def schedule_service(
    ctx: RunContext[AgentDeps],
    vehicle_id: str,
    service_date: date,
    confirmed: Annotated[
        bool,
        Field(description="Must be true to actually book the service - guardrail: unconfirmed requests never write."),
    ] = False,
) -> ScheduleServiceResult:
    """Book a service appointment. Guardrail: writes ONLY if confirmed=True;
    otherwise returns a confirmation prompt and performs no write."""
    if not confirmed:
        return ScheduleServiceResult(
            vehicle_id=vehicle_id,
            service_date=service_date,
            written=False,
            message=(
                f"I can schedule vehicle '{vehicle_id}' for service on {service_date}, "
                "but I need you to confirm first. Reply with confirmed=true to book it."
            ),
        )

    await ctx.deps.scheduler.schedule(vehicle_id, service_date)
    return ScheduleServiceResult(
        vehicle_id=vehicle_id,
        service_date=service_date,
        written=True,
        message=f"Scheduled vehicle '{vehicle_id}' for service on {service_date}.",
    )
