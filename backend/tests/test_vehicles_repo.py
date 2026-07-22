"""Unit tests for the Vehicle ORM model + repository."""

from datetime import date

from app.repositories.vehicles import VehicleRepository


async def test_create_and_get_vehicle(db_session):
    repo = VehicleRepository(db_session)

    created = await repo.create(
        id="V001",
        make="Toyota",
        model="Corolla",
        year=2020,
        fuel_type="petrol",
        registered_at=date(2020, 1, 15),
    )
    await db_session.commit()

    fetched = await repo.get("V001")

    assert fetched is not None
    assert fetched.id == "V001"
    assert fetched.make == "Toyota"
    assert fetched.model == "Corolla"
    assert fetched.year == 2020
    assert fetched.fuel_type == "petrol"
    assert fetched.registered_at == date(2020, 1, 15)
    assert created.id == fetched.id


async def test_list_vehicles(db_session):
    repo = VehicleRepository(db_session)
    await repo.create(id="V001", make="Toyota", model="Corolla", year=2020, fuel_type="petrol")
    await repo.create(id="V002", make="Honda", model="Civic", year=2021, fuel_type="petrol")
    await db_session.commit()

    vehicles = await repo.list()

    assert {v.id for v in vehicles} == {"V001", "V002"}


async def test_get_missing_vehicle_returns_none(db_session):
    repo = VehicleRepository(db_session)
    assert await repo.get("UNKNOWN") is None
