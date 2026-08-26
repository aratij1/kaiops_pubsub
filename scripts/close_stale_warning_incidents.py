from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from common.config import get_settings
from common.database import (
    AuditLogRecord,
    IncidentProjectionRecord,
    IncidentRecord,
    PendingWorkflowRecord,
    create_engine,
    create_session_factory,
)
from common.repository import IncidentRepository


async def close_stale_warnings(*, apply: bool) -> int:
    engine = create_engine(get_settings())
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            result = await session.execute(
                select(IncidentProjectionRecord).where(
                    IncidentProjectionRecord.severity == "warning",
                    IncidentProjectionRecord.status == "remediating",
                )
            )
            rows = list(result.scalars().all())
            print(f"MATCHED={len(rows)}")
            if not apply or not rows:
                return len(rows)

            now = datetime.now(timezone.utc)
            repository = IncidentRepository(session)
            incident_ids: list[str] = []
            for row in rows:
                incident_id = str(row.incident_id)
                incident_ids.append(incident_id)
                await repository.save_incident_event(
                    {
                        "event_id": str(uuid4()),
                        "event_type": "incident.closed",
                        "produced_at": now.isoformat(),
                        "identity": {
                            "incident_id": incident_id,
                            "alert_id": str(row.alert_id) if row.alert_id else None,
                            "trace_id": row.trace_id,
                        },
                        "scope": {
                            "tenant_id": row.tenant_id or "default",
                            "service": row.service or "unknown",
                            "environment": row.environment or "prod",
                        },
                        "state": {"severity": row.severity or "warning", "status": "closed"},
                        "policy": {
                            "risk_tier": row.risk_tier,
                            "execution_mode": row.execution_mode,
                            "requires_approval": row.requires_approval,
                            "policy_version": row.policy_version,
                            "policy_reason": "Administrative closure of stale warning remediation",
                        },
                        "transport": {
                            "provider": row.transport_provider or "rabbitmq",
                            "channel": "administrative-closure",
                        },
                        "payload": {
                            "health_restored": True,
                            "alerts_cleared": True,
                            "closure_reason": "Stale warning incident manually closed; no active execution was present.",
                            "closed_at": now.isoformat(),
                        },
                    }
                )

                incident = await session.get(IncidentRecord, row.incident_id)
                if incident:
                    incident.status = "closed"
                    incident.payload = {
                        **(incident.payload or {}),
                        "status": "closed",
                        "closed_at": now.isoformat(),
                        "closure_reason": "Administrative closure of stale warning remediation",
                    }

                pending = await session.get(PendingWorkflowRecord, row.incident_id)
                if pending and pending.status not in {"completed", "cancelled"}:
                    pending.status = "cancelled"
                    pending.completed_at = now
                    pending.completed_payload = {
                        "reason": "Incident administratively closed as stale warning"
                    }

            session.add(
                AuditLogRecord(
                    actor="admin",
                    action="bulk_close_stale_warning_incidents",
                    resource_type="incident",
                    resource_id="warning:remediating",
                    payload={
                        "count": len(incident_ids),
                        "incident_ids": incident_ids,
                        "reason": "Warnings remained in remediating without active execution",
                    },
                )
            )
            await session.commit()
            print(f"CLOSED={len(incident_ids)}")
            return len(incident_ids)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Persist closure events and status changes")
    args = parser.parse_args()
    asyncio.run(close_stale_warnings(apply=args.apply))


if __name__ == "__main__":
    main()
