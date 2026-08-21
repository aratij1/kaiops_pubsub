from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from common.orchestration.outcome_validation import (
    OutcomeValidationDecision,
    RollbackDecision,
    ValidationObservation,
    decide_outcome_validation,
)


def test_validation_observation_requires_complete_digest() -> None:
    with pytest.raises(ValidationError, match="complete sha256"):
        ValidationObservation(
            execution_id=uuid4(),
            plan_fingerprint="sha256:short",
            validator_id="availability-1",
            connector_id="prometheus",
            target_resource_id="payments-api",
            observed_at=datetime.now(UTC),
            passed=True,
            result_checksum="sha256:short",
        )


def test_failed_validation_requires_approved_rollback_when_available() -> None:
    decision = decide_outcome_validation(
        execution_id=uuid4(),
        incident_id=uuid4(),
        plan_fingerprint=f"sha256:{'a' * 64}",
        target_resource_id="payments-api",
        execution_succeeded=True,
        integrity_preserved=True,
        checks={"availability_recovered": False},
        independent_checks_passed=False,
        stability_passed=False,
        stability_window_seconds=300,
        observation_ids=[f"sha256:{'b' * 64}"],
        rollback_action="kubectl rollout undo deployment/payments-api",
    )

    assert decision.outcome == "VALIDATION_FAILED"
    assert decision.closure_authorized is False
    assert decision.rollback.disposition == "REQUIRED"
    assert decision.rollback.rollback_action.startswith("kubectl rollout undo")


def test_stability_pending_observes_without_premature_rollback() -> None:
    decision = decide_outcome_validation(
        execution_id=uuid4(),
        incident_id=uuid4(),
        plan_fingerprint=f"sha256:{'c' * 64}",
        target_resource_id="payments-api",
        execution_succeeded=True,
        integrity_preserved=True,
        checks={"availability_recovered": True, "stability_window_completed": False},
        independent_checks_passed=True,
        stability_passed=False,
        stability_window_seconds=300,
        observation_ids=[],
        rollback_action="approved-rollback",
    )

    assert decision.outcome == "PENDING_STABILITY"
    assert decision.rollback.disposition == "OBSERVE"
    assert decision.closure_authorized is False


def test_integrity_failure_blocks_both_closure_and_automatic_rollback() -> None:
    decision = decide_outcome_validation(
        execution_id=uuid4(),
        incident_id=uuid4(),
        plan_fingerprint=f"sha256:{'d' * 64}",
        target_resource_id="payments-api",
        execution_succeeded=True,
        integrity_preserved=False,
        checks={},
        independent_checks_passed=False,
        stability_passed=False,
        stability_window_seconds=300,
        observation_ids=[],
        rollback_action="untrusted-rollback",
    )

    assert decision.outcome == "INTEGRITY_FAILED"
    assert decision.rollback.disposition == "BLOCKED"


def test_closure_cannot_be_authorized_for_failed_outcome() -> None:
    with pytest.raises(ValidationError, match="only for a recovered"):
        OutcomeValidationDecision(
            execution_id=uuid4(),
            incident_id=uuid4(),
            plan_fingerprint=f"sha256:{'e' * 64}",
            target_resource_id="payments-api",
            outcome="VALIDATION_FAILED",
            closure_authorized=True,
            stability_window_seconds=300,
            rollback=RollbackDecision(disposition="BLOCKED", reason_codes=["test"]),
        )
