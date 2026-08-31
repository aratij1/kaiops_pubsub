from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from ai_workbench_common.models import Context
from common.context_enrichment_contract import (
    EvidenceRequirement,
    HitlRoutingConfiguration,
    validate_enrichment_observation,
)
from common.database import ContextSnapshotRecord, IncidentInvestigationBindingRecord
from common.models import Alert, AlertSeverity, Incident
from common.repository import ContextEnrichmentRepository
from context_agent.connectors import execute_enrichment_plan
from context_agent.context_quality import plan_missing_evidence
from sqlalchemy import select


def context_for(incident_id, *, tenant_id="tenant-a") -> Context:
    alert = Alert(
        tenant_id=tenant_id, source="prometheus", name="LatencyHigh",
        service="checkout-api", environment="prod", severity=AlertSeverity.CRITICAL,
        description="p99 latency is above threshold",
    )
    return Context(tenant_id=tenant_id, incident_id=incident_id, alert=alert)


def test_trace_gap_rejects_metric_only_observation() -> None:
    incident_id = uuid4()
    context = context_for(incident_id)
    now = datetime.now(UTC)
    requirement = EvidenceRequirement(
        requirement_id=uuid4(), tenant_id="tenant-a", incident_id=incident_id,
        rca_version=1, category="traces", question="Which span failed?", reason="Test the causal path",
        priority="high", collection_mode="automatic", candidate_connectors=["jaeger"],
        created_at=now, updated_at=now,
    )
    result = validate_enrichment_observation(
        requirement, "jaeger", {
            "evidence": [{"category": "metrics", "metric_name": "latency", "value": 4,
                          "source_uri": "prometheus://latency", "collected_at": now.isoformat()}],
        }, Incident(id=incident_id, tenant_id="tenant-a", service="checkout-api", title="test"),
        context.alert, now,
    )
    assert result.accepted is False
    assert "does not match traces" in result.rejection_reasons[0]


def test_trace_gap_accepts_attributable_trace_and_redacts_secrets() -> None:
    incident_id = uuid4()
    context = context_for(incident_id)
    now = datetime.now(UTC)
    requirement = EvidenceRequirement(
        requirement_id=uuid4(), tenant_id="tenant-a", incident_id=incident_id,
        rca_version=1, category="traces", question="Which span failed?", reason="Test the causal path",
        priority="high", collection_mode="automatic", candidate_connectors=["jaeger"],
        created_at=now, updated_at=now,
    )
    result = validate_enrichment_observation(
        requirement, "jaeger", {"spans": [{
            "category": "traces", "trace_id": "trace-1", "span_id": "span-1",
            "service": "checkout-api", "tenant_id": "tenant-a", "timestamp": now.isoformat(),
            "source_uri": "jaeger://trace/trace-1", "token": "do-not-persist",
        }]}, Incident(id=incident_id, tenant_id="tenant-a", service="checkout-api", title="test"), context.alert, now,
    )
    assert result.accepted is True
    assert result.accepted_evidence[0]["token"] == "[REDACTED]"
    assert result.accepted_evidence[0]["category"] == "traces"


@pytest.mark.asyncio
async def test_missing_automatic_evidence_creates_idempotent_enrichment_jobs(
    sqlite_session_factory,
):
    incident_id = uuid4()
    requirements = await plan_missing_evidence(
        context_for(incident_id),
        {"tenant_id": "tenant-a", "incident_id": str(incident_id), "rca_version": 2,
         "missing_evidence": [{"category": "logs", "question": "Which errors preceded the alert?"}]},
    )
    result = await execute_enrichment_plan(requirements, authorized_connectors={"opensearch"})
    assert result.scheduled_requirement_ids == [requirements[0].requirement_id]

    now = datetime.now(UTC)
    async with sqlite_session_factory() as session:
        repo = ContextEnrichmentRepository(session)
        await repo.upsert_context_evidence_requirements(requirements)
        first = await repo.schedule_context_enrichment_job(
            tenant_id="tenant-a", incident_id=incident_id,
            requirement_id=requirements[0].requirement_id, connector_id="opensearch",
            query_payload={"service": "checkout-api", "environment": "prod"},
            observation_start=now - timedelta(minutes=10), observation_end=now,
        )
        second = await repo.schedule_context_enrichment_job(
            tenant_id="tenant-a", incident_id=incident_id,
            requirement_id=requirements[0].requirement_id, connector_id="opensearch",
            query_payload={"service": "checkout-api", "environment": "prod"},
            observation_start=now - timedelta(minutes=10), observation_end=now,
        )
        assert first.job_id == second.job_id
        job_id = first.job_id
        await session.commit()

    async with sqlite_session_factory() as session:
        repo = ContextEnrichmentRepository(session)
        claimed = await repo.claim_context_enrichment_jobs(worker_id="worker-a", limit=1)
        assert claimed[0]["job_id"] == str(job_id)
        assert claimed[0]["attempt_count"] == 1
        assert claimed[0]["lease_owner"] == "worker-a"
        with pytest.raises(RuntimeError, match="lease is not owned"):
            await repo.finish_context_enrichment_job(
                job_id=job_id, worker_id="worker-b", collected=True,
            )
        await repo.finish_context_enrichment_job(
            job_id=job_id, worker_id="worker-a", collected=True,
        )
        activity = await repo.list_context_enrichment_activity(
            tenant_id="tenant-a", incident_id=incident_id,
        )
        assert activity["jobs"][0]["status"] == "collected"
        assert activity["jobs"][0]["lease_owner"] is None


@pytest.mark.asyncio
async def test_connector_unavailable_becomes_human_request_without_stopping_other_work(
    sqlite_session_factory,
):
    incident_id = uuid4()
    requirements = await plan_missing_evidence(
        context_for(incident_id),
        {"tenant_id": "tenant-a", "incident_id": str(incident_id), "rca_version": 1,
         "missing_evidence": ["logs", "ownership"]},
    )
    result = await execute_enrichment_plan(requirements, authorized_connectors={"opensearch"})
    assert len(result.scheduled_requirement_ids) == 1
    assert len(result.human_requirement_ids) == 1

    human_requirement = next(row for row in requirements if row.collection_mode == "human_required")
    async with sqlite_session_factory() as session:
        repo = ContextEnrichmentRepository(session)
        await repo.upsert_context_evidence_requirements(requirements)
        request = await repo.create_human_evidence_request(
            tenant_id="tenant-a", incident_id=incident_id,
            requirement_id=human_requirement.requirement_id,
            expected_responder="checkout-service-owner", due_at=datetime.now(UTC) + timedelta(hours=1),
            acceptable_format="Account ID or governed support group",
            evidence_already_checked=["cmdb", "service-catalog"],
            hypothesis_impact="Determines the authorized approver",
            investigation_can_continue=True,
        )
        assert request.investigation_can_continue is True


@pytest.mark.asyncio
async def test_human_response_is_tenant_scoped_and_recorded_as_assertion(sqlite_session_factory):
    incident_id = uuid4()
    requirement = EvidenceRequirement(
        requirement_id=uuid4(), tenant_id="tenant-a", incident_id=incident_id,
        rca_version=1, category="business_impact", question="Is checkout customer-facing?",
        reason="Impact classification requires business ownership", priority="high",
        collection_mode="human_required", created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
    )
    async with sqlite_session_factory() as session:
        repo = ContextEnrichmentRepository(session)
        now = datetime.now(UTC)
        snapshot_id, alert_id, analysis_id, recommendation_id = uuid4(), uuid4(), uuid4(), uuid4()
        session.add(ContextSnapshotRecord(
            snapshot_id=snapshot_id, tenant_id="tenant-a", incident_id=str(incident_id),
            source_incident_id=str(incident_id), alert_signature="alert-signature",
            subject_fingerprint="s" * 64, context_fingerprint="c" * 64,
            snapshot_stage="final", snapshot_version=1, evidence_ids=["metric-1"],
            evidence_checksums={"metric-1": "m" * 64}, contract_version="kaiops.context.v2",
            quality_score=0.5, reusable=False, source_manifest={}, payload={"metadata": {}},
            collected_at=now, expires_at=now + timedelta(hours=1),
        ))
        session.add(IncidentInvestigationBindingRecord(
            tenant_id="tenant-a", project_id="project-a", incident_id=incident_id,
            alert_id=alert_id, analysis_request_id=analysis_id, context_snapshot_id=snapshot_id,
            context_fingerprint="c" * 64, recommendation_id=recommendation_id,
            rca_version=1, status="grounded", created_at=now, expires_at=now + timedelta(hours=1),
        ))
        await repo.upsert_context_evidence_requirements([requirement])
        await repo.create_human_evidence_request(
            tenant_id="tenant-a", incident_id=incident_id, requirement_id=requirement.requirement_id,
            expected_responder="checkout-product-owner", due_at=datetime.now(UTC) + timedelta(hours=1),
            acceptable_format="yes/no with service catalog link", evidence_already_checked=["cmdb"],
            hypothesis_impact="Changes customer-impact classification",
        )
        with pytest.raises(LookupError):
            await repo.record_human_evidence_response(
                tenant_id="tenant-b", incident_id=incident_id, requirement_id=requirement.requirement_id,
                response={"response": "yes", "responder_id": "owner-a", "responded_at": datetime.now(UTC).isoformat()},
            )
        recorded = await repo.record_human_evidence_response(
            tenant_id="tenant-a", incident_id=incident_id, requirement_id=requirement.requirement_id,
            response={"response": "yes", "responder_id": "owner-a", "responded_at": datetime.now(UTC).isoformat()},
        )
        assert recorded["evidence_id"].startswith("HUMAN-")
        assert recorded["context_snapshot_id"] is not None
        gaps = await repo.list_context_evidence_requirements(
            tenant_id="tenant-a", incident_id=incident_id,
        )
        assert gaps[0]["status"] == "answered"
        assert gaps[0]["evidence_ids"] == [recorded["evidence_id"]]
        latest = (await session.execute(
            select(ContextSnapshotRecord).where(
                ContextSnapshotRecord.tenant_id == "tenant-a",
                ContextSnapshotRecord.incident_id == str(incident_id),
            ).order_by(ContextSnapshotRecord.snapshot_version.desc())
        )).scalars().first()
        assert latest.snapshot_version == 2
        assert latest.parent_snapshot_id == snapshot_id


def test_hitl_routing_configuration_rejects_placeholder_identity():
    with pytest.raises(ValueError, match="explicit governed identities"):
        HitlRoutingConfiguration(
            default_approver_group="admin", l2_group="checkout-l2", l3_group="checkout-l3",
            service_owner="checkout-owner", timezone="Asia/Calcutta", business_hours={},
            severity_sla_minutes={"critical": 15}, jira_project_key="KAN", jira_issue_type="Bug",
            jira_transition_mapping={"approved": "31"}, fallback_assignment_group="platform-l2",
        )
