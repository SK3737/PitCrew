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

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

import app.models  # noqa: F401 - registers all ORM models on Base.metadata
from app.db.base import Base
from app.db.session import async_session_factory, engine
from app.main import app


@pytest_asyncio.fixture(autouse=True)
async def _clean_database():
    """Recreate a fresh schema on the test database before every test."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest_asyncio.fixture
async def db_session():
    async with async_session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def async_client():
    """httpx.AsyncClient wired directly to the app via ASGI transport (in-process, no server)."""
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
