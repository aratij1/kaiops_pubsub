"""IncidentRepository.list_lowest_confidence_recommendations.

Backs the Copilot "explain the lowest-confidence RCA" question when it
arrives with no incident ID: the repository must find the lowest-confidence
incident.recommendation.generated event itself.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from common.database import IncidentEventRecord
from common.repository import IncidentRepository


def make_event(
    *,
    incident_id,
    event_type: str = "incident.recommendation.generated",
    confidence: float | None,
    tenant_id: str = "default",
    service: str = "checkout",
) -> IncidentEventRecord:
    return IncidentEventRecord(
        id=uuid4(),
        incident_id=incident_id,
        tenant_id=tenant_id,
        service=service,
        environment="prod",
        event_type=event_type,
        event_stage="completed",
        confidence=confidence,
        transport_provider="rabbitmq",
        transport_channel="incident-events",
    )


@pytest.mark.asyncio
async def test_list_lowest_confidence_recommendations_orders_ascending(sqlite_session_factory) -> None:
    low = uuid4()
    mid = uuid4()
    high = uuid4()

    async with sqlite_session_factory() as session:
        session.add_all(
            [
                make_event(incident_id=high, confidence=0.91),
                make_event(incident_id=low, confidence=0.12),
                make_event(incident_id=mid, confidence=0.55),
            ]
        )
        await session.commit()

    async with sqlite_session_factory() as session:
        repo = IncidentRepository(session)
        rows = await repo.list_lowest_confidence_recommendations()

    assert [row["incident_id"] for row in rows] == [str(low), str(mid), str(high)]
    assert rows[0]["confidence"] == pytest.approx(0.12)


@pytest.mark.asyncio
async def test_list_lowest_confidence_recommendations_excludes_other_event_types_and_null_confidence(
    sqlite_session_factory,
) -> None:
    keep = uuid4()
    wrong_type = uuid4()
    no_confidence = uuid4()

    async with sqlite_session_factory() as session:
        session.add_all(
            [
                make_event(incident_id=keep, confidence=0.3),
                make_event(incident_id=wrong_type, event_type="incident.created", confidence=0.01),
                make_event(incident_id=no_confidence, confidence=None),
            ]
        )
        await session.commit()

    async with sqlite_session_factory() as session:
        repo = IncidentRepository(session)
        rows = await repo.list_lowest_confidence_recommendations()

    assert [row["incident_id"] for row in rows] == [str(keep)]


@pytest.mark.asyncio
async def test_list_lowest_confidence_recommendations_scopes_by_tenant(sqlite_session_factory) -> None:
    tenant_a_incident = uuid4()
    tenant_b_incident = uuid4()

    async with sqlite_session_factory() as session:
        session.add_all(
            [
                make_event(incident_id=tenant_a_incident, confidence=0.4, tenant_id="tenant-a"),
                make_event(incident_id=tenant_b_incident, confidence=0.05, tenant_id="tenant-b"),
            ]
        )
        await session.commit()

    async with sqlite_session_factory() as session:
        repo = IncidentRepository(session)
        rows = await repo.list_lowest_confidence_recommendations(tenant_id="tenant-a")

    assert [row["incident_id"] for row in rows] == [str(tenant_a_incident)]


@pytest.mark.asyncio
async def test_list_lowest_confidence_recommendations_respects_limit(sqlite_session_factory) -> None:
    async with sqlite_session_factory() as session:
        session.add_all([make_event(incident_id=uuid4(), confidence=c) for c in (0.1, 0.2, 0.3, 0.4, 0.5)])
        await session.commit()

    async with sqlite_session_factory() as session:
        repo = IncidentRepository(session)
        rows = await repo.list_lowest_confidence_recommendations(limit=2)

    assert len(rows) == 2
    assert rows[0]["confidence"] == pytest.approx(0.1)
    assert rows[1]["confidence"] == pytest.approx(0.2)
