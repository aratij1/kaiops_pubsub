from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "database" / "migrations"


def migration_manifest(directory: Path = MIGRATIONS_DIR) -> dict[str, str]:
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.glob("*.sql"), key=lambda item: item.name)
    }


def current_schema_version(directory: Path = MIGRATIONS_DIR) -> str:
    manifest = migration_manifest(directory)
    return Path(next(reversed(manifest), "unversioned")).stem


async def inspect_schema_compatibility(connection: AsyncConnection) -> dict[str, Any]:
    expected = migration_manifest()
    version = Path(next(reversed(expected), "unversioned")).stem
    if connection.dialect.name != "mysql":
        return {"compatible": True, "schema_version": version, "pending": [], "changed": []}
    table_exists = await connection.scalar(text(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_schema = DATABASE() AND table_name = 'schema_migrations'"
    ))
    if int(table_exists or 0) == 0:
        return {"compatible": False, "schema_version": "unversioned", "pending": list(expected), "changed": []}
    rows = (await connection.execute(text(
        "SELECT filename, checksum_sha256 FROM schema_migrations ORDER BY filename"
    ))).all()
    applied = {str(row[0]): str(row[1] or "") for row in rows}
    pending = [name for name in expected if name not in applied]
    changed = [name for name, checksum in expected.items() if name in applied and applied[name] != checksum]
    applied_known = [name for name in expected if name in applied and name not in changed]
    applied_version = Path(applied_known[-1]).stem if applied_known else "unversioned"
    return {
        "compatible": not pending and not changed,
        "schema_version": applied_version,
        "expected_schema_version": version,
        "pending": pending,
        "changed": changed,
    }


async def schema_compatibility(engine: AsyncEngine) -> dict[str, Any]:
    async with engine.connect() as connection:
        return await inspect_schema_compatibility(connection)


def require_compatible_schema(state: dict[str, Any]) -> None:
    if state.get("compatible") is True:
        return
    if state.get("changed"):
        raise RuntimeError("applied migration checksum mismatch")
    raise RuntimeError("pending database migrations")
