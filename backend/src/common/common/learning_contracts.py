from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from common.models import utc_now
from common.tenant_identity import require_tenant_id


class AutonomyTier(StrEnum):
    SHADOW = "SHADOW"
    RECOMMENDATION = "RECOMMENDATION"
    HITL = "HITL"
    HOTL = "HOTL"


class PromotionDisposition(StrEnum):
    HOLD = "HOLD"
    PROMOTE = "PROMOTE"
    DEMOTE = "DEMOTE"


class IncidentMemoryRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["kaims.incident-memory.v1"] = "kaims.incident-memory.v1"
    memory_id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    incident_id: UUID
    service: str
    environment: str
    issue_signature: str
    root_cause: str | None
    resolution_option_id: str | None
    execution_id: UUID | None
    outcome: str
    validation_evidence_ids: list[str] = Field(default_factory=list)
    rollback_disposition: str
    operator_reviewed: bool
    negative_feedback: bool = False
    deployment_version: str | None = None
    recorded_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def memory_requires_reviewed_outcome(self) -> "IncidentMemoryRecord":
        require_tenant_id(self.tenant_id, source="incident memory")
        if not self.operator_reviewed:
            raise ValueError("incident memory must be operator reviewed")
        if self.outcome == "RECOVERED" and not self.validation_evidence_ids:
            raise ValueError("recovered memory requires validation evidence")
        return self


class OperatorCorrection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["kaims.operator-correction.v1"] = "kaims.operator-correction.v1"
    decision: Literal["approved", "rejected", "modified", "incorrect", "incomplete"]
    actor: str
    reason_category: str | None = None
    corrected_cause: str | None = None
    missing_evidence: str | None = None
    comment: str | None = None
    recorded_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def correction_requires_reason(self) -> "OperatorCorrection":
        if self.decision in {"rejected", "modified", "incorrect", "incomplete"} and not str(self.reason_category or "").strip():
            raise ValueError("non-approval correction requires reason_category")
        return self


class AgentOpsTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["kaims.agentops-trace.v1"] = "kaims.agentops-trace.v1"
    trace_id: str
    tenant_id: str
    incident_id: UUID
    agent: str
    model_provider: str | None = None
    model_name: str | None = None
    started_at: datetime
    completed_at: datetime
    tool_calls: int = Field(ge=0, le=10000)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    estimated_cost_usd: float = Field(default=0.0, ge=0.0)
    outcome: str
    fallback_used: bool = False
    error_code: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def trace_is_well_formed(self) -> "AgentOpsTrace":
        require_tenant_id(self.tenant_id, source="agentops trace")
        if self.completed_at < self.started_at:
            raise ValueError("agent trace completion cannot precede start")
        forbidden = {"api_key", "token", "password", "authorization", "credential"}
        if forbidden.intersection(str(key).lower() for key in self.attributes):
            raise ValueError("agent trace attributes cannot contain credential material")
        return self


class CalibrationSample(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confidence: float = Field(ge=0.0, le=1.0)
    correct: bool


class PromotionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["kaims.autonomy-promotion-evidence.v1"] = "kaims.autonomy-promotion-evidence.v1"
    tenant_id: str
    service: str
    action_type: str
    current_tier: AutonomyTier
    reviewed_attempts: int = Field(ge=0)
    successful_attempts: int = Field(ge=0)
    rollback_attempts: int = Field(ge=0)
    operator_corrections: int = Field(ge=0)
    critical_failures: int = Field(ge=0)
    calibration_samples: list[CalibrationSample] = Field(default_factory=list)
    approved_runbook: bool
    rollback_tested: bool
    credential_scope_verified: bool
    blast_radius_verified: bool

    @model_validator(mode="after")
    def counts_are_consistent(self) -> "PromotionEvidence":
        require_tenant_id(self.tenant_id, source="autonomy promotion evidence")
        if any(value > self.reviewed_attempts for value in (self.successful_attempts, self.rollback_attempts, self.operator_corrections)):
            raise ValueError("promotion counters cannot exceed reviewed attempts")
        return self


class AutonomyPromotionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["kaims.autonomy-promotion-decision.v1"] = "kaims.autonomy-promotion-decision.v1"
    disposition: PromotionDisposition
    current_tier: AutonomyTier
    recommended_tier: AutonomyTier
    reason_codes: list[str]
    metrics: dict[str, float]
    requires_human_approval: bool = True


def calibration_error(samples: list[CalibrationSample]) -> float:
    if not samples:
        return 1.0
    return sum(abs(sample.confidence - float(sample.correct)) for sample in samples) / len(samples)


def assess_autonomy_promotion(evidence: PromotionEvidence) -> AutonomyPromotionDecision:
    attempts = max(1, evidence.reviewed_attempts)
    success_rate = evidence.successful_attempts / attempts
    rollback_rate = evidence.rollback_attempts / attempts
    correction_rate = evidence.operator_corrections / attempts
    calibration = calibration_error(evidence.calibration_samples)
    metrics = {
        "success_rate": round(success_rate, 4),
        "rollback_rate": round(rollback_rate, 4),
        "operator_correction_rate": round(correction_rate, 4),
        "calibration_error": round(calibration, 4),
    }
    reasons: list[str] = []
    if evidence.critical_failures:
        reasons.append("critical_failure_requires_demotion")
    if evidence.reviewed_attempts < 30:
        reasons.append("minimum_30_reviewed_attempts_required")
    if success_rate < 0.95:
        reasons.append("success_rate_below_95_percent")
    if rollback_rate > 0.02:
        reasons.append("rollback_rate_above_2_percent")
    if correction_rate > 0.05:
        reasons.append("operator_correction_rate_above_5_percent")
    if calibration > 0.05 or len(evidence.calibration_samples) < 30:
        reasons.append("confidence_calibration_not_proven")
    for proven, reason in (
        (evidence.approved_runbook, "approved_runbook_required"),
        (evidence.rollback_tested, "rollback_test_required"),
        (evidence.credential_scope_verified, "credential_scope_required"),
        (evidence.blast_radius_verified, "blast_radius_verification_required"),
    ):
        if not proven:
            reasons.append(reason)
    order = [AutonomyTier.SHADOW, AutonomyTier.RECOMMENDATION, AutonomyTier.HITL, AutonomyTier.HOTL]
    current_index = order.index(evidence.current_tier)
    if evidence.critical_failures and current_index > 0:
        return AutonomyPromotionDecision(
            disposition=PromotionDisposition.DEMOTE,
            current_tier=evidence.current_tier,
            recommended_tier=order[current_index - 1],
            reason_codes=reasons,
            metrics=metrics,
        )
    # This phase deliberately stops at HITL. HOTL requires a later, separately
    # approved production-autonomy phase and cannot be inferred from statistics.
    if not reasons and current_index < order.index(AutonomyTier.HITL):
        return AutonomyPromotionDecision(
            disposition=PromotionDisposition.PROMOTE,
            current_tier=evidence.current_tier,
            recommended_tier=order[current_index + 1],
            reason_codes=["reviewed_evidence_thresholds_satisfied"],
            metrics=metrics,
        )
    if not reasons and evidence.current_tier == AutonomyTier.HITL:
        reasons.append("hotl_promotion_not_authorized_in_phase_5")
    return AutonomyPromotionDecision(
        disposition=PromotionDisposition.HOLD,
        current_tier=evidence.current_tier,
        recommended_tier=evidence.current_tier,
        reason_codes=reasons,
        metrics=metrics,
    )
