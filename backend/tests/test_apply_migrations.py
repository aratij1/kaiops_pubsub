import importlib.util
import sys
from pathlib import Path

import pytest


def load_migrations_module():
    module_path = Path("scripts/apply-migrations.py")
    spec = importlib.util.spec_from_file_location("apply_migrations", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_resolve_connection_kwargs_parses_database_url() -> None:
    module = load_migrations_module()

    kwargs = module.resolve_connection_kwargs("mysql+aiomysql://kaiops:s3cr%40t@dbhost:3307/kaiops")

    assert kwargs == {
        "host": "dbhost",
        "port": 3307,
        "user": "kaiops",
        "password": "s3cr@t",
        "database": "kaiops",
    }


def test_resolve_connection_kwargs_falls_back_to_discrete_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_migrations_module()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DB_HOST", "envhost")
    monkeypatch.setenv("DB_PORT", "3308")
    monkeypatch.setenv("DB_USER", "envuser")
    monkeypatch.setenv("DB_PASSWORD", "envpass")
    monkeypatch.setenv("DB_DATABASE", "envdb")

    kwargs = module.resolve_connection_kwargs(None)

    assert kwargs == {
        "host": "envhost",
        "port": 3308,
        "user": "envuser",
        "password": "envpass",
        "database": "envdb",
    }


def test_resolve_connection_kwargs_rejects_non_mysql_url() -> None:
    module = load_migrations_module()

    with pytest.raises(ValueError, match="only MySQL"):
        module.resolve_connection_kwargs("postgresql://user:pass@host:5432/db")


def test_list_migration_files_returns_sorted_sql_files() -> None:
    module = load_migrations_module()

    files = module.list_migration_files()

    names = [f.name for f in files]
    assert names == sorted(names)
    assert all(name.endswith(".sql") for name in names)
    assert "20260701_user_rbac.sql" in names
