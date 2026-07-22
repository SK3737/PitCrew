"""
Owner-scoping on GET /vehicles/{id}/history.

The negative case (an owner denied someone else's vehicle) is also covered
in test_api.py::TestVehicles::test_owner_cannot_view_another_owners_vehicle;
this file additionally proves the positive case - an owner CAN see a
vehicle whose ``owner_id`` actually matches them - since a guard that always
403s an "owner" role would pass the negative-only test just as well.
"""

import uuid
from datetime import date

from app.db.session import async_session_factory
from app.repositories.service_history import ServiceHistoryRepository
from app.repositories.vehicles import VehicleRepository
from tests.conftest import create_user_directly

PASSWORD = "correct horse battery staple"
SELF_SERVE_ROLES = frozenset({"owner", "demo"})


async def _register_and_login(async_client, role: str) -> tuple[int, dict]:
    email = f"{role}-{uuid.uuid4()}@example.com"
    if role in SELF_SERVE_ROLES:
        await async_client.post(
            "/auth/register", json={"email": email, "password": PASSWORD, "role": role}
        )
    else:
        # POST /auth/register deliberately refuses to self-grant privileged
        # roles (e.g. "mechanic") - provision those directly instead.
        await create_user_directly(email, PASSWORD, role=role)

    login = await async_client.post("/auth/login", json={"email": email, "password": PASSWORD})
    access_token = login.json()["access_token"]

    # Look up the id we just created (register's response also has it, but
    # re-deriving from /auth/login's decoded token keeps this self-contained).
    import jwt as pyjwt

    claims = pyjwt.decode(access_token, options={"verify_signature": False})
    return int(claims["sub"]), {"Authorization": f"Bearer {access_token}"}


async def _seed_vehicle_owned_by(vehicle_id: str, owner_id: int) -> None:
    async with async_session_factory() as session:
        vehicle_repo = VehicleRepository(session)
        history_repo = ServiceHistoryRepository(session)
        await vehicle_repo.create(id=vehicle_id, make="Toyota", model="Corolla", owner_id=owner_id)
        await history_repo.add_event(
            vehicle_id, service_date=date(2025, 11, 1), odometer_km=45000.0, service_type="oil_change"
        )
        await session.commit()


async def test_owner_can_view_their_own_vehicle(async_client):
    owner_id, headers = await _register_and_login(async_client, "owner")
    await _seed_vehicle_owned_by("OWNED_V001", owner_id)

    r = await async_client.get("/vehicles/OWNED_V001/history", headers=headers)

    assert r.status_code == 200
    assert r.json()["vehicle_id"] == "OWNED_V001"


async def test_owner_is_denied_a_vehicle_owned_by_someone_else(async_client):
    other_owner_id, _ = await _register_and_login(async_client, "owner")
    await _seed_vehicle_owned_by("OWNED_V002", other_owner_id)

    _, my_headers = await _register_and_login(async_client, "owner")
    r = await async_client.get("/vehicles/OWNED_V002/history", headers=my_headers)

    assert r.status_code == 403


async def test_mechanic_can_view_any_vehicle_regardless_of_owner(async_client):
    owner_id, _ = await _register_and_login(async_client, "owner")
    await _seed_vehicle_owned_by("OWNED_V003", owner_id)

    _, mechanic_headers = await _register_and_login(async_client, "mechanic")
    r = await async_client.get("/vehicles/OWNED_V003/history", headers=mechanic_headers)

    assert r.status_code == 200
