from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from ai_workbench_common.models import Context
from common.context_enrichment_contract import (
    EvidenceRecord,
    EvidenceRequirement,
    HitlRoutingConfiguration,
    build_evidence_requirements,
    validate_enrichment_observation,
)
from common.database import (
    AuditLogRecord,
    CanonicalEvidenceRecord,
    ContextSnapshotRecord,
    ContextReconciliationRunRecord,
    IncidentLifecycleTransitionRecord,
    IncidentProjectionRecord,
    IncidentInvestigationBindingRecord,
    IncidentRecord,
    ResolutionOutboxRecord,
)
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


def test_duplicate_rca_gaps_produce_one_durable_requirement() -> None:
    incident_id = uuid4()
    gap = {"category": "logs", "question": "Which errors preceded the alert?"}

    requirements = build_evidence_requirements(
        tenant_id="tenant-a",
        incident_id=incident_id,
        rca_version=3,
        missing_evidence=[gap, gap],
        now=datetime.now(UTC),
    )

    assert len(requirements) == 1


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
            observation_start=now - timedelta(minutes=20), observation_end=now + timedelta(seconds=1),
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
async def test_operations_state_selects_current_requirement_and_latest_job(
    sqlite_session_factory,
):
    incident_id = uuid4()
    now = datetime.now(UTC)
    old_requirement, current_requirement = build_evidence_requirements(
        tenant_id="tenant-a", incident_id=incident_id, rca_version=1,
        missing_evidence=[{"category": "logs", "question": "What failed previously?"}], now=now,
    )[0], build_evidence_requirements(
        tenant_id="tenant-a", incident_id=incident_id, rca_version=2,
        missing_evidence=[{"category": "metrics", "question": "What is failing now?"}], now=now,
    )[0]
    async with sqlite_session_factory() as session:
        repo = ContextEnrichmentRepository(session)
        session.add(IncidentRecord(
            id=incident_id, tenant_id="tenant-a", service="checkout-api", environment="prod",
            severity="critical", status="investigating", title="Checkout latency", payload={},
        ))
        await repo.upsert_context_evidence_requirements([old_requirement, current_requirement])
        first = await repo.schedule_context_enrichment_job(
            tenant_id="tenant-a", incident_id=incident_id,
            requirement_id=current_requirement.requirement_id, connector_id="prometheus-a",
            query_payload={"query": "up"}, observation_start=now - timedelta(minutes=5), observation_end=now,
        )
        second = await repo.schedule_context_enrichment_job(
            tenant_id="tenant-a", incident_id=incident_id,
            requirement_id=current_requirement.requirement_id, connector_id="prometheus-b",
            query_payload={"query": "rate(errors[5m])"},
            observation_start=now - timedelta(minutes=5), observation_end=now,
        )
        first.created_at = now - timedelta(seconds=1)
        second.created_at = now
        await session.commit()

        state = await repo.incident_operations_state(tenant_id="tenant-a", incident_id=incident_id)

    assert state is not None
    assert state["lifecycle_state"] == "COLLECTING"
    assert state["investigation"]["rca_version"] == 0
    assert [row["requirement_id"] for row in state["requirements"]] == [str(current_requirement.requirement_id)]
    assert state["requirements"][0]["latest_job"]["job_id"] == str(second.job_id)
    assert state["requirement_history"][0]["requirement_id"] == str(old_requirement.requirement_id)
    assert state["next_action"]["type"] == "AUTONOMOUS_COLLECTION"


@pytest.mark.asyncio
async def test_operations_state_is_tenant_scoped(sqlite_session_factory):
    incident_id = uuid4()
    async with sqlite_session_factory() as session:
        session.add(IncidentRecord(
            id=incident_id, tenant_id="tenant-a", service="checkout-api", environment="prod",
            severity="critical", status="investigating", title="Checkout latency", payload={},
        ))
        session.add(IncidentProjectionRecord(
            incident_id=incident_id, tenant_id="tenant-a", service="checkout-api",
            environment="prod", status="investigating", first_seen_at=datetime.now(UTC),
            projection_payload={},
        ))
        await session.commit()
        repository = ContextEnrichmentRepository(session)
        assert await repository.incident_operations_state(
            tenant_id="tenant-b", incident_id=incident_id,
        ) is None
        assert await repository.enabled_reconciliation_tenants() == ["tenant-a"]


@pytest.mark.asyncio
async def test_incident_lifecycle_transition_is_atomic_idempotent_and_versioned(
    sqlite_session_factory,
):
    incident_id, alert_id = uuid4(), uuid4()
    now = datetime.now(UTC)
    requirement = build_evidence_requirements(
        tenant_id="tenant-a", incident_id=incident_id, rca_version=1,
        missing_evidence=[{"category": "metrics", "question": "What is failing?"}], now=now,
    )[0]
    async with sqlite_session_factory() as session:
        repo = ContextEnrichmentRepository(session)
        session.add(IncidentRecord(
            id=incident_id, tenant_id="tenant-a", service="checkout-api", environment="prod",
            severity="critical", status="investigating", title="Checkout latency", payload={},
        ))
        session.add(IncidentProjectionRecord(
            incident_id=incident_id, alert_id=alert_id, tenant_id="tenant-a",
            service="checkout-api", environment="prod", severity="critical",
            status="investigating", first_seen_at=now, projection_payload={},
        ))
        await repo.upsert_context_evidence_requirements([requirement])
        await session.commit()

        first = await repo.transition_incident_lifecycle(
            tenant_id="tenant-a", incident_id=incident_id,
            target_state="REQUIREMENTS_IDENTIFIED", expected_version=1,
            actor="context-agent", reason="RCA evidence gaps persisted",
            idempotency_key="requirements-v1",
        )
        await session.commit()
        repeated = await repo.transition_incident_lifecycle(
            tenant_id="tenant-a", incident_id=incident_id,
            target_state="REQUIREMENTS_IDENTIFIED", expected_version=1,
            actor="context-agent", reason="ignored on replay",
            idempotency_key="requirements-v1",
        )
        assert first["transition_id"] == repeated["transition_id"]
        assert repeated["idempotent"] is True

        with pytest.raises(RuntimeError, match="STALE_LIFECYCLE_VERSION"):
            await repo.transition_incident_lifecycle(
                tenant_id="tenant-a", incident_id=incident_id,
                target_state="COLLECTING", expected_version=1,
                actor="context-agent", reason="stale writer",
                idempotency_key="collecting-stale",
            )
        await session.rollback()

        projection = await session.get(IncidentProjectionRecord, incident_id)
        assert projection.lifecycle_state == "REQUIREMENTS_IDENTIFIED"
        assert projection.lifecycle_version == 2
        transitions = list((await session.execute(select(IncidentLifecycleTransitionRecord))).scalars())
        assert len(transitions) == 1
        assert await session.get(ResolutionOutboxRecord, f"incident-lifecycle:{first['transition_id']}") is not None


@pytest.mark.asyncio
async def test_incident_lifecycle_rejects_missing_prerequisite_and_failure_code(
    sqlite_session_factory,
):
    incident_id = uuid4()
    async with sqlite_session_factory() as session:
        repo = ContextEnrichmentRepository(session)
        session.add(IncidentProjectionRecord(
            incident_id=incident_id, tenant_id="tenant-a", service="checkout-api",
            environment="prod", status="investigating", first_seen_at=datetime.now(UTC),
            projection_payload={},
        ))
        await session.commit()
        with pytest.raises(ValueError, match="REQUIREMENTS_MISSING"):
            await repo.transition_incident_lifecycle(
                tenant_id="tenant-a", incident_id=incident_id,
                target_state="REQUIREMENTS_IDENTIFIED", expected_version=1,
                actor="context-agent", reason="no requirements", idempotency_key="missing",
            )
        await session.rollback()
        with pytest.raises(ValueError, match="failure_code"):
            await repo.transition_incident_lifecycle(
                tenant_id="tenant-a", incident_id=incident_id,
                target_state="COLLECTION_BLOCKED", expected_version=1,
                actor="context-agent", reason="connector exhausted", idempotency_key="blocked",
            )


@pytest.mark.asyncio
async def test_reconciliation_lease_prevents_overlap_and_records_run(sqlite_session_factory):
    async with sqlite_session_factory() as first_session:
        first = ContextEnrichmentRepository(first_session)
        assert await first.claim_reconciliation_lease(
            lease_key="active-incidents", owner="worker-a", lease_seconds=60,
        ) is True
        await first_session.commit()

    async with sqlite_session_factory() as second_session:
        second = ContextEnrichmentRepository(second_session)
        assert await second.claim_reconciliation_lease(
            lease_key="active-incidents", owner="worker-b", lease_seconds=60,
        ) is False
        await second_session.rollback()

    async with sqlite_session_factory() as first_session:
        first = ContextEnrichmentRepository(first_session)
        await first.release_reconciliation_lease(lease_key="active-incidents", owner="worker-a")
        await first_session.commit()

    async with sqlite_session_factory() as second_session:
        second = ContextEnrichmentRepository(second_session)
        assert await second.claim_reconciliation_lease(
            lease_key="active-incidents", owner="worker-b", lease_seconds=60,
        ) is True
        run = await second.start_reconciliation_run(owner="worker-b", tenant_id="tenant-a")
        await second.finish_reconciliation_run(
            run_id=run.run_id,
            summary={"incidents_scanned": 2, "jobs_scheduled": 1, "errors": []},
            status="completed",
        )
        await second_session.commit()
        persisted = await second_session.get(ContextReconciliationRunRecord, run.run_id)
        assert persisted.status == "completed"
        assert persisted.incidents_scanned == 2
        assert persisted.jobs_scheduled == 1
        assert persisted.duration_ms >= 0


@pytest.mark.asyncio
async def test_exhausted_context_job_is_dead_lettered(sqlite_session_factory):
    incident_id = uuid4()
    now = datetime.now(UTC)
    requirement = build_evidence_requirements(
        tenant_id="tenant-a", incident_id=incident_id, rca_version=1,
        missing_evidence=[{"category": "metrics", "question": "What failed?"}], now=now,
    )[0]
    async with sqlite_session_factory() as session:
        repo = ContextEnrichmentRepository(session)
        await repo.upsert_context_evidence_requirements([requirement])
        job = await repo.schedule_context_enrichment_job(
            tenant_id="tenant-a", incident_id=incident_id,
            requirement_id=requirement.requirement_id, connector_id="prometheus",
            query_payload={}, observation_start=now - timedelta(minutes=5), observation_end=now,
        )
        await session.commit()
        await repo.claim_context_enrichment_jobs(worker_id="worker-a", limit=1)
        await repo.finish_context_enrichment_job(
            job_id=job.job_id, worker_id="worker-a", collected=False,
            error="connector unavailable", maximum_attempts=1,
        )
        await session.commit()
        activity = await repo.list_context_enrichment_activity(
            tenant_id="tenant-a", incident_id=incident_id,
        )
        assert activity["jobs"][0]["status"] == "dead_letter"
        assert "connector unavailable" in activity["jobs"][0]["last_error"]


@pytest.mark.asyncio
async def test_atomic_enrichment_persists_exact_evidence_snapshot_and_outbox(
    sqlite_session_factory,
):
    incident_id = uuid4()
    requirement = EvidenceRequirement(
        requirement_id=uuid4(), tenant_id="tenant-a", incident_id=incident_id,
        rca_version=1, category="metrics", question="What was latency?",
        reason="Confirm the alert", priority="high", collection_mode="automatic",
        candidate_connectors=["prometheus"], created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
    )
    now = datetime.now(UTC)
    record = EvidenceRecord(
        evidence_id="EVD-" + "a" * 64, requirement_id=str(requirement.requirement_id),
        tenant_id="tenant-a", incident_id=str(incident_id), category="metrics",
        source_id="prometheus:9090", connector="prometheus",
        source_reference="prometheus://prometheus:9090/query?expr=up",
        service="checkout-api", observed_at=now, collected_at=now, freshness="fresh",
        content={"metric_name": "up", "labels": {"service": "checkout-api"},
                 "samples": [{"timestamp": now.isoformat(), "value": "0"}]},
        provenance={"query": "up"}, current_observation=True,
    )
    async with sqlite_session_factory() as session:
        repo = ContextEnrichmentRepository(session)
        await repo.upsert_context_evidence_requirements([requirement])
        job = await repo.schedule_context_enrichment_job(
            tenant_id="tenant-a", incident_id=incident_id,
            requirement_id=requirement.requirement_id, connector_id="prometheus",
            query_payload={"incident": {"id": str(incident_id), "tenant_id": "tenant-a",
                                          "service": "checkout-api", "title": "latency"}, "decision": {}},
            observation_start=now - timedelta(minutes=5), observation_end=now,
        )
        session.add(ContextSnapshotRecord(
            snapshot_id=uuid4(), tenant_id="tenant-a", incident_id=str(incident_id),
            alert_signature="signature", subject_fingerprint="s" * 64,
            context_fingerprint="c" * 64, snapshot_version=1, evidence_ids=[],
            evidence_checksums={}, contract_version="kaiops.context.v2", quality_score=0.2,
            reusable=False, source_manifest={}, payload={"tenant_id": "tenant-a",
                "incident_id": str(incident_id), "metadata": {"context_evidence": {}}},
            collected_at=now, expires_at=now + timedelta(hours=1),
        ))
        await session.commit()
    async with sqlite_session_factory() as session:
        repo = ContextEnrichmentRepository(session)
        await repo.claim_context_enrichment_jobs(worker_id="worker-a", limit=1)
        result = await repo.persist_enrichment_result_atomically(
            job_id=job.job_id, worker_id="worker-a", accepted_records=[record],
            rejected_records=[], source_response_metadata={"query": "up"},
        )
        await session.commit()
        assert result["evidence_ids"] == [record.evidence_id]
        assert await session.get(CanonicalEvidenceRecord, record.evidence_id) is not None
        assert await session.get(ResolutionOutboxRecord, result["outbox_event_id"]) is not None
        snapshot = await session.get(ContextSnapshotRecord, UUID(result["snapshot_id"]))
        assert snapshot.evidence_ids == [record.evidence_id]
        assert snapshot.payload["metadata"]["context_evidence"]["metrics"][0]["evidence_id"] == record.evidence_id


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


@pytest.mark.asyncio
async def test_active_gap_reconciliation_is_idempotent(sqlite_session_factory) -> None:
    incident_id, alert_id, snapshot_id, recommendation_id = uuid4(), uuid4(), uuid4(), uuid4()
    analysis_id = uuid4()
    now = datetime.now(UTC)
    async with sqlite_session_factory() as session:
        session.add(IncidentRecord(
            id=incident_id, tenant_id="tenant-a", service="checkout-api", environment="prod",
            severity="critical", status="investigating", title="checkout latency", payload={},
        ))
        session.add(ContextSnapshotRecord(
            snapshot_id=snapshot_id, tenant_id="tenant-a", incident_id=str(incident_id),
            alert_signature="signature", subject_fingerprint="s" * 64,
            context_fingerprint="c" * 64, contract_version="kaiops.context.v2",
            quality_score=0.4, reusable=False, source_manifest={}, payload={},
            collected_at=now, expires_at=now + timedelta(hours=1),
        ))
        session.add(IncidentInvestigationBindingRecord(
            tenant_id="tenant-a", project_id="project-a", incident_id=incident_id,
            alert_id=alert_id, analysis_request_id=analysis_id, context_snapshot_id=snapshot_id,
            context_fingerprint="c" * 64, recommendation_id=recommendation_id,
            rca_version=3, status="insufficient_evidence", created_at=now,
            expires_at=now + timedelta(hours=1),
        ))
        session.add(AuditLogRecord(
            id=recommendation_id, tenant_id="tenant-a", actor="resolution-agent",
            action="recommendation.generated", resource_type="incident",
            resource_id=str(incident_id), payload={"metadata": {"rca_analysis": {
                "missing_evidence": [{"category": "logs", "question": "Which errors occurred?"}],
            }}},
        ))
        await session.flush()
        repo = ContextEnrichmentRepository(session)
        candidates = await repo.active_incident_gap_candidates(tenant_id="tenant-a")
        requirements = await plan_missing_evidence(
            context_for(incident_id), {
                "tenant_id": "tenant-a", "incident_id": str(incident_id), "rca_version": 3,
                "missing_evidence": candidates[0]["gaps"],
            },
        )
        first = await repo.upsert_context_evidence_requirements(requirements)
        second = await repo.upsert_context_evidence_requirements(requirements)
        assert len(candidates) == 1
        assert first[0].requirement_id == second[0].requirement_id


def test_hitl_routing_configuration_rejects_placeholder_identity():
    with pytest.raises(ValueError, match="explicit governed identities"):
        HitlRoutingConfiguration(
            default_approver_group="admin", l2_group="checkout-l2", l3_group="checkout-l3",
            service_owner="checkout-owner", timezone="Asia/Calcutta", business_hours={},
            severity_sla_minutes={"critical": 15}, jira_project_key="KAN", jira_issue_type="Bug",
            jira_transition_mapping={"approved": "31"}, fallback_assignment_group="platform-l2",
        )
