"""Restartable canonical incident-correlation backfill; dry-run by default."""

from __future__ import annotations

import argparse
import asyncio
import json

from common.config import get_settings
from common.correlation_backfill import backfill_incident_correlations
from common.database import create_engine, create_session_factory


async def run(*, execute: bool, batch_size: int, resume_cursor: str | None) -> dict[str, object]:
    engine = create_engine(get_settings())
    sessions = create_session_factory(engine)
    try:
        async with sessions() as session:
            report = await backfill_incident_correlations(
                session,
                batch_size=batch_size,
                resume_cursor=resume_cursor,
                dry_run=not execute,
            )
            return report.model_dump()
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="persist one verified backfill batch")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--resume-cursor", help="exclusive durable incident UUID cursor")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(
        execute=args.execute,
        batch_size=args.batch_size,
        resume_cursor=args.resume_cursor,
    )), sort_keys=True))


if __name__ == "__main__":
    main()
