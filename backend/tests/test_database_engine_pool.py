"""create_engine now wires the (previously unconfigured) DB connection pool
size through to SQLAlchemy, since a raised MESSAGE_BUS_WORKER_COUNT for a
10k-alert burst needs more than the ~15-connection implicit default. The
sqlite path must keep skipping pool kwargs entirely, since aiosqlite's pool
class rejects pool_size/max_overflow.
"""

from __future__ import annotations

from unittest.mock import patch

from common.config import Settings
from common.database import create_engine


def test_create_engine_sqlite_skips_pool_kwargs() -> None:
    # aiosqlite may not be installed in every environment; assert the guard
    # behavior (no pool_size/max_overflow passed for sqlite) by inspecting the
    # call rather than requiring the real driver. install_db_circuit_breaker
    # is also mocked out here since it registers real SQLAlchemy event
    # listeners that require a genuine Engine, not this mocked one — the
    # mechanism itself is covered by test_database_circuit_breaker.py.
    settings = Settings(DATABASE_URL="sqlite+aiosqlite:///:memory:")
    with (
        patch("common.database.create_async_engine") as mock_create,
        patch("common.database.install_db_circuit_breaker"),
    ):
        create_engine(settings)
    _args, kwargs = mock_create.call_args
    assert "pool_size" not in kwargs
    assert "max_overflow" not in kwargs


def test_create_engine_mysql_applies_configured_pool_size() -> None:
    settings = Settings(
        DATABASE_URL="mysql+aiomysql://user:pass@localhost:3306/kaiops",
        DB_POOL_SIZE=7,
        DB_MAX_OVERFLOW=13,
    )
    engine = create_engine(settings)
    assert engine.pool.size() == 7


def test_create_engine_mysql_defaults_match_conservative_global_default() -> None:
    settings = Settings(DATABASE_URL="mysql+aiomysql://user:pass@localhost:3306/kaiops")
    engine = create_engine(settings)
    assert engine.pool.size() == 10
