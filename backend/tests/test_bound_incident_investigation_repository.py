from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from common.database import (
    ActionRecord,
    AlertRecord,
    AuditLogRecord,
    ContextSnapshotRecord,
    GovernedResolutionPlanRecord,
    IncidentInvestigationBindingRecord,
    IncidentProjectionRecord,
    IncidentRecord,
    ResolutionOutboxRecord,
    ResolutionPlanSupersessionRecord,
)
from common.repository import IncidentRepository
from sqlalchemy import func, select


async def _seed_pair(
    session,
    *,
    tenant_id: str,
    incident_id,
    alert_id,
    snapshot_id,
    recommendation_id,
    fingerprint: str,
    evidence_id: str,
    expires_at: datetime | None = None,
) -> None:
    now = datetime.now(UTC)
    analysis_request_id = uuid4()
    session.add(ContextSnapshotRecord(
        snapshot_id=snapshot_id,
        tenant_id=tenant_id,
        incident_id=str(incident_id),
        source_incident_id=str(incident_id),
        alert_signature="alert-signature",
        subject_fingerprint="b" * 64,
        context_fingerprint=fingerprint,
        contract_version="kaiops.context.v2",
        quality_score=0.9,
        reusable=True,
        source_manifest={},
        payload={
            "alert": {"id": str(alert_id), "service": "payments"},
            "metadata": {
                "alert_id": str(alert_id),
                "project_id": "payments",
                "context_quality": {
                    "coverage_score": 1.0, "freshness_score": 1.0,
                    "provenance_score": 1.0, "reusable": True,
                },
                "context_sources": {},
                "context_evidence": {
                    "telemetry": [{
                        "evidence_id": evidence_id, "category": "metrics",
                        "source_id": "prometheus", "connector": "prometheus",
                        "tenant_id": tenant_id, "project_id": "payments", "service": "payments",
                        "collected_at": now.isoformat(), "freshness": "fresh",
                        "provenance": {}, "citation": "prometheus://query/test",
                        "epistemic_role": "current_observation", "current_observation": True,
                    }],
                },
            },
        },
        collected_at=now - timedelta(minutes=1),
        expires_at=expires_at or now + timedelta(hours=1),
    ))
    session.add(AuditLogRecord(
        id=recommendation_id,
        tenant_id=tenant_id,
        actor="resolution-agent",
        action="recommendation.generated",
        resource_type="incident",
        resource_id=str(incident_id),
        payload={
            "id": str(recommendation_id),
            "incident_id": str(incident_id),
            "metadata": {
                "alert_id": str(alert_id),
                "project_id": "payments",
                "analysis_request_id": str(analysis_request_id),
                "context_snapshot_id": str(snapshot_id),
                "context_fingerprint": fingerprint,
                "evidence_ids": [evidence_id],
                "rca_version": 1,
                "rca_status": "grounded",
                "rca_analysis": {"evidence_used": [evidence_id], "missing_evidence": []},
                "investigation_report": {
                    "investigation_id": str(uuid4()), "status": "conclusive", "conclusive": True,
                },
                "execution_plan": {"execution_ready": False, "mutating": False, "readiness_blocks": []},
            },
        },
    ))
    session.add(IncidentInvestigationBindingRecord(
        binding_id=recommendation_id, tenant_id=tenant_id, project_id="payments",
        incident_id=incident_id, alert_id=alert_id, analysis_request_id=analysis_request_id,
        context_snapshot_id=snapshot_id, context_fingerprint=fingerprint,
        recommendation_id=recommendation_id, rca_version=1, resolution_plan_id=None,
        plan_fingerprint=None, status="grounded", created_at=now,
        expires_at=expires_at or now + timedelta(hours=1),
    ))


@pytest.mark.asyncio
async def test_next_rca_version_uses_durable_incident_history(sqlite_session_factory) -> None:
    incident_id, alert_id = uuid4(), uuid4()
    async with sqlite_session_factory() as session:
        await _seed_pair(
            session, tenant_id="tenant-a", incident_id=incident_id, alert_id=alert_id,
            snapshot_id=uuid4(), recommendation_id=uuid4(), fingerprint="1" * 64,
            evidence_id="evidence-v1",
        )
        assert await IncidentRepository(session).next_incident_rca_version(
            tenant_id="tenant-a", incident_id=incident_id,
        ) == 2
        assert await IncidentRepository(session).next_incident_rca_version(
            tenant_id="tenant-a", incident_id=uuid4(),
        ) == 1


@pytest.mark.asyncio
async def test_bound_recommendation_keeps_its_snapshot_when_a_newer_snapshot_exists(
    sqlite_session_factory,
) -> None:
    incident_id, alert_id = uuid4(), uuid4()
    snapshot_v1, recommendation_v1 = uuid4(), uuid4()
    async with sqlite_session_factory() as session:
        await _seed_pair(
            session, tenant_id="tenant-a", incident_id=incident_id, alert_id=alert_id,
            snapshot_id=snapshot_v1, recommendation_id=recommendation_v1,
            fingerprint="1" * 64, evidence_id="evidence-v1",
        )
        session.add(ContextSnapshotRecord(
            snapshot_id=uuid4(), tenant_id="tenant-a", incident_id=str(incident_id),
            source_incident_id=str(incident_id), alert_signature="newer",
            subject_fingerprint="c" * 64, context_fingerprint="2" * 64,
            contract_version="kaiops.context.v2", quality_score=1.0, reusable=True,
            source_manifest={}, payload={}, collected_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(hours=2),
        ))
        await session.commit()
        result = await IncidentRepository(session).get_bound_incident_investigation(
            tenant_id="tenant-a", incident_id=incident_id, alert_id=alert_id,
            recommendation_id=recommendation_v1,
        )

    assert result["investigation_integrity"]["status"] == "verified"
    assert result["context_snapshot"]["snapshot_id"] == str(snapshot_v1)


@pytest.mark.asyncio
async def test_processed_result_uses_projection_recommendation_snapshot_and_emits_integrity(
    sqlite_session_factory,
) -> None:
    incident_id, alert_id = uuid4(), uuid4()
    snapshot_v1, recommendation_v1 = uuid4(), uuid4()
    now = datetime.now(UTC)
    async with sqlite_session_factory() as session:
        await _seed_pair(
            session, tenant_id="tenant-a", incident_id=incident_id, alert_id=alert_id,
            snapshot_id=snapshot_v1, recommendation_id=recommendation_v1,
            fingerprint="1" * 64, evidence_id="evidence-v1",
        )
        session.add(AlertRecord(
            id=alert_id, tenant_id="tenant-a", source="prometheus", name="LatencyHigh",
            service="payments", environment="prod", severity="critical", fingerprint="alert-fp",
            payload={"id": str(alert_id), "tenant_id": "tenant-a", "project_id": "payments", "labels": {}},
        ))
        session.add(IncidentRecord(
            id=incident_id, tenant_id="tenant-a", service="payments", environment="prod",
            severity="critical", status="investigating", title="Payments latency", ticket_id=None,
            payload={"id": str(incident_id), "project_id": "payments", "alert_ids": [str(alert_id)]},
        ))
        session.add(IncidentProjectionRecord(
            incident_id=incident_id, alert_id=alert_id, recommendation_id=recommendation_v1,
            tenant_id="tenant-a", service="payments", environment="prod", severity="critical",
            status="investigating", first_seen_at=now, projection_payload={},
        ))
        legacy_action_id = uuid4()
        session.add(ActionRecord(
            id=legacy_action_id, tenant_id="tenant-a", incident_id=incident_id,
            recommendation_id=None, resolution_plan_id=None, plan_fingerprint=None,
            approval_id=None, action_type="restart", target="payments",
            idempotency_key=f"legacy-{legacy_action_id}", status="succeeded",
            payload={"id": str(legacy_action_id), "status": "succeeded"},
        ))
        session.add(ContextSnapshotRecord(
            snapshot_id=uuid4(), tenant_id="tenant-a", incident_id=str(incident_id),
            source_incident_id=str(incident_id), alert_signature="newer",
            subject_fingerprint="c" * 64, context_fingerprint="2" * 64,
            contract_version="kaiops.context.v2", quality_score=1.0, reusable=True,
            source_manifest={}, payload={"marker": "snapshot-v2"}, collected_at=now + timedelta(seconds=1),
            expires_at=now + timedelta(hours=2),
        ))
        await session.commit()
        result = await IncidentRepository(session).get_processed_result_by_alert_id(
            str(alert_id), tenant_id="tenant-a",
        )

    assert result is not None
    assert result["investigation_integrity"]["status"] == "verified"
    assert result["incident_investigation"]["context_snapshot_id"] == str(snapshot_v1)
    assert result["context"]["metadata"]["snapshot"]["snapshot_id"] == str(snapshot_v1)
    assert result["remediation_action"] == {}
    assert result["metrics"]["remediation_status"] == "unknown"
    assert result["legacy_lifecycle_records"][0]["record_id"] == str(legacy_action_id)
    assert result["legacy_lifecycle_records"][0]["status"] == "legacy_unbound"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("fingerprint", "fingerprint_mismatch"),
        ("alert", "alert_mismatch"),
        ("evidence", "evidence_mismatch"),
        ("expired", "context_expired"),
    ],
)
async def test_bound_investigation_fails_closed(
    sqlite_session_factory, mutation: str, expected: str,
) -> None:
    incident_id, alert_id = uuid4(), uuid4()
    snapshot_id, recommendation_id = uuid4(), uuid4()
    async with sqlite_session_factory() as session:
        await _seed_pair(
            session, tenant_id="tenant-a", incident_id=incident_id, alert_id=alert_id,
            snapshot_id=snapshot_id, recommendation_id=recommendation_id,
            fingerprint="a" * 64, evidence_id="evidence-1",
            expires_at=(datetime.now(UTC) - timedelta(seconds=1)) if mutation == "expired" else None,
        )
        recommendation = await session.get(AuditLogRecord, recommendation_id)
        metadata = dict(recommendation.payload["metadata"])
        if mutation == "fingerprint":
            metadata["context_fingerprint"] = "f" * 64
        elif mutation == "alert":
            metadata["alert_id"] = str(uuid4())
        elif mutation == "evidence":
            metadata["evidence_ids"] = ["not-in-snapshot"]
        recommendation.payload = {**recommendation.payload, "metadata": metadata}
        await session.commit()
        result = await IncidentRepository(session).get_bound_incident_investigation(
            tenant_id="tenant-a", incident_id=incident_id, alert_id=alert_id,
            recommendation_id=recommendation_id,
        )

    assert result["investigation_integrity"]["status"] == expected
    assert result["investigation_integrity"]["verified"] is False
    assert result["context_snapshot"] == {}


def _catalog_option(option_id: str = "latency-kubernetes-diagnose") -> dict:
    return {
        "id": option_id,
        "source": "kaims-governed-catalog-v1",
        "service": "payments",
        "target_resource": "payments",
        "connector_id": "diagnostic-only",
        "risk": "low",
        "commands": [],
        "validation": ["Latency returns within SLO"],
        "rollback": ["No mutation is permitted before approval"],
        "execution_eligible": False,
        "requires_operator_review": True,
    }


@pytest.mark.asyncio
async def test_catalog_selection_persists_once_with_projection_audit_and_outbox(
    sqlite_session_factory,
) -> None:
    incident_id, alert_id, snapshot_id, recommendation_id = uuid4(), uuid4(), uuid4(), uuid4()
    async with sqlite_session_factory() as session:
        await _seed_pair(
            session, tenant_id="tenant-a", incident_id=incident_id, alert_id=alert_id,
            snapshot_id=snapshot_id, recommendation_id=recommendation_id,
            fingerprint="a" * 64, evidence_id="evidence-1",
        )
        binding = await session.get(IncidentInvestigationBindingRecord, recommendation_id)
        session.add(IncidentProjectionRecord(
            incident_id=incident_id, alert_id=alert_id, recommendation_id=recommendation_id,
            tenant_id="tenant-a", service="payments", environment="prod", severity="critical",
            status="investigating", first_seen_at=datetime.now(UTC), projection_payload={},
        ))
        await session.commit()
        repo = IncidentRepository(session)
        kwargs = dict(
            tenant_id="tenant-a", incident_id=incident_id, alert_id=alert_id,
            analysis_request_id=binding.analysis_request_id, context_snapshot_id=snapshot_id,
            context_fingerprint="a" * 64, recommendation_id=recommendation_id, rca_version=1,
            option=_catalog_option(), selected_by="operator-a",
        )
        first = await repo.persist_governed_resolution_selection(**kwargs)
        await session.commit()
        second = await repo.persist_governed_resolution_selection(**kwargs)
        await session.commit()

        assert second == first
        assert first["schema_version"] == "kaims.resolution-selection.v1"
        assert first["status"] == "selected"
        assert await session.scalar(select(func.count()).select_from(GovernedResolutionPlanRecord)) == 1
        assert await session.scalar(select(func.count()).select_from(ResolutionOutboxRecord)) >= 1
        projection = await session.get(IncidentProjectionRecord, incident_id)
        assert projection.projection_payload["resolution_selection"]["selection_id"] == first["selection_id"]
        assert "execution_plan" not in projection.projection_payload
        audit = await session.scalar(select(AuditLogRecord).where(AuditLogRecord.action == "resolution.plan.selected"))
        assert audit.payload["selection_id"] == first["selection_id"]


@pytest.mark.asyncio
async def test_new_catalog_option_creates_immutable_supersession_relation(sqlite_session_factory) -> None:
    incident_id, alert_id, snapshot_id, recommendation_id = uuid4(), uuid4(), uuid4(), uuid4()
    async with sqlite_session_factory() as session:
        await _seed_pair(
            session, tenant_id="tenant-a", incident_id=incident_id, alert_id=alert_id,
            snapshot_id=snapshot_id, recommendation_id=recommendation_id,
            fingerprint="b" * 64, evidence_id="evidence-1",
        )
        binding = await session.get(IncidentInvestigationBindingRecord, recommendation_id)
        session.add(IncidentProjectionRecord(
            incident_id=incident_id, alert_id=alert_id, recommendation_id=recommendation_id,
            tenant_id="tenant-a", service="payments", environment="prod", severity="critical",
            status="investigating", first_seen_at=datetime.now(UTC), projection_payload={},
        ))
        await session.commit()
        repo = IncidentRepository(session)
        base = dict(
            tenant_id="tenant-a", incident_id=incident_id, alert_id=alert_id,
            analysis_request_id=binding.analysis_request_id, context_snapshot_id=snapshot_id,
            context_fingerprint="b" * 64, recommendation_id=recommendation_id, rca_version=1,
            selected_by="operator-a",
        )
        first = await repo.persist_governed_resolution_selection(**base, option=_catalog_option("option-one"))
        await session.commit()
        second = await repo.persist_governed_resolution_selection(**base, option=_catalog_option("option-two"))
        await session.commit()
        relation = await session.scalar(select(ResolutionPlanSupersessionRecord))
        assert first["selection_id"] != second["selection_id"]
        assert str(relation.supersedes) == first["selection_id"]
        assert str(relation.superseded_by) == second["selection_id"]


@pytest.mark.asyncio
async def test_stale_catalog_selection_writes_nothing(sqlite_session_factory) -> None:
    incident_id, alert_id, snapshot_id, recommendation_id = uuid4(), uuid4(), uuid4(), uuid4()
    async with sqlite_session_factory() as session:
        await _seed_pair(
            session, tenant_id="tenant-a", incident_id=incident_id, alert_id=alert_id,
            snapshot_id=snapshot_id, recommendation_id=recommendation_id,
            fingerprint="c" * 64, evidence_id="evidence-1",
        )
        binding = await session.get(IncidentInvestigationBindingRecord, recommendation_id)
        session.add(IncidentProjectionRecord(
            incident_id=incident_id, alert_id=alert_id, recommendation_id=uuid4(),
            tenant_id="tenant-a", service="payments", environment="prod", severity="critical",
            status="investigating", first_seen_at=datetime.now(UTC), projection_payload={},
        ))
        await session.commit()
        with pytest.raises(ValueError, match="stale recommendation"):
            await IncidentRepository(session).persist_governed_resolution_selection(
                tenant_id="tenant-a", incident_id=incident_id, alert_id=alert_id,
                analysis_request_id=binding.analysis_request_id, context_snapshot_id=snapshot_id,
                context_fingerprint="c" * 64, recommendation_id=recommendation_id, rca_version=1,
                option=_catalog_option(), selected_by="operator-a",
            )
        await session.rollback()
        assert await session.scalar(select(func.count()).select_from(GovernedResolutionPlanRecord)) == 0
        assert await session.scalar(select(func.count()).select_from(ResolutionOutboxRecord)) == 0
