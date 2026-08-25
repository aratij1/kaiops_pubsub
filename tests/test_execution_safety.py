from __future__ import annotations

from uuid import uuid4

import pytest

from common.execution_safety import ExecutionSafetyDecision, assess_execution_safety, hash_snapshot
from common.models import Approval, ApprovalDecision, RemediationAction, RemediationStatus
from remediation_engine import RemediationEngine


def _approved_action(action_type: str = "restart_pod") -> RemediationAction:
    return RemediationAction(
        incident_id=uuid4(),
        approval_id=uuid4(),
        action_type=action_type,
        target="orders",
        status=RemediationStatus.RUNNING,
    )


def test_snapshot_hash_is_stable_and_bound_to_action() -> None:
    action = _approved_action()
    assessment = assess_execution_safety(action, allowlisted_actions={"restart_pod"})
    assert assessment.decision == ExecutionSafetyDecision.ALLOW
    assert assessment.snapshot_hash == hash_snapshot(assessment.snapshot)
    assert assessment.snapshot["action_type"] == "restart_pod"
    assert assessment.snapshot["target"] == "orders"


def test_unknown_action_type_fails_closed() -> None:
    action = _approved_action("arbitrary_shell")
    assessment = assess_execution_safety(action, allowlisted_actions={"restart_pod"})
    assert assessment.decision == ExecutionSafetyDecision.BLOCK
    assert assessment.reason == "ACTION_TYPE_NOT_ALLOWLISTED"


def test_unapproved_action_requires_explicit_auto_authorization() -> None:
    action = RemediationAction(
        incident_id=uuid4(),
        action_type="restart_pod",
        target="orders",
        status=RemediationStatus.RUNNING,
    )
    assessment = assess_execution_safety(action, allowlisted_actions={"restart_pod"})
    assert assessment.decision == ExecutionSafetyDecision.BLOCK
    assert assessment.reason == "APPROVAL_OR_AUTO_AUTHORIZATION_REQUIRED"
    action.metadata["auto_execution_authorized"] = True
    assert assess_execution_safety(action, allowlisted_actions={"restart_pod"}).decision == ExecutionSafetyDecision.ALLOW


@pytest.mark.asyncio
async def test_engine_does_not_fallback_unknown_action_to_api_execution() -> None:
    engine = RemediationEngine()
    action = _approved_action("arbitrary_shell")
    result = await engine.execute(action)
    assert result.status == RemediationStatus.SKIPPED
    assert result.error == "ACTION_TYPE_NOT_ALLOWLISTED"
    assert "executed REST API remediation" not in result.output


@pytest.mark.asyncio
async def test_engine_attaches_execution_provenance_before_plugin_call() -> None:
    engine = RemediationEngine()
    action = _approved_action("restart_pod")
    result = await engine.execute(action)
    assert result.status == RemediationStatus.SUCCEEDED
    assert result.parameters["pre_execution_snapshot_hash"]
    assert result.parameters["execution_idempotency_key"].startswith("remediation:")


def test_build_action_binds_real_approval_id() -> None:
    approval = Approval(
        incident_id=uuid4(),
        recommendation_id=uuid4(),
        decision=ApprovalDecision.APPROVED,
        approver="reviewer@example.com",
        comment="restart pod",
    )
    action = RemediationEngine().build_action(approval)
    assert action.approval_id == approval.id
    assert action.action_type == "restart_pod"
