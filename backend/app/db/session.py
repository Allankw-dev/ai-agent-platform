from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

import app.db.tenancy  # noqa: F401  (registers the Row Level Security context listener)
from app.core.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session


@asynccontextmanager
async def standalone_sessionmaker() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A private engine for code that runs outside the API process (Celery tasks).

    Each task runs in its own event loop, and a pooled async connection cannot be shared across
    loops, so a task gets its own unpooled engine and disposes of it when done.
    """
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
