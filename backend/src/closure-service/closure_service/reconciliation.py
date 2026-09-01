from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from common.models import RemediationAction, RemediationStatus


class ReconciliationDecision(StrEnum):
    REPLAY = "replay"
    REVALIDATE = "revalidate"
    IGNORE = "ignore"


@dataclass(frozen=True)
class ReconciliationAssessment:
    decision: ReconciliationDecision
    reason: str
    recovery_proof: bool

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)


def has_signed_recovery_proof(action: RemediationAction) -> bool:
    """Require the complete executor recovery contract, not exit code alone."""

    execution_result = action.parameters.get("execution_result")
    execution_result = execution_result if isinstance(execution_result, dict) else {}
    evidence = execution_result.get("recovery_evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    return bool(
        action.status == RemediationStatus.SUCCEEDED
        and execution_result.get("executed") is True
        and str(execution_result.get("build_result") or "").upper() == "SUCCESS"
        and execution_result.get("recovery_validated") is True
        and evidence.get("executed") is True
        and evidence.get("recovery_validated") is True
    )


def assess_terminal_action(action: RemediationAction, projection_status: str | None) -> ReconciliationAssessment:
    """Classify persisted terminal work without changing external state.

    A succeeded executor record is not, by itself, permission to close an
    incident. It must carry signed recovery proof. Actions with only
    independent checks are surfaced for explicit revalidation rather than
    being silently replayed during process startup.
    """

    current_status = str(projection_status or "").strip().lower()
    if current_status in {"closed", "resolved", "cancelled", "canceled"}:
        return ReconciliationAssessment(ReconciliationDecision.IGNORE, "incident_already_terminal", False)

    diagnostic_completion = bool(
        action.status == RemediationStatus.SKIPPED
        and action.action_type == "diagnostic_completion"
        and action.parameters.get("diagnostic_closure") is True
    )
    if diagnostic_completion:
        return ReconciliationAssessment(ReconciliationDecision.REPLAY, "diagnostic_completion_evidence", True)
    if action.status != RemediationStatus.SUCCEEDED:
        return ReconciliationAssessment(ReconciliationDecision.IGNORE, "action_not_successful", False)
    if has_signed_recovery_proof(action):
        return ReconciliationAssessment(ReconciliationDecision.REPLAY, "signed_recovery_proof", True)
    return ReconciliationAssessment(ReconciliationDecision.REVALIDATE, "recovery_proof_missing", False)
