from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ResolutionPolicyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment: str
    risk: Literal["low", "medium", "high", "critical"]
    confidence: float = Field(ge=0.0, le=1.0)
    runbook_status: str
    runbook_success_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    mutating: bool
    reversible: bool
    canary_supported: bool
    blast_radius: str
    target_verified: bool
    validation_available: bool
    rollback_available: bool
    contradiction_count: int = Field(default=0, ge=0)
    database_change: bool = False
    rca_conclusive: bool = False


class ResolutionPolicyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_version: str = "kaims.resolution-policy.v1"
    decision: Literal["block", "investigate", "hitl", "hotl"]
    reason_codes: list[str]
    required_approver_role: str = "hitl-reviewer"
    max_targets: int = 1
    canary_required: bool = True
    stability_window_seconds: int = 300


def evaluate_resolution_policy(value: ResolutionPolicyInput) -> ResolutionPolicyDecision:
    reasons: list[str] = []
    if not value.mutating:
        return ResolutionPolicyDecision(
            decision="investigate",
            reason_codes=["diagnostic_only"],
            canary_required=False,
        )
    if not value.rca_conclusive or value.confidence < 0.60:
        return ResolutionPolicyDecision(
            decision="investigate",
            reason_codes=["rca_inconclusive" if not value.rca_conclusive else "confidence_below_recommendation_gate"],
            canary_required=False,
        )
    if value.runbook_status != "approved":
        reasons.append("runbook_not_approved")
    if not value.target_verified:
        reasons.append("target_not_verified")
    if not value.validation_available:
        reasons.append("validation_missing")
    if not value.rollback_available:
        reasons.append("rollback_missing")
    if value.contradiction_count:
        reasons.append("unresolved_contradictions")
    if reasons:
        return ResolutionPolicyDecision(decision="block", reason_codes=reasons, canary_required=False)

    hitl_reasons: list[str] = []
    if value.risk in {"high", "critical"}:
        hitl_reasons.append("high_risk_requires_hitl")
    if value.environment.lower() in {"prod", "production"} and value.database_change:
        hitl_reasons.append("production_database_change_requires_hitl")
    if value.confidence < 0.92:
        hitl_reasons.append("confidence_below_hotl_gate")
    if value.risk != "low":
        hitl_reasons.append("hotl_low_risk_only")
    if not value.reversible:
        hitl_reasons.append("action_not_reversible")
    if value.blast_radius != "single-service":
        hitl_reasons.append("blast_radius_requires_hitl")
    if not value.canary_supported:
        hitl_reasons.append("canary_not_supported")

    # P0 safety mode is deliberately fail-closed.  An environment variable is
    # not sufficient governance to activate autonomous production mutation.
    # A future release may add a separately reviewed policy version once the
    # HITL, validation, rollback, audit, and tenant-isolation acceptance gates
    # all pass; v1 can only recommend or require a human decision.
    hitl_reasons.append("hotl_disabled_p0_safety_mode")
    return ResolutionPolicyDecision(decision="hitl", reason_codes=list(dict.fromkeys(hitl_reasons)))
