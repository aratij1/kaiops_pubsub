from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ValidationOutcome(StrEnum):
    RECOVERED = "RECOVERED"
    PENDING_STABILITY = "PENDING_STABILITY"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    INTEGRITY_FAILED = "INTEGRITY_FAILED"


class ValidationSignal(StrEnum):
    ORIGINAL_ALERT = "original_alert"
    SERVICE_HEALTH = "service_health"
    METRIC = "metric"
    LOG = "log"
    TRACE = "trace"
    SLO = "slo"
    DEPENDENCY_HEALTH = "dependency_health"
    SYNTHETIC_PROBE = "synthetic_probe"


class ClosedLoopState(StrEnum):
    EXECUTION_SUCCEEDED_VALIDATION_PENDING = "EXECUTION_SUCCEEDED_VALIDATION_PENDING"
    VALIDATION_SUCCEEDED = "VALIDATION_SUCCEEDED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    ROLLED_BACK = "ROLLED_BACK"
    ESCALATED = "ESCALATED"


class ClosedLoopAction(StrEnum):
    OBSERVE = "OBSERVE"
    CLOSE = "CLOSE"
    ROLLBACK = "ROLLBACK"
    RECOLLECT_EVIDENCE = "RECOLLECT_EVIDENCE"
    ESCALATE_TO_HITL = "ESCALATE_TO_HITL"


class ValidationCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check_id: str
    signal: ValidationSignal
    connector_id: str
    target_resource_id: str
    check_reference: str
    expected_condition: str
    required: bool = True
    independent: bool = True

    @field_validator("check_id", "connector_id", "target_resource_id", "check_reference", "expected_condition")
    @classmethod
    def require_check_identity(cls, value: str) -> str:
        value = str(value or "").strip()
        if not value:
            raise ValueError("validation check identity is required")
        return value


class ValidationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["kaims.validation-plan.v1"] = "kaims.validation-plan.v1"
    execution_id: UUID
    incident_id: UUID
    plan_fingerprint: str
    target_resource_id: str
    checks: list[ValidationCheck]
    stability_window_seconds: int = Field(default=300, ge=60, le=86400)
    maximum_autonomous_attempts: int = Field(default=2, ge=1, le=3)
    rollback_capability: str | None = None

    @field_validator("plan_fingerprint")
    @classmethod
    def require_plan_digest(cls, value: str) -> str:
        value = str(value or "").strip().lower()
        if not value.startswith("sha256:") or len(value) != 71:
            raise ValueError("a complete sha256 plan fingerprint is required")
        return value

    @model_validator(mode="after")
    def require_independent_recovery_evidence(self) -> "ValidationPlan":
        required = [check for check in self.checks if check.required]
        if not required:
            raise ValueError("validation plan requires at least one required check")
        if not any(check.signal == ValidationSignal.ORIGINAL_ALERT for check in required):
            raise ValueError("validation plan must evaluate the original alert state")
        if not any(check.independent for check in required):
            raise ValueError("validation plan requires an independent recovery check")
        if any(check.target_resource_id != self.target_resource_id for check in self.checks):
            raise ValueError("all validation checks must bind to the execution target")
        return self


class ClosedLoopDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["kaims.closed-loop-decision.v1"] = "kaims.closed-loop-decision.v1"
    state: ClosedLoopState
    next_action: ClosedLoopAction
    closure_authorized: bool
    attempt: int = Field(ge=1, le=3)
    reason_codes: list[str]
    failed_checks: list[str] = Field(default_factory=list)
    missing_checks: list[str] = Field(default_factory=list)
    rollback_capability: str | None = None

    @model_validator(mode="after")
    def closure_only_after_validation(self) -> "ClosedLoopDecision":
        if self.closure_authorized != (self.state == ClosedLoopState.VALIDATION_SUCCEEDED):
            raise ValueError("closure is authorized only after validation succeeds")
        if self.next_action == ClosedLoopAction.ROLLBACK and not self.rollback_capability:
            raise ValueError("rollback requires a registered rollback capability")
        return self


def decide_closed_loop(
    plan: ValidationPlan,
    *,
    execution_succeeded: bool,
    observations: dict[str, bool],
    stability_window_complete: bool,
    attempt: int,
    rollback_attempted: bool = False,
    rollback_succeeded: bool = False,
) -> ClosedLoopDecision:
    if attempt < 1 or attempt > plan.maximum_autonomous_attempts:
        raise ValueError("attempt is outside the validation plan's autonomous limit")
    required_ids = {check.check_id for check in plan.checks if check.required}
    missing = sorted(required_ids - observations.keys())
    failed = sorted(check_id for check_id in required_ids if observations.get(check_id) is False)
    reasons: list[str] = []
    if rollback_attempted:
        if rollback_succeeded:
            return ClosedLoopDecision(
                state=ClosedLoopState.ROLLED_BACK,
                next_action=ClosedLoopAction.RECOLLECT_EVIDENCE,
                closure_authorized=False,
                attempt=attempt,
                reason_codes=["registered_rollback_completed", "fresh_rca_required"],
                failed_checks=failed,
                missing_checks=missing,
                rollback_capability=plan.rollback_capability,
            )
        return ClosedLoopDecision(
            state=ClosedLoopState.ESCALATED,
            next_action=ClosedLoopAction.ESCALATE_TO_HITL,
            closure_authorized=False,
            attempt=attempt,
            reason_codes=["registered_rollback_failed"],
            failed_checks=failed,
            missing_checks=missing,
            rollback_capability=plan.rollback_capability,
        )
    if not execution_succeeded:
        reasons.append("execution_did_not_succeed")
    if missing:
        reasons.append("required_validation_evidence_missing")
    if failed:
        reasons.append("recovery_checks_failed")
    if execution_succeeded and not missing and not failed and not stability_window_complete:
        return ClosedLoopDecision(
            state=ClosedLoopState.EXECUTION_SUCCEEDED_VALIDATION_PENDING,
            next_action=ClosedLoopAction.OBSERVE,
            closure_authorized=False,
            attempt=attempt,
            reason_codes=["stability_window_incomplete"],
        )
    if execution_succeeded and not missing and not failed and stability_window_complete:
        return ClosedLoopDecision(
            state=ClosedLoopState.VALIDATION_SUCCEEDED,
            next_action=ClosedLoopAction.CLOSE,
            closure_authorized=True,
            attempt=attempt,
            reason_codes=["all_required_recovery_checks_passed"],
        )
    if plan.rollback_capability:
        return ClosedLoopDecision(
            state=ClosedLoopState.VALIDATION_FAILED,
            next_action=ClosedLoopAction.ROLLBACK,
            closure_authorized=False,
            attempt=attempt,
            reason_codes=reasons,
            failed_checks=failed,
            missing_checks=missing,
            rollback_capability=plan.rollback_capability,
        )
    if attempt < plan.maximum_autonomous_attempts:
        return ClosedLoopDecision(
            state=ClosedLoopState.VALIDATION_FAILED,
            next_action=ClosedLoopAction.RECOLLECT_EVIDENCE,
            closure_authorized=False,
            attempt=attempt,
            reason_codes=[*reasons, "fresh_hypotheses_required"],
            failed_checks=failed,
            missing_checks=missing,
        )
    return ClosedLoopDecision(
        state=ClosedLoopState.ESCALATED,
        next_action=ClosedLoopAction.ESCALATE_TO_HITL,
        closure_authorized=False,
        attempt=attempt,
        reason_codes=[*reasons, "maximum_autonomous_attempts_reached"],
        failed_checks=failed,
        missing_checks=missing,
    )


class RollbackDisposition(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    OBSERVE = "OBSERVE"
    REQUIRED = "REQUIRED"
    BLOCKED = "BLOCKED"


class ValidationObservation(BaseModel):
    """Immutable validator result bound to one execution, plan, and target."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["kaims.validation-observation.v1"] = "kaims.validation-observation.v1"
    execution_id: UUID
    plan_fingerprint: str
    validator_id: str
    connector_id: str
    target_resource_id: str
    observed_at: datetime
    passed: bool
    result_checksum: str

    @field_validator("plan_fingerprint", "result_checksum")
    @classmethod
    def require_sha256(cls, value: str) -> str:
        value = str(value or "").strip().lower()
        if not value.startswith("sha256:") or len(value) != 71:
            raise ValueError("a complete sha256 digest is required")
        return value


class RollbackDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["kaims.rollback-decision.v1"] = "kaims.rollback-decision.v1"
    disposition: RollbackDisposition
    reason_codes: list[str]
    rollback_action: str | None = None
    requires_human_approval: bool = True

    @model_validator(mode="after")
    def required_rollback_has_registered_action(self) -> "RollbackDecision":
        if self.disposition == RollbackDisposition.REQUIRED and not self.rollback_action:
            raise ValueError("required rollback must reference the approved rollback action")
        return self


class OutcomeValidationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["kaims.outcome-validation.v1"] = "kaims.outcome-validation.v1"
    execution_id: UUID
    incident_id: UUID
    plan_fingerprint: str
    target_resource_id: str
    outcome: ValidationOutcome
    closure_authorized: bool
    observation_ids: list[str] = Field(default_factory=list)
    failed_checks: list[str] = Field(default_factory=list)
    stability_window_seconds: int = Field(ge=60, le=86400)
    rollback: RollbackDecision

    @model_validator(mode="after")
    def closure_requires_recovery(self) -> "OutcomeValidationDecision":
        if self.closure_authorized != (self.outcome == ValidationOutcome.RECOVERED):
            raise ValueError("closure is authorized only for a recovered outcome")
        return self


def decide_outcome_validation(
    *,
    execution_id: UUID,
    incident_id: UUID,
    plan_fingerprint: str,
    target_resource_id: str,
    execution_succeeded: bool,
    integrity_preserved: bool,
    checks: dict[str, bool],
    independent_checks_passed: bool,
    stability_passed: bool,
    stability_window_seconds: int,
    observation_ids: list[str],
    rollback_action: str | None,
) -> OutcomeValidationDecision:
    failed = sorted(name for name, passed in checks.items() if passed is not True)
    if not integrity_preserved:
        outcome = ValidationOutcome.INTEGRITY_FAILED
        rollback = RollbackDecision(
            disposition=RollbackDisposition.BLOCKED,
            reason_codes=["approved_plan_integrity_failed", "operator_escalation_required"],
        )
    elif not execution_succeeded:
        outcome = ValidationOutcome.EXECUTION_FAILED
        rollback = RollbackDecision(
            disposition=RollbackDisposition.REQUIRED if rollback_action else RollbackDisposition.BLOCKED,
            reason_codes=["execution_failed"],
            rollback_action=rollback_action,
        )
    elif independent_checks_passed and not stability_passed:
        outcome = ValidationOutcome.PENDING_STABILITY
        rollback = RollbackDecision(
            disposition=RollbackDisposition.OBSERVE,
            reason_codes=["stability_window_incomplete"],
        )
    elif not independent_checks_passed or failed:
        outcome = ValidationOutcome.VALIDATION_FAILED
        rollback = RollbackDecision(
            disposition=RollbackDisposition.REQUIRED if rollback_action else RollbackDisposition.BLOCKED,
            reason_codes=["independent_recovery_validation_failed"],
            rollback_action=rollback_action,
        )
    else:
        outcome = ValidationOutcome.RECOVERED
        rollback = RollbackDecision(
            disposition=RollbackDisposition.NOT_REQUIRED,
            reason_codes=["recovery_criteria_satisfied"],
            requires_human_approval=False,
        )
    return OutcomeValidationDecision(
        execution_id=execution_id,
        incident_id=incident_id,
        plan_fingerprint=plan_fingerprint,
        target_resource_id=target_resource_id,
        outcome=outcome,
        closure_authorized=outcome == ValidationOutcome.RECOVERED,
        observation_ids=observation_ids,
        failed_checks=failed,
        stability_window_seconds=stability_window_seconds,
        rollback=rollback,
    )
