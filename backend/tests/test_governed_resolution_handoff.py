from __future__ import annotations

import importlib.util
from pathlib import Path
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest
from common.models import Alert, AlertSeverity, ApprovalDecision, Recommendation
from common.orchestration.execution_plan import resolve_execution_plan
from common.orchestration.execution_plan_contract import ExecutionPlanV2
from common.repository import IncidentRepository

from test_bound_incident_investigation_repository import _seed_pair


def load_approval_module():
    path = Path("backend/src/approval-service/app.py")
    spec = importlib.util.spec_from_file_location("canonical_approval_app", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_resolution_module():
    path = Path("ai-workbench/src/resolution-agent/app.py")
    spec = importlib.util.spec_from_file_location("governed_resolution_agent_app", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def catalog_option() -> dict:
    return {
        "id": "restart-service", "source": "kaims-governed-catalog-v1",
        "service": "api-gateway", "risk": "high", "execution_eligible": False,
        "validation": ["health"], "rollback": ["rollback"],
    }


@pytest.mark.asyncio
async def test_incident_and_approval_use_exact_persisted_execution_plan(sqlite_session_factory):
    incident_id, alert_id, snapshot_id, recommendation_id = uuid4(), uuid4(), uuid4(), uuid4()
    async with sqlite_session_factory() as session:
        await _seed_pair(
            session, tenant_id="tenant-a", incident_id=incident_id, alert_id=alert_id,
            snapshot_id=snapshot_id, recommendation_id=recommendation_id,
            fingerprint="d" * 64, evidence_id="metric:up:api-gateway",
        )
        from common.database import IncidentProjectionRecord
        from datetime import UTC, datetime
        session.add(IncidentProjectionRecord(
            incident_id=incident_id, alert_id=alert_id, recommendation_id=recommendation_id,
            tenant_id="tenant-a", service="api-gateway", environment="prod", severity="critical",
            status="investigating", first_seen_at=datetime.now(UTC), projection_payload={},
        ))
        await session.commit()
        repo = IncidentRepository(session)
        from common.database import IncidentInvestigationBindingRecord
        binding = await session.get(IncidentInvestigationBindingRecord, recommendation_id)
        selection = await repo.persist_governed_resolution_selection(
            tenant_id="tenant-a", incident_id=incident_id, alert_id=alert_id,
            analysis_request_id=binding.analysis_request_id, context_snapshot_id=snapshot_id,
            context_fingerprint="d" * 64, recommendation_id=recommendation_id, rca_version=1,
            option=catalog_option(), selected_by="operator-a",
        )
        raw_plan = resolve_execution_plan(
            alert=Alert(
                id=alert_id, tenant_id="tenant-a", source="prometheus", name="KaiOpsServiceDown",
                service="api-gateway", environment="prod", severity=AlertSeverity.CRITICAL,
                description="API endpoint is unreachable", metadata={"incident_id": str(incident_id)},
            ),
            workflow_name="operator-resolution-selection", requires_approval=True,
            risk_tier="high", execution_mode="human-approval",
            resolution_hints="restart service", evidence_basis=["metric:up:api-gateway"],
            incident_id=incident_id, root_cause="api gateway process unavailable", confidence=0.91,
        )
        raw_plan.update({
            "plan_id": uuid5(NAMESPACE_URL, f"execution-plan:{selection['selection_id']}"),
            "recommendation_id": recommendation_id, "recommendation_version": str(recommendation_id),
            "rca_version": 1, "evidence_snapshot_id": snapshot_id,
            "context_fingerprint": "d" * 64, "resolution_selection_id": selection["selection_id"],
            "policy_version": "resolution-policy.v1", "policy_decision": {"decision": "hitl"},
        })
        plan = ExecutionPlanV2.model_validate(raw_plan).finalized().model_dump(mode="json")
        persisted = await repo.persist_compiled_execution_plan(
            selection_id=selection["selection_id"], plan=plan, blocking_reasons=[],
        )
        await session.commit()
        canonical = await repo.get_current_execution_plan_for_incident(
            tenant_id="tenant-a", incident_id=incident_id,
            recommendation_id=recommendation_id, rca_version=1,
        )
        projection = await session.get(IncidentProjectionRecord, incident_id)

    assert persisted and canonical
    assert projection.projection_payload["execution_plan"]["plan_id"] == canonical["plan_id"]
    assert projection.projection_payload["execution_plan"]["plan_fingerprint"] == canonical["plan_fingerprint"]

    approval_module = load_approval_module()
    approval_module.app.state.session_factory = sqlite_session_factory
    approval_module.settings.database_enabled = True
    approval_module.settings.service_internal_token = "test-internal-signing-key"
    metadata = {
        "rca_version": 1, "context_snapshot_id": str(snapshot_id), "context_fingerprint": "d" * 64,
        "resolution_selection": {**selection, "status": "compiled",
                                 "compiled_execution_plan_id": canonical["plan_id"]},
        "execution_plan": canonical, "runbook_status": "approved",
        "connection_profile": {"secret_ref": "vault://tenant-a/api-gateway"},
        "evidence_quality": {"evidence_coverage": 1.0, "citation_coverage": 1.0,
                             "evidence_fresh": True, "conflict_count": 0},
    }
    approval_module.PENDING_INCIDENTS[f"tenant-a:{incident_id}"] = {
        "tenant_id": "tenant-a", "incident_id": str(incident_id),
        "recommendation": {"id": str(recommendation_id), "incident_id": str(incident_id),
                           "tenant_id": "tenant-a", "metadata": metadata},
    }
    approval_module.ApprovalRequest.model_rebuild(_types_namespace={"UUID": UUID})
    request = approval_module.ApprovalRequest(
        incident_id=incident_id, recommendation_id=recommendation_id, tenant_id="tenant-a",
        plan_id=canonical["plan_id"], plan_fingerprint=canonical["plan_fingerprint"],
        approver="operator-a", approver_role="hitl-reviewer", authorization_scope="execution",
    )
    approval = await approval_module._approval_from_request(request, ApprovalDecision.APPROVED)
    assert str(approval.plan_id) == canonical["plan_id"]
    assert approval.plan_fingerprint == canonical["plan_fingerprint"]
    assert approval.metadata["execution_plan"]["plan_id"] == projection.projection_payload["execution_plan"]["plan_id"]


def test_cached_rca_cannot_be_rebound_to_different_evidence():
    module = load_resolution_module()
    prior = {
        "tenant_id": "tenant-a", "metadata": {
            "context_subject_fingerprint": "a" * 64, "context_fingerprint": "b" * 64,
            "service": "api-gateway", "environment": "prod", "deployment_id": "dep-1",
            "change_id": "change-1", "evidence_ids": ["evidence-old"],
            "evidence_content_checksums": {"evidence-old": "sha256:old"},
            "contradicting_evidence_ids": [],
        },
    }
    snapshot = {
        "tenant_id": "tenant-a", "subject_fingerprint": "a" * 64,
        "context_fingerprint": "b" * 64, "evidence_ids": ["evidence-new"],
        "evidence_checksums": {"evidence-new": "sha256:new"},
        "payload": {"alert": {"service": "api-gateway", "environment": "prod"},
                    "metadata": {"deployment_id": "dep-1", "change_id": "change-1",
                                 "investigation_report": {"conclusion": {"contradicting_evidence_ids": []}}}},
        "expires_at": datetime.now(UTC) + timedelta(minutes=10),
    }
    decision = module.validate_rca_reuse(prior, snapshot)
    assert decision.reusable is False
    assert {"evidence_ids_mismatch", "evidence_checksums_mismatch"}.issubset(decision.reasons)


def test_rca_persistence_rejects_evidence_outside_final_snapshot():
    module = load_resolution_module()
    recommendation = Recommendation(
        tenant_id="tenant-a", incident_id=uuid4(), root_cause="candidate cause", confidence=0.7,
        impact="service impact", recommended_action="collect validation", severity=AlertSeverity.HIGH,
        rationale="candidate", metadata={"evidence_ids": ["forged-evidence"]},
    )
    with pytest.raises(module.HTTPException) as mismatch:
        module._validate_recommendation_snapshot_evidence(
            recommendation, SimpleNamespace(evidence_ids=["bound-evidence"]),
        )
    assert mismatch.value.detail["code"] == "evidence_snapshot_mismatch"
