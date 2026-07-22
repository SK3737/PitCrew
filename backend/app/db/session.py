"""Async SQLAlchemy engine, session factory, and FastAPI session dependency."""

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings

# NullPool: never reuse a DBAPI connection across calls. The engine is a
# module-level singleton, but it is exercised from more than one event loop
# within the same process (sync TestClient spawns its own background loop
# distinct from pytest-asyncio's), and asyncpg connections are bound to the
# loop that created them - a pooled connection handed to a different loop
# than the one that opened it crashes. NullPool sidesteps this entirely by
# always opening a fresh connection for the duration of a single operation.
engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an AsyncSession, closed after the request."""
    async with async_session_factory() as session:
        yield session
