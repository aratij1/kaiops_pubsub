"""Idempotently copy landing-pad archives to object storage and index MySQL.

Original files are preserved by default. A rerun uses the deterministic
checksum/key and updates the same metadata row. Failures are recorded for safe
retry. This is an offline migration utility, never an interactive API scan.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from common.config import get_settings
from common.database import create_engine, create_schema, create_session_factory
from common.object_storage import build_object_storage, file_sha256
from common.repository import ObjectStorageRepository


def metadata_for(path: Path, root: Path, checksum: str) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if path.suffix.lower() == ".json":
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            payload = loaded if isinstance(loaded, dict) else {}
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            payload = {}
    alert = payload.get("alert") if isinstance(payload.get("alert"), dict) else payload
    relative = path.relative_to(root).as_posix()
    return {
        "object_key": f"landing-pad/{checksum[:2]}/{checksum}-{path.name}",
        "object_uri": "",
        "object_type": "landing-pad-archive",
        "application": str(alert.get("application") or alert.get("project_name") or "") or None,
        "environment": str(alert.get("environment") or "") or None,
        "source": str(alert.get("source") or payload.get("source") or "landing-pad") or None,
        "occurrence_at": None,
        "ingested_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc),
        "size_bytes": path.stat().st_size,
        "checksum_sha256": checksum,
        "retention_policy": "landing-pad-standard",
        "security_classification": "internal",
        "processing_status": "migration_pending",
        "metadata_payload": {"original_relative_path": relative, "migration_attempts": 0},
    }


async def migrate(root: Path, *, limit: int, dry_run: bool) -> dict[str, int]:
    settings = get_settings()
    if not settings.object_storage_enabled and not dry_run:
        raise RuntimeError("OBJECT_STORAGE_ENABLED=true is required")
    paths = sorted(path for path in root.rglob("*") if path.is_file())[: max(1, limit)]
    if dry_run:
        return {"discovered": len(paths), "stored": 0, "failed": 0}
    storage = build_object_storage(settings)
    engine = create_engine(settings)
    await create_schema(engine)
    sessions = create_session_factory(engine)
    stored = failed = 0
    for path in paths:
        checksum = file_sha256(path)
        values = metadata_for(path, root, checksum)
        try:
            values["object_uri"] = await storage.put_file(values["object_key"], path, checksum)
            values["processing_status"] = "stored"
            stored += 1
        except Exception as exc:
            values["object_uri"] = f"migration-failed://{values['object_key']}"
            values["processing_status"] = "migration_failed"
            values["metadata_payload"] = {**values["metadata_payload"], "last_error": str(exc)}
            failed += 1
        async with sessions() as session:
            await ObjectStorageRepository(session).upsert(values)
            await session.commit()
    await engine.dispose()
    return {"discovered": len(paths), "stored": stored, "failed": failed}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("backend/ingested_alerts/archive"))
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.root.resolve().is_dir():
        raise SystemExit(f"archive root does not exist: {args.root.resolve()}")
    print(json.dumps(asyncio.run(migrate(args.root.resolve(), limit=args.limit, dry_run=args.dry_run)), sort_keys=True))


if __name__ == "__main__":
    main()
