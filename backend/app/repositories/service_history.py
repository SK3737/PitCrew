"""Data access for ServiceHistory rows."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.service_history import ServiceHistory


def compute_empirical_km_per_month(events: list[ServiceHistory]) -> float | None:
    """Estimate a vehicle's typical km/month from consecutive service events.

    Shared between routers/vehicles.py (surfaced directly on the history
    response) and app.agents.tools (used to estimate kms_driven for the
    assistant's predict_service tool, since a bare vehicle_id carries no
    live odometer reading). Returns None when there's insufficient history
    (fewer than two events, or no valid positive-duration interval) to
    derive an estimate at all.
    """
    if len(events) < 2:
        return None
    total_km, total_months = 0.0, 0.0
    for i in range(1, len(events)):
        prev, curr = events[i - 1], events[i]
        km_diff = curr.odo_km - prev.odo_km
        months_diff = (curr.serviced_at - prev.serviced_at).days / 30.44
        if months_diff > 0 and km_diff >= 0:
            total_km += km_diff
            total_months += months_diff
    return round(total_km / total_months, 1) if total_months else None


class ServiceHistoryRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add_event(
        self,
        vehicle_id: str,
        service_date: date,
        odometer_km: float,
        service_type: str | None = None,
    ) -> ServiceHistory:
        event = ServiceHistory(
            vehicle_id=vehicle_id,
            serviced_at=service_date,
            odo_km=odometer_km,
            service_type=service_type,
        )
        self.session.add(event)
        await self.session.flush()
        return event

    async def list_for_vehicle(self, vehicle_id: str) -> list[ServiceHistory]:
        result = await self.session.execute(
            select(ServiceHistory)
            .where(ServiceHistory.vehicle_id == vehicle_id)
            .order_by(ServiceHistory.serviced_at, ServiceHistory.id)
        )
        return list(result.scalars().all())

    async def get_last_for_vehicle(self, vehicle_id: str) -> ServiceHistory | None:
        events = await self.list_for_vehicle(vehicle_id)
        return events[-1] if events else None
