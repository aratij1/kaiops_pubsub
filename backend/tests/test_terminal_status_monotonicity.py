from __future__ import annotations

from uuid import uuid4

import pytest
from common.database import IncidentProjectionRecord
from common.event_publishers import build_event_envelope
from common.models import Incident, IncidentStatus, RemediationAction, RemediationStatus, ResolutionReport
from common.repository import IncidentRepository


def _event(*, incident_id: str, status: str, event_type: str) -> dict:
    return build_event_envelope(
        event_type=event_type,
        identity={"incident_id": incident_id, "alert_id": None, "trace_id": "trace-terminal"},
        scope={"tenant_id": "tenant-a", "service": "checkout", "environment": "prod"},
        state={"severity": "warning", "status": status, "owner": None},
        policy={"risk_tier": "low", "execution_mode": "diagnostic", "requires_approval": False},
        transport={"provider": "test", "channel": "test"},
        payload={"status": status},
    )


@pytest.mark.asyncio
async def test_stale_incident_write_cannot_reopen_closed_incident(sqlite_session_factory) -> None:
    incident_id = uuid4()
    async with sqlite_session_factory() as session:
        repo = IncidentRepository(session)
        await repo.save_incident(Incident(
            id=incident_id,
            service="checkout",
            title="Checkout alert",
            status=IncidentStatus.CLOSED,
        ))
        await session.commit()

    async with sqlite_session_factory() as session:
        repo = IncidentRepository(session)
        await repo.save_incident(Incident(
            id=incident_id,
            service="checkout",
            title="Stale pre-closure copy",
            ticket_id="KAN-100",
            status=IncidentStatus.INVESTIGATING,
        ))
        await session.commit()

    async with sqlite_session_factory() as session:
        stored = await IncidentRepository(session).get_incident(str(incident_id))

    assert stored is not None
    assert stored["status"] == "closed"
    assert stored["ticket_id"] == "KAN-100"
    assert stored["title"] == "Checkout alert"


@pytest.mark.asyncio
async def test_late_action_and_event_cannot_regress_closed_projection(sqlite_session_factory) -> None:
    incident_id = uuid4()
    async with sqlite_session_factory() as session:
        repo = IncidentRepository(session)
        await repo.save_incident_event(_event(
            incident_id=str(incident_id),
            status="closed",
            event_type="incident.closure.completed",
        ))
        await repo.save_action(RemediationAction(
            tenant_id="tenant-a",
            incident_id=incident_id,
            action_type="diagnostic_completion",
            target="checkout",
            status=RemediationStatus.SKIPPED,
            parameters={"diagnostic_closure": True},
        ))
        await repo.save_incident_event(_event(
            incident_id=str(incident_id),
            status="investigating",
            event_type="incident.alert.enriched",
        ))
        await session.commit()

    async with sqlite_session_factory() as session:
        projection = await session.get(IncidentProjectionRecord, incident_id)

    assert projection is not None
    assert projection.status == "closed"
    assert projection.latest_event_type == "incident.closure.completed"


@pytest.mark.asyncio
async def test_diagnostic_stage_summary_omits_inapplicable_approval(sqlite_session_factory) -> None:
    incident_id = uuid4()
    event_types = (
        "incident.alert.enriched",
        "incident.workflow.selected",
        "incident.context.collected",
        "incident.recommendation.generated",
        "incident.remediation.executed",
        "incident.closure.completed",
    )
    async with sqlite_session_factory() as session:
        repo = IncidentRepository(session)
        await repo.save_incident(Incident(
            id=incident_id,
            tenant_id="tenant-a",
            service="checkout",
            title="Diagnostic checkout alert",
            status=IncidentStatus.CLOSED,
        ))
        for event_type in event_types:
            await repo.save_incident_event(_event(
                incident_id=str(incident_id),
                status="closed" if event_type == "incident.closure.completed" else "investigating",
                event_type=event_type,
            ))
        await repo.save_action(RemediationAction(
            tenant_id="tenant-a",
            incident_id=incident_id,
            action_type="diagnostic_completion",
            target="checkout",
            status=RemediationStatus.SKIPPED,
            parameters={"diagnostic_closure": True},
        ))
        await session.commit()

    async with sqlite_session_factory() as session:
        summary = await IncidentRepository(session).get_incident_stage_completeness(
            str(incident_id),
            tenant_id="tenant-a",
        )

    assert summary is not None
    assert summary["status"] == "closed"
    assert summary["stage_completion"] == {
        "completed": 6,
        "total": 6,
        "percentage": 100.0,
        "missing": [],
    }
    assert "approval_recorded" not in {stage["stage"] for stage in summary["stages"]}


@pytest.mark.asyncio
async def test_manual_closure_summary_omits_inapplicable_control_phases(sqlite_session_factory) -> None:
    incident_id = uuid4()
    event_types = (
        "incident.alert.enriched",
        "incident.workflow.selected",
        "incident.context.collected",
        "incident.recommendation.generated",
        "incident.closure.completed",
    )
    async with sqlite_session_factory() as session:
        repo = IncidentRepository(session)
        await repo.save_incident(Incident(
            id=incident_id,
            tenant_id="tenant-a",
            service="checkout",
            title="Manually reviewed checkout alert",
            status=IncidentStatus.CLOSED,
        ))
        for event_type in event_types:
            await repo.save_incident_event(_event(
                incident_id=str(incident_id),
                status="closed" if event_type == "incident.closure.completed" else "investigating",
                event_type=event_type,
            ))
        await repo.save_report(ResolutionReport(
            tenant_id="tenant-a",
            incident_id=incident_id,
            root_cause="Operator-directed closure",
            impact="Reviewed by the incident commander",
            action_taken="Administrative closure",
            metadata={"closure_kind": "manual", "technical_recovery_verified": False},
        ))
        await session.commit()

    async with sqlite_session_factory() as session:
        summary = await IncidentRepository(session).get_incident_stage_completeness(
            str(incident_id),
            tenant_id="tenant-a",
        )

    assert summary is not None
    assert summary["status"] == "closed"
    assert "administratively closed" in summary["status_reason"]
    assert "without a technical recovery claim" in summary["status_reason"]
    assert summary["stage_completion"] == {
        "completed": 5,
        "total": 5,
        "percentage": 100.0,
        "missing": [],
    }
    stage_names = {stage["stage"] for stage in summary["stages"]}
    assert "approval_recorded" not in stage_names
    assert "remediation_executed" not in stage_names
