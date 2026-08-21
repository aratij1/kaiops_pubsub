from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from common.tenant_identity import require_tenant_id


class ReviewDisposition(StrEnum):
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"
    SUPPORTED = "SUPPORTED"


class CodePatchProposal(BaseModel):
    """A review artifact only; it is never an executable remediation skill."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["kaims.code-patch-proposal.v1"] = "kaims.code-patch-proposal.v1"
    proposal_id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    incident_id: UUID
    repository_id: str
    base_revision: str
    source_uri: str
    title: str
    explanation: str
    unified_diff: str
    supporting_code_evidence_ids: list[str]
    test_plan: list[str]
    limitations: list[str] = Field(default_factory=list)
    review_required: Literal[True] = True
    executable: Literal[False] = False

    @model_validator(mode="after")
    def patch_is_evidence_bound(self) -> "CodePatchProposal":
        require_tenant_id(self.tenant_id, source="code patch proposal")
        if not self.supporting_code_evidence_ids:
            raise ValueError("code patch proposal requires source-code evidence")
        if not all(marker in self.unified_diff for marker in ("--- ", "+++ ", "@@")):
            raise ValueError("code patch proposal must contain a unified diff")
        if not self.test_plan:
            raise ValueError("code patch proposal requires a test plan")
        return self


class TemporalGraphNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node_id: str
    kind: Literal["service", "resource", "deployment", "dependency", "incident", "owner"]
    label: str


class TemporalGraphEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")
    edge_id: str
    source_node_id: str
    relation: str
    target_node_id: str
    valid_from: datetime
    valid_to: datetime | None = None
    observed_at: datetime
    evidence_ids: list[str]
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def interval_and_evidence_are_valid(self) -> "TemporalGraphEdge":
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("temporal edge valid_to must follow valid_from")
        if not self.evidence_ids:
            raise ValueError("temporal edge requires evidence")
        return self

    def active_at(self, timestamp: datetime) -> bool:
        instant = timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=UTC)
        start = self.valid_from if self.valid_from.tzinfo else self.valid_from.replace(tzinfo=UTC)
        end = self.valid_to if self.valid_to is None or self.valid_to.tzinfo else self.valid_to.replace(tzinfo=UTC)
        return start <= instant and (end is None or instant < end)


class TemporalServiceGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["kaims.temporal-service-graph.v1"] = "kaims.temporal-service-graph.v1"
    tenant_id: str
    nodes: list[TemporalGraphNode]
    edges: list[TemporalGraphEdge]

    @model_validator(mode="after")
    def edges_reference_known_nodes(self) -> "TemporalServiceGraph":
        require_tenant_id(self.tenant_id, source="temporal service graph")
        node_ids = {node.node_id for node in self.nodes}
        for edge in self.edges:
            if edge.source_node_id not in node_ids or edge.target_node_id not in node_ids:
                raise ValueError("temporal edge references an unknown node")
        return self

    def snapshot(self, timestamp: datetime) -> dict[str, list[dict]]:
        active_edges = [edge for edge in self.edges if edge.active_at(timestamp)]
        active_nodes = {value for edge in active_edges for value in (edge.source_node_id, edge.target_node_id)}
        return {
            "nodes": [node.model_dump(mode="json") for node in self.nodes if node.node_id in active_nodes],
            "edges": [edge.model_dump(mode="json") for edge in active_edges],
        }


class EvidenceCouncilVote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    judge_id: str
    role: Literal["causal", "operations", "safety", "domain"]
    disposition: ReviewDisposition
    confidence: float = Field(ge=0.0, le=1.0)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    rationale: str

    @model_validator(mode="after")
    def evidence_relationships_are_disjoint(self) -> "EvidenceCouncilVote":
        if set(self.supporting_evidence_ids) & set(self.contradicting_evidence_ids):
            raise ValueError("council evidence cannot both support and contradict")
        if self.disposition == ReviewDisposition.SUPPORTED and not self.supporting_evidence_ids:
            raise ValueError("supported council vote requires evidence")
        return self


class EvidenceCouncilDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["kaims.evidence-council.v1"] = "kaims.evidence-council.v1"
    disposition: ReviewDisposition
    confidence: float = Field(ge=0.0, le=1.0)
    votes: list[EvidenceCouncilVote]
    reason_codes: list[str]
    human_review_required: bool = True


def decide_evidence_council(votes: list[EvidenceCouncilVote]) -> EvidenceCouncilDecision:
    unique = {vote.judge_id for vote in votes}
    if len(unique) != len(votes):
        raise ValueError("evidence council judge identities must be unique")
    if len(votes) < 3 or len({vote.role for vote in votes}) < 3:
        return EvidenceCouncilDecision(
            disposition=ReviewDisposition.INSUFFICIENT_EVIDENCE,
            confidence=0.0,
            votes=votes,
            reason_codes=["three_independent_judge_roles_required"],
        )
    if any(vote.disposition == ReviewDisposition.CONFLICTING_EVIDENCE for vote in votes):
        return EvidenceCouncilDecision(
            disposition=ReviewDisposition.CONFLICTING_EVIDENCE,
            confidence=min(vote.confidence for vote in votes),
            votes=votes,
            reason_codes=["council_conflict_requires_operator_review"],
        )
    supported = [vote for vote in votes if vote.disposition == ReviewDisposition.SUPPORTED]
    evidence_sources = {evidence_id for vote in supported for evidence_id in vote.supporting_evidence_ids}
    if len(supported) == len(votes) and len(evidence_sources) >= 2:
        return EvidenceCouncilDecision(
            disposition=ReviewDisposition.SUPPORTED,
            confidence=min(vote.confidence for vote in supported),
            votes=votes,
            reason_codes=["independent_judges_agree"],
        )
    return EvidenceCouncilDecision(
        disposition=ReviewDisposition.INSUFFICIENT_EVIDENCE,
        confidence=min((vote.confidence for vote in votes), default=0.0),
        votes=votes,
        reason_codes=["unanimous_evidence_support_required"],
    )


class PreventiveRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["kaims.preventive-recommendation.v1"] = "kaims.preventive-recommendation.v1"
    recommendation_id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    service: str
    risk_signal: str
    forecast_window_seconds: int = Field(ge=300, le=2592000)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_ids: list[str]
    recommended_review: str
    mode: Literal["SHADOW", "RECOMMENDATION"] = "SHADOW"
    commands: list[Literal[""]] = Field(default_factory=list)
    execution_authorized: Literal[False] = False

    @model_validator(mode="after")
    def prevention_is_non_executing(self) -> "PreventiveRecommendation":
        require_tenant_id(self.tenant_id, source="preventive recommendation")
        if len(self.evidence_ids) < 2:
            raise ValueError("preventive recommendation requires two evidence records")
        if self.commands:
            raise ValueError("preventive recommendation cannot contain commands")
        return self
