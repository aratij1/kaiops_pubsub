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
