from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from common.execution_safety import ExecutionSafetyDecision, assess_execution_safety, hash_snapshot
from common.models import RemediationAction, RemediationStatus
from remediation_engine import RemediationEngine
from remediation_engine.plugins import FakeCapabilityAdapter


def _approved_action(action_type: str = "fake_test") -> RemediationAction:
    return RemediationAction(
        tenant_id="tenant-a",
        incident_id=uuid4(),
        approval_id=uuid4(),
        action_type=action_type,
        target="orders",
        parameters={
            "target_resource_id": "k8s://production/orders",
            "credential_ref": "vault://kaiops/orders",
            "approval_expires_at": "2099-01-01T00:00:00+00:00",
        },
        status=RemediationStatus.RUNNING,
    )


def test_snapshot_hash_is_stable_and_detached_from_action_mutation() -> None:
    action = _approved_action()
    assessment = assess_execution_safety(action, allowlisted_actions={"fake_test"})
    assert assessment.decision == ExecutionSafetyDecision.ALLOW
    assert assessment.snapshot_hash == hash_snapshot(assessment.snapshot)
    action.parameters["new_value"] = "must not alter evidence"
    assert "new_value" not in assessment.snapshot["parameters"]


def test_unknown_action_type_fails_closed() -> None:
    action = _approved_action("arbitrary_shell")
    assessment = assess_execution_safety(action, allowlisted_actions={"fake_test"})
    assert assessment.decision == ExecutionSafetyDecision.BLOCK
    assert assessment.reason == "ACTION_TYPE_NOT_ALLOWLISTED"


def test_unapproved_action_requires_explicit_auto_authorization() -> None:
    action = _approved_action()
    action.approval_id = None
    assessment = assess_execution_safety(action, allowlisted_actions={"fake_test"})
    assert assessment.reason == "APPROVAL_OR_AUTO_AUTHORIZATION_REQUIRED"
    action.metadata["auto_execution_authorized"] = True
    assert assess_execution_safety(action, allowlisted_actions={"fake_test"}).decision == ExecutionSafetyDecision.ALLOW


def test_expired_or_missing_approval_expiry_fails_closed() -> None:
    action = _approved_action()
    action.parameters.pop("approval_expires_at")
    assert assess_execution_safety(action, allowlisted_actions={"fake_test"}).reason == "APPROVAL_EXPIRY_MISSING"

    action.parameters["approval_expires_at"] = "2026-09-01T09:59:59+00:00"
    assessment = assess_execution_safety(
        action,
        allowlisted_actions={"fake_test"},
        now=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
    )
    assert assessment.reason == "APPROVAL_EXPIRED"


@pytest.mark.asyncio
async def test_engine_does_not_fallback_unknown_action_to_api_execution() -> None:
    engine = RemediationEngine(plugins={"fake_test": FakeCapabilityAdapter()})
    action = _approved_action("arbitrary_shell")
    result = await engine.execute(action)
    assert result.status == RemediationStatus.SKIPPED
    assert result.error == "ACTION_TYPE_NOT_ALLOWLISTED"


@pytest.mark.asyncio
async def test_engine_attaches_execution_provenance_before_plugin_call() -> None:
    engine = RemediationEngine(plugins={"fake_test": FakeCapabilityAdapter()})
    result = await engine.execute(_approved_action())
    assert result.status == RemediationStatus.SUCCEEDED
    assert result.parameters["pre_execution_snapshot_hash"]
    assert result.parameters["execution_idempotency_key"].startswith("remediation:")
