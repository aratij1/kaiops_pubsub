#!/usr/bin/env python3
"""Read-only, content-safe incident pipeline diagnosis."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src" / "common"))

from common.config import get_settings  # noqa: E402


async def _one(connection: Any, statement: str, parameters: dict[str, Any]) -> dict[str, Any] | None:
    result = await connection.execute(text(statement), parameters)
    row = result.mappings().first()
    return dict(row) if row else None


async def diagnose(tenant_id: str, incident_id: str) -> list[tuple[str, str, str, str]]:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    params = {"tenant": tenant_id, "incident": incident_id}
    try:
        async with engine.connect() as connection:
            incident = await _one(
                connection,
                """
                SELECT id, status FROM incidents WHERE tenant_id=:tenant AND id=:incident LIMIT 1
            """,
                params,
            )
            requirement = await _one(
                connection,
                """
                SELECT COUNT(*) AS total,
                       SUM(status NOT IN ('collected','answered','cancelled')) AS active
                FROM context_evidence_requirements WHERE tenant_id=:tenant AND incident_id=:incident
            """,
                params,
            )
            job = await _one(
                connection,
                """
                SELECT job_id, status, attempt_count, last_error FROM context_enrichment_jobs
                WHERE tenant_id=:tenant AND incident_id=:incident ORDER BY updated_at DESC LIMIT 1
            """,
                params,
            )
            evidence = await _one(
                connection,
                """
                SELECT COUNT(*) AS total FROM canonical_evidence
                WHERE tenant_id=:tenant AND incident_id=:incident
            """,
                params,
            )
            rejection = await _one(
                connection,
                """
                SELECT reason_code FROM evidence_rejections
                WHERE tenant_id=:tenant AND incident_id=:incident ORDER BY created_at DESC LIMIT 1
            """,
                params,
            )
            snapshot = await _one(
                connection,
                """
                SELECT snapshot_id, snapshot_version FROM context_snapshots
                WHERE tenant_id=:tenant AND incident_id=:incident ORDER BY snapshot_version DESC LIMIT 1
            """,
                params,
            )
            investigation = await _one(
                connection,
                """
                SELECT investigation_id, rca_version, status FROM incident_investigation_bindings
                WHERE tenant_id=:tenant AND incident_id=:incident ORDER BY rca_version DESC LIMIT 1
            """,
                params,
            )
            resolution = await _one(
                connection,
                """
                SELECT plan_id, plan_version FROM governed_resolution_plans
                WHERE tenant_id=:tenant AND incident_id=:incident ORDER BY plan_version DESC LIMIT 1
            """,
                params,
            )
            approval = await _one(
                connection,
                """
                SELECT id, decision FROM approvals
                WHERE tenant_id=:tenant AND incident_id=:incident ORDER BY created_at DESC LIMIT 1
            """,
                params,
            )
            projection = await _one(
                connection,
                """
                SELECT lifecycle_state, lifecycle_version, updated_at FROM incident_projections
                WHERE tenant_id=:tenant AND incident_id=:incident LIMIT 1
            """,
                params,
            )
    finally:
        await engine.dispose()

    active = int((requirement or {}).get("active") or 0)
    accepted = int((evidence or {}).get("total") or 0)
    return [
        (
            "Incident",
            "PASS" if incident else "FAIL",
            incident_id if incident else "-",
            "-" if incident else "NOT_FOUND",
        ),
        (
            "Requirements",
            "PASS" if requirement and int(requirement.get("total") or 0) else "BLOCKED",
            f"{active} active",
            "-" if requirement and int(requirement.get("total") or 0) else "NO_REQUIREMENTS",
        ),
        (
            "Connector job",
            "PASS" if job and job["status"] == "collected" else "BLOCKED",
            f"attempt-{job['attempt_count']}" if job else "-",
            str(job.get("last_error") or "-")[:80] if job else "NO_JOB",
        ),
        (
            "Accepted evidence",
            "PASS" if accepted else "FAIL",
            f"{accepted} records",
            "-" if accepted else str((rejection or {}).get("reason_code") or "NO_ACCEPTED_EVIDENCE"),
        ),
        (
            "Context snapshot",
            "PASS" if snapshot else "BLOCKED",
            f"v{snapshot['snapshot_version']} {snapshot['snapshot_id']}" if snapshot else "-",
            "-" if snapshot else "NO_SNAPSHOT",
        ),
        (
            "Investigation",
            "PASS" if investigation and investigation["status"] == "current" else "BLOCKED",
            f"RCA v{investigation['rca_version']}" if investigation else "-",
            "-" if investigation and investigation["status"] == "current" else "RCA_NOT_CURRENT",
        ),
        (
            "Resolution",
            "PASS" if resolution else "BLOCKED",
            f"plan v{resolution['plan_version']}" if resolution else "-",
            "-" if resolution else "RCA_NOT_READY",
        ),
        (
            "Approval",
            "PASS" if approval and approval["decision"] == "approved" else "BLOCKED",
            str(approval["id"]) if approval else "-",
            "-" if approval else "PLAN_NOT_READY",
        ),
        (
            "UI projection",
            "PASS" if projection else "STALE",
            f"v{projection['lifecycle_version']} updated_at={projection['updated_at']}" if projection else "-",
            "-" if projection else "JOB_NOT_PROJECTED",
        ),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--incident-id", required=True)
    args = parser.parse_args()
    UUID(args.incident_id)
    rows = asyncio.run(diagnose(args.tenant_id.strip(), args.incident_id))
    print(f"{'Stage':<23} {'Status':<10} {'Identity/version':<42} Failure")
    for stage, status, identity, failure in rows:
        print(f"{stage:<23} {status:<10} {identity:<42} {failure}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
