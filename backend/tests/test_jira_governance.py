from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from common.context_enrichment_contract import HitlRoutingConfiguration, TicketClosurePolicy
from common.database import ExecutionPlanRecord, IncidentInvestigationBindingRecord
from common.hitl_routing import resolve_hitl_assignee
from common.jira_governance import (
    governed_jira_action,
    jira_webhook_event_id,
    kaims_may_close_ticket,
    validate_jira_approval,
)
from common.repository import ContextEnrichmentRepository


def routing() -> HitlRoutingConfiguration:
    return HitlRoutingConfiguration(
        default_approver_group="platform-approvers", l2_group="payments-l2",
        l3_group="payments-l3", service_owner="payments-owner-account-id",
        timezone="Asia/Calcutta", business_hours={}, severity_sla_minutes={"critical": 15},
        jira_project_key="KAN", jira_issue_type="Bug",
        jira_transition_mapping={"approved": "31", "rejected": "41"},
        fallback_assignment_group="platform-l2",
    )


@pytest.mark.asyncio
async def test_hitl_request_resolves_exact_service_owner_and_sla():
    incident_id = uuid4()
    assignment = await resolve_hitl_assignee(
        "tenant-a", SimpleNamespace(id=incident_id), "remediation", "critical", routing=routing(),
    )
    assert assignment.incident_id == incident_id
    assert assignment.assignee == "payments-owner-account-id"
    assert assignment.source == "service_owner"
    assert assignment.due_at <= datetime.now(UTC) + timedelta(minutes=16)


async def seed_identity(session):
    now = datetime.now(UTC)
    incident_id, alert_id, analysis_id = uuid4(), uuid4(), uuid4()
    snapshot_id, recommendation_id, selection_id, plan_id = uuid4(), uuid4(), uuid4(), uuid4()
    context_fingerprint, plan_fingerprint = "c" * 64, "sha256:" + "p" * 64
    session.add(IncidentInvestigationBindingRecord(
        tenant_id="tenant-a", project_id="project-a", incident_id=incident_id,
        alert_id=alert_id, analysis_request_id=analysis_id, context_snapshot_id=snapshot_id,
        context_fingerprint=context_fingerprint, recommendation_id=recommendation_id,
        rca_version=3, resolution_plan_id=selection_id, plan_fingerprint=plan_fingerprint,
        status="grounded", created_at=now, expires_at=now + timedelta(hours=1),
    ))
    session.add(ExecutionPlanRecord(
        id=plan_id, tenant_id="tenant-a", incident_id=incident_id,
        recommendation_id=recommendation_id, rca_version=3,
        context_snapshot_id=snapshot_id, context_fingerprint=context_fingerprint,
        resolution_selection_id=selection_id, policy_version="policy-v1",
        playbook_id="restart-service", schema_version="kaims.execution-plan.v2",
        fingerprint=plan_fingerprint, target_service="payments", target_environment="prod",
        risk_tier="MEDIUM", execution_mode="HITL", approval_required=True,
        execution_ready=True, readiness_blocks=[], plan_payload={"plan_id": str(plan_id)},
    ))
    await session.flush()
    return {
        "incident_id": incident_id, "recommendation_id": recommendation_id,
        "rca_version": 3, "context_snapshot_id": snapshot_id,
        "context_fingerprint": context_fingerprint, "resolution_selection_id": selection_id,
        "execution_plan_id": plan_id, "plan_fingerprint": plan_fingerprint,
    }


@pytest.mark.asyncio
async def test_jira_binding_preserves_full_identity_and_cross_tenant_lookup_fails(
    sqlite_session_factory,
):
    async with sqlite_session_factory() as session:
        identity = await seed_identity(session)
        repo = ContextEnrichmentRepository(session)
        binding = await repo.bind_jira_incident(
            tenant_id="tenant-a", jira_issue_key="KAN-42", jira_project_key="KAN",
            assignee_id="payments-owner-account-id", assignee_group=None,
            approval_expires_at=datetime.now(UTC) + timedelta(minutes=15),
            ownership="human", closure_policy={"ownership": "human", "kaims_may_close": False},
            **identity,
        )
        assert binding["execution_plan_id"] == str(identity["execution_plan_id"])
        assert await repo.get_jira_incident_binding(
            tenant_id="tenant-b", jira_issue_key="KAN-42", jira_project_key="KAN",
        ) is None


@pytest.mark.asyncio
async def test_duplicate_webhook_is_idempotent_and_unauthorized_actor_cannot_approve(
    sqlite_session_factory,
):
    payload = {
        "timestamp": 1, "webhookEvent": "jira:issue_updated",
        "issue": {"id": "42", "key": "KAN-42"}, "changelog": {"id": "99"},
    }
    async with sqlite_session_factory() as session:
        repo = ContextEnrichmentRepository(session)
        first, _ = await repo.record_jira_webhook_outcome(
            tenant_id="tenant-a", event_id=jira_webhook_event_id(payload),
            jira_issue_key="KAN-42", action="approved", actor_id="intruder",
            outcome="rejected", payload=payload,
        )
        duplicate, _ = await repo.record_jira_webhook_outcome(
            tenant_id="tenant-a", event_id=jira_webhook_event_id(payload),
            jira_issue_key="KAN-42", action="approved", actor_id="intruder",
            outcome="rejected", payload=payload,
        )
        assert first is True and duplicate is False
    valid, reason = validate_jira_approval(
        binding={"assignee_id": "authorized"}, actor_id="intruder", action="approved",
        current_identity={},
    )
    assert valid is False
    assert "not the assigned" in reason


def test_stale_plan_cannot_be_approved_and_arbitrary_comment_is_not_approval():
    binding = {
        "assignee_id": "authorized", "recommendation_id": "r1", "rca_version": 2,
        "context_snapshot_id": "s1", "context_fingerprint": "c1",
        "execution_plan_id": "p1", "plan_fingerprint": "f1",
        "approval_expires_at": datetime.now(UTC) + timedelta(minutes=5),
    }
    current = {**binding, "execution_plan_id": "p2"}
    valid, reason = validate_jira_approval(
        binding=binding, actor_id="authorized", action="approved", current_identity=current,
    )
    assert valid is False and "execution_plan_id changed" in reason
    assert governed_jira_action("In Progress", {"approved": "Approved"}) == "updated"


def test_ticket_closure_authority_is_fail_closed():
    ready_state = {
        "remediation_status": "succeeded", "validation_status": "passed",
        "required_validators_complete": True, "alerts_cleared": True,
        "stability_window_passed": True, "rollback_not_active": True,
        "critical_contradictions": [], "current_plan_matches_approved_plan": True,
    }
    human_policy = TicketClosurePolicy(ownership="human", kaims_may_close=False)
    assert kaims_may_close_ticket(human_policy, ready_state)[0] is False
    kaims_policy = TicketClosurePolicy(ownership="kaims", kaims_may_close=True)
    assert kaims_may_close_ticket(kaims_policy, ready_state) == (True, [])
    assert kaims_may_close_ticket(kaims_policy, {**ready_state, "alerts_cleared": False})[0] is False
