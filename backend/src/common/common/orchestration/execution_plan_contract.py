from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from common.tenant_identity import require_tenant_id

SCHEMA_VERSION = "kaims.execution-plan.v2"
_PLAN_NAMESPACE = UUID("f863e8a9-0e87-47b0-8324-f6896a149683")
_FINGERPRINT_EXCLUDES = {"generated_at", "plan_fingerprint", "idempotency_key"}


def _required_text(value: str, *, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    return normalized


class RetryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_attempts: int = Field(default=1, ge=1, le=3)
    retry_safe: bool = False
    backoff_seconds: float = Field(default=0.0, ge=0.0, le=300.0)


class PlanAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str
    connector_id: str
    target_resource_id: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=300, ge=1, le=3600)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    expected_outcome: str
    validation: list[str] = Field(default_factory=list)
    rollback_action: str | None = None
    reversible: bool = False
    blast_radius: str = "single-service"
    required_permissions: list[str] = Field(default_factory=list)

    @field_validator("action_id", "connector_id", "target_resource_id", "expected_outcome")
    @classmethod
    def require_identity(cls, value: str, info: Any) -> str:
        return _required_text(value, field=info.field_name)


class ApprovalPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["recommend_only", "hitl_required", "denied"]
    required_approver_role: Literal["admin", "hitl-reviewer"] = "hitl-reviewer"
    reason_codes: list[str] = Field(default_factory=list)
    approval_expiry_seconds: int = Field(default=900, ge=60, le=86400)


class ExecutionPlanV2(BaseModel):
    """Canonical execution plan; flat command fields are temporary v1 consumer projections."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["kaims.execution-plan.v2"] = SCHEMA_VERSION
    version: Literal["execution-plan-v2"] = "execution-plan-v2"
    plan_id: UUID
    incident_id: UUID
    tenant_id: str
    service: str
    environment: str
    generated_at: datetime
    source: str
    evidence_references: list[str] = Field(default_factory=list)
    root_cause: str
    confidence: float = Field(ge=0.0, le=1.0)
    risk: Literal["low", "medium", "high", "critical"]
    actions: list[PlanAction] = Field(default_factory=list)
    preflight: list[str] = Field(default_factory=list)
    validation: list[str] = Field(default_factory=list)
    rollback: list[str] = Field(default_factory=list)
    approval_policy: ApprovalPolicy
    plan_fingerprint: str = ""
    expiry: datetime
    idempotency_key: str = ""

    # Explicit compatibility projection consumed by existing services.
    workflow: str
    alert: dict[str, Any]
    risk_tier: str
    execution_mode: str
    requires_approval: bool
    approval_required: bool
    connection: dict[str, Any]
    playbook: dict[str, Any]
    playbook_id: str
    runbook_governance_id: UUID | None = None
    runbook_checksum: str | None = None
    playbook_version: int | None = None
    runbook_status: str
    connector_id: str
    remediation_target: str
    mutating: bool
    plan_kind: Literal["diagnostic", "remediation"]
    diagnostic_only: bool
    execution_ready: bool
    readiness_blocks: list[str] = Field(default_factory=list)
    preflight_commands: list[str] = Field(default_factory=list)
    commands: list[str] = Field(default_factory=list)
    validation_commands: list[str] = Field(default_factory=list)
    validation_endpoints: list[dict[str, Any]] = Field(default_factory=list)
    required_validation_kinds: list[str] = Field(default_factory=lambda: [
        "availability", "alert_clearance", "error_rate", "latency", "dependency_health", "critical_alerts"
    ])
    stability_window_seconds: int = Field(default=300, ge=60, le=3600)
    rollback_commands: list[str] = Field(default_factory=list)
    rollback_mode: str
    queries: list[str] = Field(default_factory=list)
    scripts: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    evidence_basis: list[str] = Field(default_factory=list)
    classification: dict[str, Any] = Field(default_factory=dict)
    investigation_report: dict[str, Any] = Field(default_factory=dict)
    historical_precedents: list[dict[str, Any]] = Field(default_factory=list)
    investigation_status: str | None = None
    investigation_id: str | None = None
    next_evidence: list[Any] = Field(default_factory=list)
    policy_decision: dict[str, Any] = Field(default_factory=dict)

    @field_validator("tenant_id")
    @classmethod
    def tenant_must_be_verified(cls, value: str) -> str:
        return require_tenant_id(value, source="execution plan identity")

    @field_validator("service", "environment", "source", "root_cause")
    @classmethod
    def require_core_text(cls, value: str, info: Any) -> str:
        return _required_text(value, field=info.field_name)

    @model_validator(mode="after")
    def enforce_mutation_safety(self) -> ExecutionPlanV2:
        if self.execution_ready and not self.actions:
            raise ValueError("execution-ready mutation requires typed actions")
        if self.execution_ready and (not self.validation or not self.rollback):
            raise ValueError("execution-ready mutation requires validation and rollback")
        if self.execution_ready and self.approval_policy.decision != "hitl_required":
            raise ValueError("P0 execution-ready plans require HITL")
        if self.commands != [str(action.inputs.get("catalog_command") or "") for action in self.actions]:
            raise ValueError("flat commands must be the exact typed-action compatibility projection")
        return self

    def canonical_fingerprint(self) -> str:
        return canonical_plan_fingerprint(self.model_dump(mode="json"))

    def finalized(self) -> ExecutionPlanV2:
        fingerprint = self.canonical_fingerprint()
        return self.model_copy(update={"plan_fingerprint": fingerprint, "idempotency_key": fingerprint})


def deterministic_plan_id(*, tenant_id: str, incident_id: UUID, playbook_id: str, target: str) -> UUID:
    material = ":".join((tenant_id, str(incident_id), playbook_id, target))
    return uuid5(_PLAN_NAMESPACE, material)


def canonical_plan_fingerprint(plan: dict[str, Any]) -> str:
    payload = {key: value for key, value in plan.items() if key not in _FINGERPRINT_EXCLUDES}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return f"sha256:{sha256(canonical.encode()).hexdigest()}"


def verify_plan_fingerprint(plan: dict[str, Any]) -> bool:
    supplied = str(plan.get("plan_fingerprint") or "")
    return bool(supplied) and supplied == canonical_plan_fingerprint(plan)


def utc_now() -> datetime:
    return datetime.now(UTC)
