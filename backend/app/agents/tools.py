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
        from app.repositories.service_history import ServiceHistoryRepository
        from app.repositories.vehicles import VehicleRepository

        self._history_repo = ServiceHistoryRepository(session)
        self._vehicle_repo = VehicleRepository(session)

    async def get_snapshot(self, vehicle_id: str) -> Optional[VehicleServiceSnapshot]:
        last = await self._history_repo.get_last_for_vehicle(vehicle_id)
        if last is None:
            return None

        vehicle = await self._vehicle_repo.get(vehicle_id)
        months_driven = (date.today() - last.serviced_at).days / 30.44

        return VehicleServiceSnapshot(
            vehicle_id=vehicle_id,
            months_driven=max(months_driven, 0.0),
            # Absolute odometer reading isn't asked by the assistant, so we
            # treat "kms since last service" as unknown (0) unless a caller
            # of predict_service supplies it explicitly via current_odometer_km.
            kms_driven=0.0,
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


@dataclass
class AgentDeps:
    """Dependencies injected into every specialist agent's RunContext."""

    vehicle_data: VehicleDataProvider
    scheduler: Scheduler = field(default_factory=InMemoryScheduler)


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
    title: str
    snippet: str
    source: str


async def search_kb(ctx: RunContext[AgentDeps], query: str) -> list[KBHit]:
    """Search the knowledge base for `query`.

    Stub for Phase 5: no knowledge base is indexed yet. Phase 6 (RAG) fills
    this in with real retrieval against an embedded corpus; until then this
    always returns an empty list and the Knowledge specialist says so.
    """
    return []


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
