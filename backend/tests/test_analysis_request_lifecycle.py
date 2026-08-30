from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from common.repository import IncidentRepository


@pytest.mark.asyncio
async def test_active_analysis_requests_coalesce_per_incident(sqlite_session_factory) -> None:
    tenant_id = "tenant-a"
    incident_id = uuid4()
    first_request_id = uuid4()
    async with sqlite_session_factory() as session:
        repository = IncidentRepository(session)
        first, first_created = await repository.create_or_reuse_analysis_request(
            request_id=first_request_id,
            tenant_id=tenant_id,
            incident_id=incident_id,
            alert_id=uuid4(),
            expected_recommendation_id=uuid4(),
            mode="fresh",
        )
        second, second_created = await repository.create_or_reuse_analysis_request(
            request_id=uuid4(),
            tenant_id=tenant_id,
            incident_id=incident_id,
            alert_id=uuid4(),
            expected_recommendation_id=uuid4(),
            mode="fresh",
        )
        await session.commit()

    assert first_created is True
    assert second_created is False
    assert second.request_id == first_request_id


@pytest.mark.asyncio
async def test_terminal_request_allows_a_new_analysis(sqlite_session_factory) -> None:
    tenant_id = "tenant-a"
    incident_id = uuid4()
    async with sqlite_session_factory() as session:
        repository = IncidentRepository(session)
        first, _ = await repository.create_or_reuse_analysis_request(
            request_id=uuid4(), tenant_id=tenant_id, incident_id=incident_id,
            alert_id=uuid4(), expected_recommendation_id=uuid4(), mode="fresh",
        )
        first.status = "complete"
        second, created = await repository.create_or_reuse_analysis_request(
            request_id=uuid4(), tenant_id=tenant_id, incident_id=incident_id,
            alert_id=uuid4(), expected_recommendation_id=uuid4(), mode="fresh",
        )
        await session.commit()

    assert created is True
    assert second.request_id != first.request_id


@pytest.mark.asyncio
async def test_analysis_failure_is_terminal_and_retryable(sqlite_session_factory) -> None:
    request_id = uuid4()
    async with sqlite_session_factory() as session:
        repository = IncidentRepository(session)
        row, _ = await repository.create_or_reuse_analysis_request(
            request_id=request_id, tenant_id="tenant-a", incident_id=uuid4(),
            alert_id=uuid4(), expected_recommendation_id=uuid4(), mode="fresh",
        )
        changed = await repository.fail_analysis_request(
            request_id, tenant_id="tenant-a", reason="context connector contract failed",
        )
        await session.commit()

    assert changed is True
    assert row.status == "failed"
    assert row.terminal_reason == "context connector contract failed"
    assert row.completed_at is not None


@pytest.mark.asyncio
async def test_expired_analysis_stops_polling(sqlite_session_factory) -> None:
    now = datetime.now(UTC)
    async with sqlite_session_factory() as session:
        repository = IncidentRepository(session)
        row, _ = await repository.create_or_reuse_analysis_request(
            request_id=uuid4(), tenant_id="tenant-a", incident_id=uuid4(),
            alert_id=uuid4(), expected_recommendation_id=uuid4(), mode="fresh",
        )
        row.status = "published"
        row.expires_at = now - timedelta(seconds=1)
        changed = await repository.expire_analysis_request(row, now=now)
        await session.commit()

    assert changed is True
    assert row.status == "timed_out"
    assert row.terminal_reason == "analysis_deadline_exceeded"
