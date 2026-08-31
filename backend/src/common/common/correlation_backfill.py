from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from common.database import (
    AlertRecord,
    IncidentCorrelationBackfillRecord,
    IncidentCorrelationOwnershipRecord,
    IncidentOccurrenceRecord,
    IncidentRecord,
)

BACKFILL_VERSION = "canonical-correlation-v1"
LEGACY_PROJECT = "legacy-unassigned"
TERMINAL_STATES = {"closed", "resolved", "cancelled", "canceled"}


@dataclass
class BackfillReport:
    scanned: int = 0
    acquired: int = 0
    already_owned: int = 0
    occurrences_created: int = 0
    needs_scope_review: int = 0
    exceptions: int = 0
    dry_run: bool = True
    resume_cursor: str | None = None
    incident_count: int = 0
    ownership_count: int = 0
    unreconciled_count: int = 0
    duplicate_ownership_count: int = 0

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)


def _payload_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def authoritative_identity(record: IncidentRecord) -> tuple[str, str, bool]:
    payload = _payload_dict(record.payload)
    metadata = _payload_dict(payload.get("metadata"))
    canonical = _payload_dict(metadata.get("canonical_correlation"))
    project_id = str(canonical.get("project_id") or payload.get("project_id") or "").strip()
    needs_scope_review = not bool(project_id)
    if needs_scope_review:
        project_id = LEGACY_PROJECT
    correlation_key = str(
        canonical.get("correlation_key")
        or payload.get("fingerprint")
        or payload.get("correlation_id")
        or f"legacy-incident:{record.id}"
    ).strip()
    return project_id, correlation_key, needs_scope_review


def _aware(value: datetime | None) -> datetime:
    result = value or datetime.now(UTC)
    return result.replace(tzinfo=UTC) if result.tzinfo is None else result


async def backfill_incident_correlations(
    session: AsyncSession,
    *,
    batch_size: int = 100,
    resume_cursor: str | None = None,
    dry_run: bool = True,
) -> BackfillReport:
    """Expand/backfill one restartable batch without mutating incident history."""
    report = BackfillReport(dry_run=dry_run)
    query = select(IncidentRecord).order_by(IncidentRecord.id).limit(max(1, min(batch_size, 1000)))
    if resume_cursor:
        query = query.where(IncidentRecord.id > UUID(resume_cursor))
    incidents = list((await session.execute(query)).scalars().all())
    for incident in incidents:
        report.scanned += 1
        report.resume_cursor = str(incident.id)
        tenant_id = str(incident.tenant_id or "").strip()
        service = str(incident.service or "").strip()
        environment = str(incident.environment or "").strip()
        if not all((tenant_id, service, environment)):
            report.exceptions += 1
            continue
        project_id, correlation_key, needs_scope_review = authoritative_identity(incident)
        report.needs_scope_review += int(needs_scope_review)
        existing = await session.scalar(
            select(IncidentCorrelationOwnershipRecord).where(
                IncidentCorrelationOwnershipRecord.tenant_id == tenant_id,
                IncidentCorrelationOwnershipRecord.canonical_incident_id == incident.id,
            )
        )
        if existing is not None:
            report.already_owned += 1
            continue
        family_id = uuid5(
            NAMESPACE_URL,
            f"kaims-backfill:{tenant_id}:{project_id}:{environment}:{service}:{correlation_key}:{incident.id}",
        )
        observed_at = _aware(incident.created_at)
        lifecycle = str(incident.status or "open").strip().lower()
        if not dry_run:
            ownership = IncidentCorrelationOwnershipRecord(
                tenant_id=tenant_id,
                project_id=project_id,
                environment=environment,
                service=service,
                correlation_key=correlation_key,
                correlation_family_id=family_id,
                correlation_generation=1,
                canonical_incident_id=incident.id,
                first_seen_at=observed_at,
                last_seen_at=_aware(incident.updated_at),
                correlation_window_expires_at=(
                    observed_at if lifecycle in TERMINAL_STATES else observed_at + timedelta(minutes=60)
                ),
                lifecycle_state=lifecycle,
                version=1,
            )
            session.add(ownership)
            session.add(IncidentCorrelationBackfillRecord(
                incident_id=incident.id,
                tenant_id=tenant_id,
                backfill_version=BACKFILL_VERSION,
                source="incidents",
                status="needs_scope_review" if needs_scope_review else "reconciled",
                reason=(
                    "authoritative project unavailable; retained under tenant-scoped legacy project"
                    if needs_scope_review else "authoritative persisted scope backfilled"
                ),
                project_id=project_id,
                needs_scope_review=needs_scope_review,
                correlation_family_id=family_id,
                correlation_generation=1,
            ))
            await session.flush()
            payload = _payload_dict(incident.payload)
            alert_ids = payload.get("alert_ids") if isinstance(payload.get("alert_ids"), list) else []
            for raw_alert_id in alert_ids:
                try:
                    alert_id = UUID(str(raw_alert_id))
                except ValueError:
                    report.exceptions += 1
                    continue
                alert = await session.scalar(select(AlertRecord).where(
                    AlertRecord.id == alert_id,
                    AlertRecord.tenant_id == tenant_id,
                ))
                if alert is None:
                    report.exceptions += 1
                    continue
                exists = await session.scalar(select(func.count()).select_from(IncidentOccurrenceRecord).where(
                    IncidentOccurrenceRecord.tenant_id == tenant_id,
                    IncidentOccurrenceRecord.idempotency_key == f"backfill-alert:{alert_id}",
                ))
                if exists:
                    continue
                session.add(IncidentOccurrenceRecord(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    environment=environment,
                    service=service,
                    correlation_family_id=family_id,
                    correlation_generation=1,
                    canonical_incident_id=incident.id,
                    occurrence_id=alert_id,
                    idempotency_key=f"backfill-alert:{alert_id}",
                    causation_id=str(alert.correlation_id or "") or None,
                    payload={"backfill_version": BACKFILL_VERSION},
                    observed_at=_aware(alert.created_at),
                ))
                report.occurrences_created += 1
        report.acquired += 1
    if not dry_run:
        await session.commit()
    report.incident_count = int((await session.scalar(
        select(func.count()).select_from(IncidentRecord)
    )) or 0)
    report.ownership_count = int((await session.scalar(
        select(func.count(func.distinct(IncidentCorrelationOwnershipRecord.canonical_incident_id)))
    )) or 0)
    report.unreconciled_count = max(0, report.incident_count - report.ownership_count)
    duplicate_rows = await session.execute(
        select(IncidentCorrelationOwnershipRecord.canonical_incident_id)
        .group_by(IncidentCorrelationOwnershipRecord.canonical_incident_id)
        .having(func.count(IncidentCorrelationOwnershipRecord.id) > 1)
    )
    report.duplicate_ownership_count = len(list(duplicate_rows.scalars().all()))
    return report
