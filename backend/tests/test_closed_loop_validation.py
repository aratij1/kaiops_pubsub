from uuid import uuid4

import pytest

from common.orchestration.outcome_validation import (
    ValidationCheck,
    ValidationPlan,
    decide_closed_loop,
)


def plan(*, rollback="kubernetes.rollback_deployment", attempts=2):
    target = "k8s://cluster-a/prod/deployment/checkout"
    return ValidationPlan(
        execution_id=uuid4(),
        incident_id=uuid4(),
        plan_fingerprint=f"sha256:{'a' * 64}",
        target_resource_id=target,
        checks=[
            ValidationCheck(
                check_id="original-alert", signal="original_alert", connector_id="prometheus",
                target_resource_id=target, check_reference="validator://alert/checkout-5xx",
                expected_condition="inactive", independent=True,
            ),
            ValidationCheck(
                check_id="synthetic", signal="synthetic_probe", connector_id="synthetics",
                target_resource_id=target, check_reference="validator://synthetic/checkout",
                expected_condition="2xx", independent=True,
            ),
        ],
        rollback_capability=rollback,
        maximum_autonomous_attempts=attempts,
    )


def test_execution_success_remains_pending_until_stability_window():
    decision = decide_closed_loop(
        plan(), execution_succeeded=True,
        observations={"original-alert": True, "synthetic": True},
        stability_window_complete=False, attempt=1,
    )
    assert decision.state == "EXECUTION_SUCCEEDED_VALIDATION_PENDING"
    assert decision.closure_authorized is False


def test_all_checks_and_stability_authorize_closure():
    decision = decide_closed_loop(
        plan(), execution_succeeded=True,
        observations={"original-alert": True, "synthetic": True},
        stability_window_complete=True, attempt=1,
    )
    assert decision.state == "VALIDATION_SUCCEEDED"
    assert decision.next_action == "CLOSE"


def test_failed_validation_uses_registered_rollback_capability():
    decision = decide_closed_loop(
        plan(), execution_succeeded=True,
        observations={"original-alert": False, "synthetic": True},
        stability_window_complete=True, attempt=1,
    )
    assert decision.next_action == "ROLLBACK"
    assert decision.rollback_capability == "kubernetes.rollback_deployment"


def test_successful_rollback_requires_fresh_evidence_and_rca():
    decision = decide_closed_loop(
        plan(), execution_succeeded=True, observations={}, stability_window_complete=False,
        attempt=1, rollback_attempted=True, rollback_succeeded=True,
    )
    assert decision.state == "ROLLED_BACK"
    assert decision.next_action == "RECOLLECT_EVIDENCE"


def test_loop_escalates_at_attempt_limit_without_rollback():
    decision = decide_closed_loop(
        plan(rollback=None), execution_succeeded=True,
        observations={"original-alert": False}, stability_window_complete=True, attempt=2,
    )
    assert decision.state == "ESCALATED"
    assert "maximum_autonomous_attempts_reached" in decision.reason_codes


def test_attempt_cannot_exceed_plan_limit():
    with pytest.raises(ValueError, match="autonomous limit"):
        decide_closed_loop(
            plan(), execution_succeeded=True, observations={},
            stability_window_complete=False, attempt=3,
        )
