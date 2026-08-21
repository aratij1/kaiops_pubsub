from uuid import uuid4

from closure_service.reconciliation import (
    ReconciliationDecision,
    assess_terminal_action,
    has_signed_recovery_proof,
)
from common.models import RemediationAction, RemediationStatus


def action(*, status: RemediationStatus, action_type: str = "restart_service", parameters: dict | None = None):
    return RemediationAction(
        tenant_id="tenant-a",
        incident_id=uuid4(),
        action_type=action_type,
        target="payments-api",
        status=status,
        parameters=parameters or {},
    )


def test_signed_recovery_contract_is_required_in_full():
    successful = action(
        status=RemediationStatus.SUCCEEDED,
        parameters={
            "execution_result": {
                "executed": True,
                "build_result": "SUCCESS",
                "recovery_validated": True,
                "recovery_evidence": {"executed": True, "recovery_validated": True},
            }
        },
    )
    incomplete = action(
        status=RemediationStatus.SUCCEEDED,
        parameters={"execution_result": {"build_result": "SUCCESS", "recovery_validated": True}},
    )

    assert has_signed_recovery_proof(successful) is True
    assert has_signed_recovery_proof(incomplete) is False


def test_success_without_recovery_proof_is_not_replayed():
    assessment = assess_terminal_action(action(status=RemediationStatus.SUCCEEDED), "approved")

    assert assessment.decision == ReconciliationDecision.REVALIDATE
    assert assessment.recovery_proof is False


def test_signed_success_and_diagnostic_completion_can_be_replayed():
    signed = action(
        status=RemediationStatus.SUCCEEDED,
        parameters={
            "execution_result": {
                "executed": True,
                "build_result": "SUCCESS",
                "recovery_validated": True,
                "recovery_evidence": {"executed": True, "recovery_validated": True},
            }
        },
    )
    diagnostic = action(
        status=RemediationStatus.SKIPPED,
        action_type="diagnostic_completion",
        parameters={"diagnostic_closure": True, "diagnostic_details": {"observed": "healthy"}},
    )

    assert assess_terminal_action(signed, "validating").decision == ReconciliationDecision.REPLAY
    assert assess_terminal_action(diagnostic, "investigating").decision == ReconciliationDecision.REPLAY


def test_terminal_incident_is_never_replayed():
    assessment = assess_terminal_action(action(status=RemediationStatus.SUCCEEDED), "closed")

    assert assessment.decision == ReconciliationDecision.IGNORE
    assert assessment.reason == "incident_already_terminal"
