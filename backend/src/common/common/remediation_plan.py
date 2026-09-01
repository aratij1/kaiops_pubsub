from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from common.tenant_identity import require_tenant_id


class AutonomyRecommendation(StrEnum):
    OBSERVE_ONLY = "OBSERVE_ONLY"
    RECOMMEND = "RECOMMEND"
    HITL_REQUIRED = "HITL_REQUIRED"
    AUTO_EXECUTE = "AUTO_EXECUTE"


class RemediationBlastRadius(StrEnum):
    RESOURCE = "resource"
    SINGLE_SERVICE = "single-service"
    MULTI_SERVICE = "multi-service"
    ENVIRONMENT = "environment"
    UNKNOWN = "unknown"


class RemediationPlan(BaseModel):
    """Capability-shaped Resolution Agent output; it never carries executable text."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["kaims.remediation-plan.v1"] = "kaims.remediation-plan.v1"
    incident_id: UUID
    tenant_id: str
    root_cause: str
    root_cause_confidence: float = Field(ge=0.0, le=1.0)
    supporting_evidence: list[str] = Field(default_factory=list)
    affected_resources: list[str] = Field(default_factory=list)
    blast_radius: RemediationBlastRadius = RemediationBlastRadius.UNKNOWN
    business_impact: str
    recommended_capability: str
    target_resource_id: str
    target_identity_verified: bool = False
    connector_id: str
    required_parameters: dict[str, Any] = Field(default_factory=dict)
    preconditions: list[str] = Field(default_factory=list)
    validation_plan: list[str] = Field(default_factory=list)
    rollback_capability: str | None = None
    risk_score: int = Field(ge=0, le=100)
    autonomy_recommendation: AutonomyRecommendation

    @field_validator("tenant_id")
    @classmethod
    def tenant_must_be_verified(cls, value: str) -> str:
        return require_tenant_id(value, source="remediation plan identity")

    @field_validator(
        "root_cause", "business_impact", "recommended_capability",
        "target_resource_id", "connector_id",
    )
    @classmethod
    def require_identity(cls, value: str) -> str:
        value = str(value or "").strip()
        if not value:
            raise ValueError("remediation plan identity fields cannot be empty")
        return value

    @model_validator(mode="after")
    def forbid_command_shaped_parameters(self) -> "RemediationPlan":
        forbidden = {"command", "commands", "script", "scripts", "shell", "sql", "query", "url"}

        def inspect(value: Any, path: str = "required_parameters") -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    if str(key).strip().lower() in forbidden:
                        raise ValueError(f"{path}.{key} is executable text, not a capability parameter")
                    inspect(child, f"{path}.{key}")
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    inspect(child, f"{path}[{index}]")

        inspect(self.required_parameters)
        if self.autonomy_recommendation == AutonomyRecommendation.AUTO_EXECUTE and not self.target_identity_verified:
            raise ValueError("AUTO_EXECUTE requires a Digital Twin verified target identity")
        return self


class RemediationPlanAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    execution_eligible: bool
    required_approval_level: Literal["none", "hitl_approver", "admin"]
    reason_codes: list[str] = Field(default_factory=list)


def assess_remediation_plan(
    plan: RemediationPlan,
    registry: Any,
    *,
    environment: str,
) -> RemediationPlanAssessment:
    # Runtime-only imports keep the canonical wire model independent of the
    # orchestration package, which itself imports common.models.
    from common.capability_registry import ApprovalLevel, CapabilityTrustLevel
    from common.orchestration.safe_remediation import BlastRadiusScope

    reasons: list[str] = []
    try:
        decision = registry.evaluate(
            plan.recommended_capability,
            connector_id=plan.connector_id,
            environment=environment,
            blast_radius=BlastRadiusScope(plan.blast_radius.value),
            parameters=plan.required_parameters,
        )
    except KeyError:
        return RemediationPlanAssessment(
            valid=False,
            execution_eligible=False,
            required_approval_level=ApprovalLevel.ADMIN,
            reason_codes=["unregistered_capability"],
        )
    reasons.extend(decision.reason_codes)
    capability = decision.capability
    if not plan.target_identity_verified:
        reasons.append("target_identity_not_verified")
    if plan.target_resource_id not in plan.affected_resources:
        reasons.append("target_not_in_affected_resources")
    if not plan.supporting_evidence:
        reasons.append("supporting_evidence_missing")
    if capability.mutating and not plan.validation_plan:
        reasons.append("validation_plan_missing")
    if capability.rollback_capability != plan.rollback_capability:
        reasons.append("rollback_capability_mismatch")
    if plan.autonomy_recommendation == AutonomyRecommendation.AUTO_EXECUTE:
        if capability.trust_level != CapabilityTrustLevel.AUTONOMOUS:
            reasons.append("capability_not_autonomous")
        if capability.required_approval_level != ApprovalLevel.NONE:
            reasons.append("approval_required")
        if plan.root_cause_confidence < 0.9:
            reasons.append("confidence_below_autonomy_threshold")
        if plan.blast_radius == RemediationBlastRadius.UNKNOWN:
            reasons.append("blast_radius_unknown")
    return RemediationPlanAssessment(
        valid=not reasons,
        execution_eligible=not reasons and plan.autonomy_recommendation == AutonomyRecommendation.AUTO_EXECUTE,
        required_approval_level=decision.required_approval_level,
        reason_codes=list(dict.fromkeys(reasons)),
    )
