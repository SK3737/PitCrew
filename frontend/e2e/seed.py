"""
Idempotent seed step for the Playwright e2e suite (frontend/e2e/).

Ensures, against whatever Postgres database DATABASE_URL currently points
at (the same one the backend under test is running against):

  1. At least one vehicle with service history exists - imports the
     existing `backend/data/service_history.json` fixture via the
     backend's own `scripts.import_json.import_data`, only if the
     vehicles table is currently empty. Never inserts rows directly.
  2. A "mechanic" user exists with a known email/password, so the e2e
     test can log in as a role that holds `read_vehicles` + `run_predict`
     - mechanic can see the whole seeded fleet, unlike "owner" (scoped to
     vehicles it owns; the seed fixture has no owner_id set) or "demo"
     (read-only, no run_predict - the dashboard needs both permissions).
     Provisioned directly, the same way backend/tests/conftest.py's
     `create_user_directly` does, because self-registration deliberately
     refuses to grant the "mechanic" role (see
     app.routers.auth.SELF_SERVE_ROLES).

Deliberately does not touch backend code, migrations, or data files - it
only imports and calls existing backend modules from the outside.

Run with the same Python environment used to run the backend itself, from
`backend/` (or with `backend/` importable on PYTHONPATH):

    python ../frontend/e2e/seed.py
"""

import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.auth.hashing import hash_password  # noqa: E402
from app.db.session import async_session_factory  # noqa: E402
from app.repositories.users import UserRepository  # noqa: E402
from app.repositories.vehicles import VehicleRepository  # noqa: E402
from scripts.import_json import import_data  # noqa: E402

E2E_MECHANIC_EMAIL = "e2e-mechanic@pitcrew.dev"
E2E_MECHANIC_PASSWORD = "pitcrew-e2e-password"


async def ensure_vehicles_seeded() -> None:
    async with async_session_factory() as session:
        vehicles = await VehicleRepository(session).list()

    if vehicles:
        print(f"[e2e seed] {len(vehicles)} vehicle(s) already present - skipping import")
        return

    vehicle_count, event_count = await import_data()
    print(f"[e2e seed] imported {vehicle_count} vehicle(s), {event_count} service event(s)")


async def ensure_mechanic_user() -> None:
    async with async_session_factory() as session:
        user_repo = UserRepository(session)
        existing = await user_repo.get_by_email(E2E_MECHANIC_EMAIL)
        if existing is not None:
            print(f"[e2e seed] user {E2E_MECHANIC_EMAIL!r} already exists (id={existing.id})")
            return

        user = await user_repo.create(
            email=E2E_MECHANIC_EMAIL,
            hashed_password=hash_password(E2E_MECHANIC_PASSWORD),
            role="mechanic",
        )
        await session.commit()
        print(f"[e2e seed] created user {E2E_MECHANIC_EMAIL!r} (id={user.id}, role=mechanic)")


async def main() -> None:
    await ensure_vehicles_seeded()
    await ensure_mechanic_user()


if __name__ == "__main__":
    asyncio.run(main())
