"""Data access for ServiceHistory rows."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.service_history import ServiceHistory


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
