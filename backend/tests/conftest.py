"""
Shared test fixtures.

Test DB strategy: a dedicated ``pitcrew_test`` database on the same running
compose ``db`` container (see docker-compose.yml), never the dev ``pitcrew``
database. This is simpler and more robust than transactional-rollback
fixtures around a shared schema: every test gets a real, fully-migrated
schema recreated from ``Base.metadata`` and there is no risk of leaking
uncommitted state between async sessions (an async engine may hand out
more than one connection per test, so a single outer transaction to roll
back is not guaranteed to see everything written in the test).

The ``DATABASE_URL`` env var is pinned to the test database *before* any
``app.*`` module is imported, so ``app.config.settings`` (loaded once at
import time) always points at the test database for the whole test
session - this must happen at the top of this file, before other imports.
"""

import os

os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://pitcrew:pitcrew@localhost:5432/pitcrew_test",
)
os.environ.setdefault("JWT_SECRET", "test-only-secret-do-not-use-in-prod")

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text as sa_text

import app.models  # noqa: F401 - registers all ORM models on Base.metadata
from app.auth.hashing import hash_password
from app.db.base import Base
from app.db.session import async_session_factory, engine
from app.main import app
from app.repositories.users import UserRepository


@pytest_asyncio.fixture(autouse=True)
async def _clean_database():
    """Recreate a fresh schema on the test database before every test.

    Tests build the schema straight from `Base.metadata` rather than
    running Alembic migrations (see module docstring), which means the
    `CREATE EXTENSION vector` step the KB migration performs (Phase 6) never
    runs here - a fresh CI database would otherwise fail to create
    `kb_chunks`' pgvector column. `IF NOT EXISTS` makes this a no-op on a
    dev machine where Phase 0 already enabled it.
    """
    async with engine.begin() as conn:
        await conn.execute(sa_text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest_asyncio.fixture
async def db_session():
    async with async_session_factory() as session:
        yield session


async def create_user_directly(email: str, password: str, role: str) -> None:
    """
    Provision a user by writing straight to the repository, bypassing
    ``POST /auth/register``.

    Self-registration deliberately only permits the "owner"/"demo" roles
    (see ``app.routers.auth.SELF_SERVE_ROLES``) - "mechanic" and "admin"
    accounts are provisioned out of band in real deployments, so tests that
    need one create it the same way rather than going through the
    (intentionally role-restricted) public endpoint.
    """
    async with async_session_factory() as session:
        user_repo = UserRepository(session)
        await user_repo.create(email=email, hashed_password=hash_password(password), role=role)
        await session.commit()


@pytest_asyncio.fixture
async def async_client():
    """
    httpx.AsyncClient wired directly to the app via ASGI transport (in-process, no server).

    base_url uses https:// (not http://) because the refresh-token cookie is
    marked Secure - httpx's cookie jar (correctly) withholds Secure cookies
    from being resent over a plain http:// base_url, which would silently
    break any test exercising the refresh-cookie flow.
    """
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="https://test") as client:
            yield client
