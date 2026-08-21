"""A query scoped to one tenant must never return another tenant's rows.

Covers the core alert/incident data model (schema-level tenant_id added in
backend/database/migrations/20260806_core_tenant_isolation.sql) and the
alert-intelligence correlation candidate pool, which must not let a
tenant-A alert correlate against tenant-B's history.
"""

from __future__ import annotations

import pytest
from alert_intelligence import AlertIntelligenceAgent
from common.models import Alert, AlertSeverity, Incident, RemediationAction, RemediationStatus, ResolutionReport
from common.repository import IncidentRepository
from common.repository_interfaces import SqlAlertHistoryRepository


def make_alert(tenant_id: str, service: str = "payments", environment: str = "prod") -> Alert:
    return Alert(
        tenant_id=tenant_id,
        source="prometheus",
        name="PaymentLatencyHigh",
        service=service,
        environment=environment,
        severity=AlertSeverity.WARNING,
        description="payment latency above threshold",
        labels={"deployment": "payments-api"},
    )


@pytest.mark.asyncio
async def test_list_alerts_source_balanced_scopes_by_tenant(sqlite_session_factory) -> None:
    async with sqlite_session_factory() as session:
        repo = IncidentRepository(session)
        await repo.save_alert(make_alert("tenant-a"))
        await repo.save_alert(make_alert("tenant-b"))
        await session.commit()

    async with sqlite_session_factory() as session:
        repo = IncidentRepository(session)
        tenant_a_rows = await repo.list_alerts_source_balanced(limit=10, tenant_id="tenant-a")
        tenant_b_rows = await repo.list_alerts_source_balanced(limit=10, tenant_id="tenant-b")
        unscoped_rows = await repo.list_alerts_source_balanced(limit=10)

    assert len(tenant_a_rows) == 1
    assert all(row.get("tenant_id") == "tenant-a" for row in tenant_a_rows)
    assert len(tenant_b_rows) == 1
    assert all(row.get("tenant_id") == "tenant-b" for row in tenant_b_rows)
    # No tenant filter is an explicit opt-in for internal/trusted callers only.
    assert len(unscoped_rows) == 2


@pytest.mark.asyncio
async def test_alert_correlation_candidate_pool_is_tenant_scoped(sqlite_session_factory) -> None:
    repository = SqlAlertHistoryRepository(session_factory=sqlite_session_factory, max_items=100)
    agent = AlertIntelligenceAgent(alert_history_repository=repository, correlation_threshold=0.2)

    tenant_a_first, _ = await agent.process(make_alert("tenant-a"))
    tenant_b_alert, _ = await agent.process(make_alert("tenant-b"))

    # Same service/environment/description as tenant_a_first, but a different
    # tenant: must never correlate or count toward dedup, even though the
    # correlation score would otherwise be a near-perfect match.
    assert tenant_b_alert.correlation_id != tenant_a_first.correlation_id
    assert tenant_b_alert.deduplicated_count == 1


@pytest.mark.asyncio
async def test_actions_table_tenant_id_persists_and_is_isolated(sqlite_session_factory) -> None:
    async with sqlite_session_factory() as session:
        repo = IncidentRepository(session)
        incident = Incident(tenant_id="tenant-a", service="payments", title="test incident")
        await repo.save_incident(incident)
        action = RemediationAction(
            tenant_id="tenant-a",
            incident_id=incident.id,
            action_type="rollback_deployment",
            target="payments",
            status=RemediationStatus.SUCCEEDED,
        )
        await repo.save_action(action)
        await session.commit()

    async with sqlite_session_factory() as session:
        from common.database import ActionRecord
        from sqlalchemy import select

        rows = (await session.execute(select(ActionRecord))).scalars().all()

    assert len(rows) == 1
    assert rows[0].tenant_id == "tenant-a"


@pytest.mark.asyncio
async def test_resolution_report_and_observations_persist_non_default_tenant(sqlite_session_factory) -> None:
    incident = Incident(tenant_id="tenant-a", service="payments", title="tenant report test")
    report = ResolutionReport(
        tenant_id="tenant-a",
        incident_id=incident.id,
        root_cause="Deployment regression",
        impact="Elevated payment latency",
        action_taken="Rolled back the governed deployment",
        metadata={"independent_validation_observations": [{
            "validator_id": "validator-availability",
            "connector_id": "fake-observer",
            "target_resource_id": "payments-api",
            "observed_at": "2026-08-21T10:00:00+00:00",
            "passed": True,
            "result_checksum": f"sha256:{'a' * 64}",
        }]},
    )
    async with sqlite_session_factory() as session:
        repo = IncidentRepository(session)
        await repo.save_incident(incident)
        await repo.save_report(report)
        await session.commit()

    async with sqlite_session_factory() as session:
        from common.database import RcaReportRecord, ValidationObservationRecord
        from sqlalchemy import select

        stored_report = (await session.execute(select(RcaReportRecord))).scalar_one()
        stored_observation = (await session.execute(select(ValidationObservationRecord))).scalar_one()

    assert stored_report.tenant_id == "tenant-a"
    assert stored_observation.tenant_id == "tenant-a"
    assert stored_observation.incident_id == incident.id
