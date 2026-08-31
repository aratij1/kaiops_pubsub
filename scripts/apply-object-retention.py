"""Apply object-storage retention from the indexed MySQL catalog.

The command is a dry run unless --execute is supplied. It never scans the
archive filesystem and marks metadata deleted only after provider deletion
succeeds, making failed runs safe to retry.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timedelta, timezone

from common.config import get_settings
from common.database import create_engine, create_session_factory
from common.object_storage import build_object_storage
from common.repository import ObjectStorageRepository


async def apply_retention(*, days: int, limit: int, execute: bool) -> dict[str, int]:
    settings = get_settings()
    if execute and not settings.object_storage_enabled:
        raise RuntimeError("OBJECT_STORAGE_ENABLED=true is required for deletion")
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, days))
    selected = deleted = failed = 0
    storage = build_object_storage(settings) if execute else None
    async with sessions() as session:
        repository = ObjectStorageRepository(session)
        rows = await repository.retention_candidates(before=cutoff, limit=limit)
        selected = len(rows)
        if execute and storage is not None:
            for row in rows:
                try:
                    await storage.delete(row.object_key)
                    await repository.mark_deleted(row, deleted_at=datetime.now(timezone.utc))
                    await session.commit()
                    deleted += 1
                except Exception:
                    await session.rollback()
                    failed += 1
    await engine.dispose()
    return {"selected": selected, "deleted": deleted, "failed": failed, "dry_run": int(not execute)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(apply_retention(days=args.days, limit=args.limit, execute=args.execute)), sort_keys=True))


if __name__ == "__main__":
    main()
