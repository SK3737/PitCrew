"""
GET /vehicles - added in Phase 4 as a minimal, necessary backend change: the
new Next.js dashboard has no way to discover which vehicles exist otherwise
(the repository already had a `list()` method with no route exposing it).

Covers the same owner-scoping contract as GET /{vehicle_id}/history so the
new route can't accidentally leak other owners' vehicles.
"""

import uuid

from app.db.session import async_session_factory
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
        await create_user_directly(email, PASSWORD, role=role)

    login = await async_client.post("/auth/login", json={"email": email, "password": PASSWORD})
    access_token = login.json()["access_token"]

    import jwt as pyjwt

    claims = pyjwt.decode(access_token, options={"verify_signature": False})
    return int(claims["sub"]), {"Authorization": f"Bearer {access_token}"}


async def _seed_vehicle(vehicle_id: str, owner_id: int | None = None) -> None:
    async with async_session_factory() as session:
        vehicle_repo = VehicleRepository(session)
        await vehicle_repo.create(
            id=vehicle_id, make="Toyota", model="Corolla", year=2020, owner_id=owner_id
        )
        await session.commit()


async def test_mechanic_sees_every_vehicle(async_client):
    await _seed_vehicle("LIST_V001")
    await _seed_vehicle("LIST_V002")
    _, headers = await _register_and_login(async_client, "mechanic")

    r = await async_client.get("/vehicles/", headers=headers)

    assert r.status_code == 200
    ids = {row["vehicle_id"] for row in r.json()}
    assert {"LIST_V001", "LIST_V002"}.issubset(ids)


async def test_owner_only_sees_their_own_vehicles(async_client):
    owner_id, owner_headers = await _register_and_login(async_client, "owner")
    await _seed_vehicle("LIST_V003", owner_id=owner_id)
    await _seed_vehicle("LIST_V004", owner_id=None)  # someone else's / unowned

    r = await async_client.get("/vehicles/", headers=owner_headers)

    assert r.status_code == 200
    ids = {row["vehicle_id"] for row in r.json()}
    assert ids == {"LIST_V003"}


async def test_demo_role_is_forbidden(async_client):
    _, headers = await _register_and_login(async_client, "demo")

    r = await async_client.get("/vehicles/", headers=headers)

    assert r.status_code == 403


async def test_unauthenticated_request_is_rejected(async_client):
    r = await async_client.get("/vehicles/")

    assert r.status_code == 401
