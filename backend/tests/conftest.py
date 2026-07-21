from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from common.database import create_schema
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


@pytest_asyncio.fixture
async def sqlite_session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A fresh in-memory SQLite database with the full app schema, per test.

    StaticPool keeps all connections in a test pointed at the same in-memory
    database (plain :memory: gives each connection its own empty database).
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    await create_schema(engine)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield session_factory
    finally:
        await engine.dispose()
