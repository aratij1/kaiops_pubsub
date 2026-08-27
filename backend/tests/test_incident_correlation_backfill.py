from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from common.correlation_backfill import LEGACY_PROJECT, backfill_incident_correlations
from common.database import (
    AlertRecord,
    IncidentCorrelationBackfillRecord,
    IncidentCorrelationOwnershipRecord,
    IncidentOccurrenceRecord,
    IncidentRecord,
)
from sqlalchemy import func, select


@pytest.mark.asyncio
async def test_backfill_is_dry_run_by_default_then_idempotent(sqlite_session_factory) -> None:
    alert_id = uuid4()
    incident_id = uuid4()
    now = datetime.now(UTC)
    async with sqlite_session_factory() as session:
        session.add(AlertRecord(
            id=alert_id,
            tenant_id="tenant-a",
            source="prometheus",
            name="Checkout errors",
            service="checkout",
            environment="prod",
            severity="critical",
            fingerprint="checkout-errors",
            payload={},
        ))
        session.add(IncidentRecord(
            id=incident_id,
            tenant_id="tenant-a",
            service="checkout",
            environment="prod",
            severity="critical",
            status="investigating",
            title="Checkout errors",
            payload={
                "id": str(incident_id),
                "alert_ids": [str(alert_id)],
                "fingerprint": "checkout-errors",
                "project_id": "commerce",
            },
            created_at=now,
            updated_at=now,
        ))
        await session.commit()

    async with sqlite_session_factory() as session:
        dry_run = await backfill_incident_correlations(session, dry_run=True)
        assert dry_run.acquired == 1
        assert await session.scalar(select(func.count()).select_from(IncidentCorrelationOwnershipRecord)) == 0

    async with sqlite_session_factory() as session:
        first = await backfill_incident_correlations(session, dry_run=False)
    async with sqlite_session_factory() as session:
        second = await backfill_incident_correlations(session, dry_run=False)
        owner = await session.scalar(select(IncidentCorrelationOwnershipRecord))
        ledger = await session.scalar(select(IncidentCorrelationBackfillRecord))

    assert first.acquired == first.occurrences_created == 1
    assert first.incident_count == first.ownership_count == 1
    assert first.unreconciled_count == first.duplicate_ownership_count == 0
    assert second.already_owned == 1
    assert owner is not None and owner.project_id == "commerce"
    assert ledger is not None and ledger.status == "reconciled"


@pytest.mark.asyncio
async def test_backfill_retains_unscoped_terminal_incident_for_review(sqlite_session_factory) -> None:
    incident_id = uuid4()
    now = datetime.now(UTC)
    async with sqlite_session_factory() as session:
        session.add(IncidentRecord(
            id=incident_id,
            tenant_id="tenant-a",
            service="checkout",
            environment="prod",
            severity="warning",
            status="closed",
            title="Historical incident",
            payload={"id": str(incident_id)},
            created_at=now,
            updated_at=now,
        ))
        await session.commit()

    async with sqlite_session_factory() as session:
        result = await backfill_incident_correlations(session, dry_run=False)
    async with sqlite_session_factory() as session:
        owner = await session.scalar(select(IncidentCorrelationOwnershipRecord))
        ledger = await session.scalar(select(IncidentCorrelationBackfillRecord))
        occurrence_count = await session.scalar(select(func.count()).select_from(IncidentOccurrenceRecord))

    assert result.needs_scope_review == 1
    assert owner is not None and owner.project_id == LEGACY_PROJECT
    assert owner.lifecycle_state == "closed"
    assert owner.correlation_window_expires_at == owner.first_seen_at
    assert ledger is not None and ledger.needs_scope_review is True
    assert occurrence_count == 0
