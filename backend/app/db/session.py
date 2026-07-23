"""Async SQLAlchemy engine, session factory, and FastAPI session dependency."""

from typing import AsyncGenerator

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings


def _build_engine(database_url: str):
    # Managed Postgres providers (Neon, RDS, etc.) commonly hand out
    # connection strings with a libpq-style `sslmode=require` query param.
    # asyncpg doesn't understand that key - it wants a bare `ssl` connect
    # arg instead - so translate it rather than letting the engine fail to
    # connect on every managed-DB deploy. Local dev URLs (docker-compose,
    # no sslmode) are untouched.
    url = make_url(database_url)
    query = dict(url.query)
    sslmode = query.pop("sslmode", None)
    connect_args = {}
    if sslmode and sslmode != "disable":
        connect_args["ssl"] = "require" if sslmode == "require" else sslmode
    if sslmode is not None:
        url = url.set(query=query)
    return create_async_engine(url, poolclass=NullPool, connect_args=connect_args)


# NullPool: never reuse a DBAPI connection across calls. The engine is a
# module-level singleton, but it is exercised from more than one event loop
# within the same process (sync TestClient spawns its own background loop
# distinct from pytest-asyncio's), and asyncpg connections are bound to the
# loop that created them - a pooled connection handed to a different loop
# than the one that opened it crashes. NullPool sidesteps this entirely by
# always opening a fresh connection for the duration of a single operation.
engine = _build_engine(settings.DATABASE_URL)

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an AsyncSession, closed after the request."""
    async with async_session_factory() as session:
        yield session
