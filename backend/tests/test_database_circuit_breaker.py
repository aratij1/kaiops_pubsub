import asyncio

import pytest
from common.database import Base, install_db_circuit_breaker
from common.resilience import CircuitBreaker, CircuitOpenError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


@pytest.mark.asyncio
async def test_open_circuit_rejects_new_checkouts_without_touching_the_database() -> None:
    """A MySQL/Postgres blip trips the breaker after enough real failures;
    once open, subsequent DB work must fail fast (CircuitOpenError) instead
    of every consumer independently waiting out its own connection/pool
    timeout. This test opens the breaker directly (record_failure) rather
    than simulating a real outage, since the mechanism under test is the
    checkout gate, not database failure detection itself.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    breaker = CircuitBreaker(failure_threshold=2, recovery_seconds=0.05)
    install_db_circuit_breaker(engine, breaker)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    # Healthy while closed.
    async with session_factory() as session:
        await session.execute(text("SELECT 1"))

    breaker.record_failure()
    breaker.record_failure()

    with pytest.raises(CircuitOpenError):
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))

    # Auto-heals after recovery_seconds even without an explicit success signal.
    await asyncio.sleep(0.1)
    async with session_factory() as session:
        await session.execute(text("SELECT 1"))

    await engine.dispose()


@pytest.mark.asyncio
async def test_real_query_failure_counts_toward_opening_the_circuit() -> None:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    breaker = CircuitBreaker(failure_threshold=1, recovery_seconds=60.0)
    install_db_circuit_breaker(engine, breaker)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    with pytest.raises(Exception):
        async with session_factory() as session:
            await session.execute(text("SELECT * FROM this_table_does_not_exist"))

    with pytest.raises(CircuitOpenError):
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))

    await engine.dispose()
