"""Data access for Vehicle rows."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vehicle import Vehicle


class VehicleRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        id: str,
        make: str | None = None,
        model: str | None = None,
        year: int | None = None,
        fuel_type: str | None = None,
        registered_at: date | None = None,
        owner_id: int | None = None,
    ) -> Vehicle:
        vehicle = Vehicle(
            id=id,
            make=make,
            model=model,
            year=year,
            fuel_type=fuel_type,
            registered_at=registered_at,
            owner_id=owner_id,
        )
        self.session.add(vehicle)
        await self.session.flush()
        return vehicle

    async def get(self, vehicle_id: str) -> Vehicle | None:
        return await self.session.get(Vehicle, vehicle_id)

    async def list(self) -> list[Vehicle]:
        result = await self.session.execute(select(Vehicle))
        return list(result.scalars().all())

    async def upsert_metadata(
        self,
        vehicle_id: str,
        make: str | None = None,
        model: str | None = None,
        year: int | None = None,
        fuel_type: str | None = None,
    ) -> Vehicle:
        """Create the vehicle if missing, or patch non-None metadata fields onto it."""
        vehicle = await self.get(vehicle_id)
        if vehicle is None:
            vehicle = Vehicle(id=vehicle_id)
            self.session.add(vehicle)

        if make is not None:
            vehicle.make = make
        if model is not None:
            vehicle.model = model
        if year is not None:
            vehicle.year = year
        if fuel_type is not None:
            vehicle.fuel_type = fuel_type

        await self.session.flush()
        return vehicle
