from pathlib import Path

import pytest
from common.migration_state import (
    current_schema_version,
    inspect_schema_compatibility,
    migration_manifest,
    require_compatible_schema,
)


def test_manifest_and_schema_version_follow_forward_filename_order(tmp_path: Path) -> None:
    (tmp_path / "20260102_second.sql").write_text("SELECT 2;", encoding="utf-8")
    (tmp_path / "20260101_first.sql").write_text("SELECT 1;", encoding="utf-8")

    manifest = migration_manifest(tmp_path)

    assert list(manifest) == ["20260101_first.sql", "20260102_second.sql"]
    assert current_schema_version(tmp_path) == "20260102_second"


def test_incompatible_schema_fails_closed() -> None:
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        require_compatible_schema({"compatible": False, "changed": ["changed.sql"]})
    with pytest.raises(RuntimeError, match="pending"):
        require_compatible_schema({"compatible": False, "changed": [], "pending": ["pending.sql"]})


@pytest.mark.asyncio
async def test_non_mysql_development_schema_is_compatible(sqlite_session_factory) -> None:
    async with sqlite_session_factory() as session:
        connection = await session.connection()
        state = await inspect_schema_compatibility(connection)
    assert state["compatible"] is True
    assert state["schema_version"] == Path(next(reversed(migration_manifest()))).stem
