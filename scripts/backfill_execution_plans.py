"""Backfill catalog-governed execution plans for persisted alert incidents.

Dry-run is the default. ``--execute`` updates the latest recommendation audit
and incident projection atomically. Historical approvals and remediation
actions remain immutable; the projection is marked as requiring renewed
approval whenever the plan fingerprint changes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from sqlalchemy import select

from common.config import get_settings
from common.database import AlertRecord, AuditLogRecord, IncidentProjectionRecord, create_engine, create_session_factory
from common.models import Alert
from common.orchestration.execution_plan import resolve_execution_plan
import common.orchestration.execution_plan as execution_plan_module

# Older running service images may predate the module-level cache. Backfills
# resolve thousands of alerts in one process, so guarantee one catalog load
# without requiring a control-plane restart merely to run this migration.
execution_plan_module._execution_catalogs = lru_cache(maxsize=1)(execution_plan_module._execution_catalogs)


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _alert_from_record(row: AlertRecord) -> Alert:
    payload = _dict(row.payload)
    return Alert.model_validate(
        {
            **payload,
            "id": str(row.id),
            "tenant_id": row.tenant_id or "default",
            "source": row.source or payload.get("source") or "unknown",
            "name": row.name or payload.get("name") or "Unnamed alert",
            "service": row.service or payload.get("service") or "unknown",
            "environment": row.environment or payload.get("environment") or "prod",
            "severity": row.severity or payload.get("severity") or "warning",
            "description": payload.get("description") or payload.get("summary") or row.name or "No description supplied",
            "fingerprint": row.fingerprint or payload.get("fingerprint"),
            "correlation_id": row.correlation_id or payload.get("correlation_id"),
        }
    )


def _apply_plan_to_recommendation(payload: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    updated = {**payload}
    metadata = _dict(updated.get("metadata"))
    previous = _dict(metadata.get("execution_plan"))
    if previous and previous.get("plan_fingerprint") != plan.get("plan_fingerprint"):
        metadata["superseded_execution_plan"] = {
            "plan_fingerprint": previous.get("plan_fingerprint"),
            "schema_version": previous.get("schema_version"),
        }
    metadata["execution_plan"] = plan
    metadata["recommended_commands"] = list(plan.get("commands") or [])
    metadata["remediation_target"] = str(plan.get("remediation_target") or "")
    metadata["execution_plan_backfilled_at"] = datetime.now(UTC).isoformat()
    metadata["approval_requires_renewal"] = previous.get("plan_fingerprint") != plan.get("plan_fingerprint")
    updated["metadata"] = metadata
    updated["commands"] = list(plan.get("commands") or [])
    return updated


async def backfill(*, execute: bool, limit: int | None) -> dict[str, Any]:
    engine = create_engine(get_settings())
    sessions = create_session_factory(engine)
    counts: Counter[str] = Counter()
    playbooks: Counter[str] = Counter()
    async with sessions() as session:
        projection_statement = select(IncidentProjectionRecord).where(IncidentProjectionRecord.alert_id.is_not(None))
        if limit:
            projection_statement = projection_statement.limit(limit)
        projection_rows = list((await session.scalars(projection_statement)).all())
        print(json.dumps({"progress": "projections_loaded", "count": len(projection_rows)}), flush=True)
        projections = {str(row.alert_id): row for row in projection_rows}
        alert_ids = [row.alert_id for row in projection_rows if row.alert_id is not None]
        alerts = list((await session.scalars(select(AlertRecord).where(AlertRecord.id.in_(alert_ids)))).all()) if alert_ids else []
        print(json.dumps({"progress": "alerts_loaded", "count": len(alerts)}), flush=True)
        # Load recommendation rows once. The former per-alert lookup turned a
        # large backfill into N+1 database traffic and could hold a transaction
        # open for hours on a production-sized alert history.
        recommendation_ids = [row.recommendation_id for row in projection_rows if row.recommendation_id is not None]
        audits_by_id: dict[str, AuditLogRecord] = {}
        audit_rows = (
            await session.scalars(
                select(AuditLogRecord)
                .where(AuditLogRecord.id.in_(recommendation_ids))
            )
        ).all()
        print(json.dumps({"progress": "recommendations_loaded", "count": len(audit_rows)}), flush=True)
        for audit_row in audit_rows:
            audits_by_id[str(audit_row.id)] = audit_row

        for alert_row in alerts:
            counts["alerts_scanned"] += 1
            projection = projections.get(str(alert_row.id))
            alert = _alert_from_record(alert_row)
            plan = resolve_execution_plan(
                alert=alert,
                workflow_name=str(projection.execution_mode or "existing-alert-backfill"),
                requires_approval=bool(projection.requires_approval if projection.requires_approval is not None else True),
                risk_tier=str(projection.risk_tier or "medium"),
                execution_mode=str(projection.execution_mode or "human-approval"),
            )
            playbooks[str(_dict(plan.get("playbook")).get("id") or "unknown")] += 1
            counts["execution_ready" if plan.get("execution_ready") else "diagnostic_only"] += 1

            audit = audits_by_id.get(str(projection.recommendation_id))
            if audit is None:
                counts["without_recommendation"] += 1
                continue

            old_payload = _dict(audit.payload)
            old_plan = _dict(_dict(old_payload.get("metadata")).get("execution_plan"))
            changed = old_plan.get("plan_fingerprint") != plan.get("plan_fingerprint")
            counts["changed" if changed else "unchanged"] += 1
            if not execute:
                continue

            audit.payload = _apply_plan_to_recommendation(old_payload, plan)
            projection_payload = _dict(projection.projection_payload)
            recommendation = _dict(projection_payload.get("recommendation"))
            projection_payload["recommendation"] = _apply_plan_to_recommendation(recommendation or old_payload, plan)
            decision = _dict(projection_payload.get("decision"))
            decision["execution_plan"] = plan
            projection_payload["decision"] = decision
            projection_payload["execution_plan_fingerprint"] = plan.get("plan_fingerprint")
            projection_payload["approval_requires_renewal"] = changed
            projection.projection_payload = projection_payload
            counts["updated"] += 1

            if counts["alerts_scanned"] % 500 == 0:
                print(json.dumps({"progress": "plans_resolved", "count": counts["alerts_scanned"]}), flush=True)

        counts["projection_without_alert"] = max(0, len(projection_rows) - len(alerts))

        if execute:
            await session.commit()
        else:
            await session.rollback()
    await engine.dispose()
    return {
        **dict(sorted(counts.items())),
        "dry_run": not execute,
        "playbooks": dict(playbooks.most_common()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Persist changes; default is report-only")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(backfill(execute=args.execute, limit=args.limit)), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
