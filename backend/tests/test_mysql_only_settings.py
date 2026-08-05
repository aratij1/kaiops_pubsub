from __future__ import annotations

import pytest
from common.config import Settings
from pydantic import ValidationError


def test_mysql_is_the_default_relational_database() -> None:
    settings = Settings(ENVIRONMENT="test")
    assert settings.database_url.startswith("mysql+aiomysql://")


def test_postgresql_database_url_is_rejected() -> None:
    with pytest.raises(ValidationError, match="only MySQL"):
        Settings(ENVIRONMENT="test", DATABASE_URL="postgresql+asyncpg://user:pass@db/kaiops")


def test_sqlite_is_limited_to_non_production_tests() -> None:
    assert Settings(ENVIRONMENT="test", DATABASE_URL="sqlite+aiosqlite:///:memory:").database_url.startswith("sqlite")
    with pytest.raises(ValidationError, match="only MySQL"):
        Settings(ENVIRONMENT="production", DATABASE_URL="sqlite+aiosqlite:///:memory:")
