from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ResolutionOutcome(StrEnum):
    UNKNOWN = "UNKNOWN"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"
    UNSUPPORTED_ACTION = "UNSUPPORTED_ACTION"
    CONNECTOR_FAILURE = "CONNECTOR_FAILURE"
    MODEL_FAILURE = "MODEL_FAILURE"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    EVIDENCE_SUPPORTED = "EVIDENCE_SUPPORTED"


class HypothesisStatus(StrEnum):
    PROPOSED = "PROPOSED"
    TESTING = "TESTING"
    SUPPORTED = "SUPPORTED"
    REJECTED = "REJECTED"
    INCONCLUSIVE = "INCONCLUSIVE"


class ClaimKind(StrEnum):
    CAUSAL = "CAUSAL"
    IMPACT = "IMPACT"


class ClaimStatus(StrEnum):
    OBSERVED = "OBSERVED"
    HYPOTHESIS = "HYPOTHESIS"
    GROUNDED = "GROUNDED"
    REFUTED = "REFUTED"
    NOT_ESTABLISHED = "NOT_ESTABLISHED"


class EvidenceBoundClaim(BaseModel):
    """One auditable assertion; confidence never substitutes for evidence."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "kaims.evidence-bound-claim.v1"
    claim_id: str
    kind: ClaimKind
    status: ClaimStatus
    statement: str = Field(min_length=1)
    source: str = "agent"
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    falsification_test: str = ""
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_grounding(self) -> "EvidenceBoundClaim":
        overlap = set(self.supporting_evidence_ids) & set(self.contradicting_evidence_ids)
        if overlap:
            raise ValueError(f"evidence cannot both support and contradict a claim: {sorted(overlap)}")
        if self.status == ClaimStatus.GROUNDED:
            if len(set(self.supporting_evidence_ids)) < 2:
                raise ValueError("a grounded claim requires at least two supporting evidence items")
            if self.contradicting_evidence_ids:
                raise ValueError("a grounded claim cannot retain unresolved contradicting evidence")
        if self.status in {ClaimStatus.HYPOTHESIS, ClaimStatus.NOT_ESTABLISHED} and not self.falsification_test:
            raise ValueError("an unconfirmed claim requires a falsification test")
        return self


class InvestigationToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str
    objective: str
    source_type: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    read_only: bool = True


class InvestigationPlan(BaseModel):
    """Immutable, auditable plan produced before investigation tools run."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "kaims.investigation-plan.v1"
    investigation_id: UUID
    incident_id: UUID
    correlation_id: str
    objectives: list[str]
    questions_to_answer: list[str]
    required_evidence: list[str]
    recommended_tool_calls: list[InvestigationToolCall]
    investigation_priority: list[str]
    stop_conditions: list[str]
    max_steps: int = Field(ge=1, le=100)
    max_tool_calls: int = Field(ge=1, le=100)
    max_duration_seconds: int = Field(ge=1, le=3600)
    max_cost_usd: float = Field(ge=0.0, le=1000.0)
    minimum_confidence: float = Field(ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Hypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "kaims.hypothesis.v1"
    hypothesis_id: str = Field(default_factory=lambda: str(uuid4()))
    incident_id: UUID
    correlation_id: str
    title: str
    description: str
    suspected_component: str
    suspected_change: str | None = None
    probability: float = Field(ge=0.0, le=1.0)
    status: HypothesisStatus = HypothesisStatus.PROPOSED
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    required_tests: list[str] = Field(default_factory=list)
    reasoning_summary: str = ""
    confidence_factors: dict[str, float] = Field(default_factory=dict)
    confidence_penalties: dict[str, float] = Field(default_factory=dict)
    affected_resource_ids: list[str] = Field(default_factory=list)
    causal_path: list[str] = Field(default_factory=list)
    recommended_next_diagnostic: str = ""

    @model_validator(mode="after")
    def evidence_is_disjoint(self) -> "Hypothesis":
        overlap = set(self.supporting_evidence_ids) & set(self.contradicting_evidence_ids)
        if overlap:
            raise ValueError(f"evidence cannot both support and contradict a hypothesis: {sorted(overlap)}")
        return self


class ResolutionOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "kaims.resolution-option.v1"
    option_id: str
    incident_id: UUID
    correlation_id: str
    title: str
    objective: str
    action_type: str
    target: dict[str, Any]
    reasoning: str
    supporting_evidence_ids: list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    estimated_success_probability: float = Field(ge=0.0, le=1.0)
    risk_level: str
    estimated_recovery_time: str | None = None
    blast_radius: dict[str, Any] = Field(default_factory=dict)
    preconditions: list[dict[str, Any]] = Field(default_factory=list)
    validation_plan: list[dict[str, Any]] = Field(default_factory=list)
    rollback_plan: dict[str, Any] | None = None
    automation_eligibility: str


class RCAResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "kaims.rca-result.v2"
    incident_id: UUID
    correlation_id: str
    outcome: ResolutionOutcome
    root_cause: str | None = None
    leading_hypothesis_id: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    factors: dict[str, float] = Field(default_factory=dict)
    penalties: dict[str, float] = Field(default_factory=dict)
    missing_evidence: list[str] = Field(default_factory=list)
    claims: list[EvidenceBoundClaim] = Field(default_factory=list)
    resolution_options: list[ResolutionOption] = Field(default_factory=list)

    @model_validator(mode="after")
    def supported_results_require_proof(self) -> "RCAResult":
        if self.outcome == ResolutionOutcome.EVIDENCE_SUPPORTED:
            if not self.root_cause or not self.leading_hypothesis_id:
                raise ValueError("evidence-supported RCA requires a root cause and leading hypothesis")
            if len(set(self.supporting_evidence_ids)) < 2:
                raise ValueError("evidence-supported RCA requires at least two supporting evidence items")
            if self.claims and not any(
                claim.kind == ClaimKind.CAUSAL and claim.status == ClaimStatus.GROUNDED
                for claim in self.claims
            ):
                raise ValueError("evidence-supported RCA requires a grounded causal claim")
        elif self.root_cause:
            raise ValueError("non-conclusive RCA outcomes must not assert a root cause")
        return self
