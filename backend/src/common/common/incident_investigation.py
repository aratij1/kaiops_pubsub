from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

INVESTIGATION_CONTRACT_VERSION = "kaiops.incident-investigation.v1"


def is_traceable_evidence_citation(value: Any) -> bool:
    citation = str(value or "").strip().lower()
    return bool(citation) and not citation.startswith(("context://", "unknown://", "unavailable://"))


class ContextQualityContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_count: int = Field(ge=0)
    category_coverage: float = Field(ge=0.0, le=1.0)
    rca_readiness_score: float = Field(default=0.0, ge=0.0, le=1.0)
    impact_readiness_score: float = Field(default=0.0, ge=0.0, le=1.0)
    rca_ready: bool = False
    impact_ready: bool = False
    freshness_score: float = Field(ge=0.0, le=1.0)
    provenance_score: float = Field(ge=0.0, le=1.0)
    independent_source_count: int = Field(ge=0)
    direct_observation_count: int = Field(ge=0)
    valid: bool
    blocking_reasons: list[str] = Field(default_factory=list)


class ContextSourceContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    connector: str = Field(min_length=1)
    status: Literal[
        "completed", "empty", "unavailable", "unauthorized",
        "misconfigured", "timed_out", "skipped",
    ]
    collected_at: datetime
    error: str | None = None


class ContextEvidenceContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    connector: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    service: str = Field(min_length=1)
    resource_id: str | None = None
    observed_at: datetime | None = None
    collected_at: datetime
    observation_window: dict[str, Any] | None = None
    freshness: Literal["fresh", "stale", "unknown"]
    provenance: dict[str, Any]
    citation: str = Field(min_length=1)
    epistemic_role: Literal["current_observation", "historical_knowledge", "operator_assertion"]
    current_observation: bool


class InvestigationReadinessContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context_ready: bool
    rca_ready: bool
    resolution_ready: bool
    approval_ready: bool
    execution_ready: bool
    validation_ready: bool
    closure_ready: bool
    blocking_reasons: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_monotonic_readiness(self) -> InvestigationReadinessContract:
        if self.closure_ready and not self.validation_ready:
            raise ValueError("closure readiness requires validation readiness")
        if self.validation_ready and not self.execution_ready:
            raise ValueError("validation readiness requires execution readiness")
        if self.execution_ready and not self.approval_ready:
            raise ValueError("execution readiness requires approval readiness")
        if self.approval_ready and not self.resolution_ready:
            raise ValueError("approval readiness requires resolution readiness")
        if self.resolution_ready and not self.rca_ready:
            raise ValueError("resolution readiness requires RCA readiness")
        if self.rca_ready and not self.context_ready:
            raise ValueError("RCA readiness requires context readiness")
        if not self.execution_ready and not self.blocking_reasons:
            raise ValueError("blocked execution requires at least one blocking reason")
        return self


class IncidentInvestigationContract(BaseModel):
    """Exact durable binding across context, RCA, plan, and execution stages."""

    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["kaiops.incident-investigation.v1"] = INVESTIGATION_CONTRACT_VERSION
    tenant_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    incident_id: UUID
    alert_id: UUID
    analysis_request_id: UUID
    context_snapshot_id: UUID
    context_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    context_contract_version: str = Field(min_length=1)
    context_collected_at: datetime
    context_expires_at: datetime
    context_quality: ContextQualityContract
    context_sources: list[ContextSourceContract]
    context_evidence: list[ContextEvidenceContract]
    investigation_id: UUID
    investigation_status: Literal["pending", "investigating", "conclusive", "inconclusive", "failed"]
    investigation_conclusive: bool
    rca_version: int = Field(ge=1)
    rca_status: Literal["pending", "grounded", "insufficient_evidence", "invalid_model_output", "inconclusive"]
    accepted_evidence_ids: list[str]
    missing_evidence: list[str]
    conflicting_evidence: list[str]
    recommendation_id: UUID | None = None
    resolution_plan_id: UUID | None = None
    plan_fingerprint: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    execution_ready: bool
    readiness_blocks: list[str]
    approval_status: Literal["not_ready", "pending", "approved", "rejected", "stale"]
    remediation_status: str
    validation_status: str
    readiness: InvestigationReadinessContract

    @model_validator(mode="after")
    def verify_cross_stage_integrity(self) -> IncidentInvestigationContract:
        evidence_ids = {item.evidence_id for item in self.context_evidence}
        if not set(self.accepted_evidence_ids).issubset(evidence_ids):
            raise ValueError("accepted RCA evidence must exist in the bound context snapshot")
        if self.context_expires_at <= self.context_collected_at:
            raise ValueError("context expiry must be after collection")
        if self.investigation_conclusive != (self.investigation_status == "conclusive"):
            raise ValueError("investigation conclusiveness contradicts investigation status")
        if self.rca_status == "grounded" and not self.accepted_evidence_ids:
            raise ValueError("grounded RCA requires accepted evidence")
        accepted = {
            item.evidence_id: item
            for item in self.context_evidence
            if item.evidence_id in self.accepted_evidence_ids
        }
        if any(not is_traceable_evidence_citation(item.citation) for item in accepted.values()):
            raise ValueError("accepted RCA evidence requires a traceable citation")
        if self.execution_ready != self.readiness.execution_ready:
            raise ValueError("execution readiness fields disagree")
        if self.execution_ready:
            if not self.investigation_conclusive or self.rca_status != "grounded":
                raise ValueError("execution requires a conclusive grounded RCA")
            if not all((self.recommendation_id, self.resolution_plan_id, self.plan_fingerprint)):
                raise ValueError("execution requires exact recommendation and plan bindings")
            if self.readiness_blocks:
                raise ValueError("execution-ready investigations cannot contain readiness blocks")
        return self
