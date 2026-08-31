from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from common.tenant_identity import require_tenant_id


class EvidenceNodeType(StrEnum):
    ALERT = "alert"
    METRIC = "metric"
    LOG = "log"
    TRACE = "trace"
    TOPOLOGY = "topology"
    CHANGE = "change"
    DEPLOYMENT = "deployment"
    CONFIGURATION = "configuration"
    TICKET = "ticket"
    SIMILAR_INCIDENT = "similar_incident"
    RUNBOOK = "runbook"
    DATABASE = "database"
    INFRASTRUCTURE = "infrastructure_health"
    RESOURCE = "resource"
    HYPOTHESIS = "hypothesis"


class EvidenceRelationship(StrEnum):
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    PRECEDES = "PRECEDES"
    AFFECTS = "AFFECTS"
    DEPENDS_ON = "DEPENDS_ON"
    CAUSES = "CAUSES"


class RelationshipBasis(StrEnum):
    OBSERVED_FACT = "observed_fact"
    VERIFIED_TOPOLOGY = "verified_topology"
    STRONG_CORRELATION = "strong_correlation"
    AI_INFERRED = "ai_inferred"


class EvidenceGraphNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node_id: str
    node_type: EvidenceNodeType
    label: str
    source: str
    observed_at: datetime
    resource_ids: list[str] = Field(default_factory=list)
    reliability: float = Field(ge=0.0, le=1.0)
    payload_checksum: str
    provenance: dict[str, Any] = Field(default_factory=dict)

    @field_validator("node_id", "label", "source")
    @classmethod
    def require_identity(cls, value: str) -> str:
        value = str(value or "").strip()
        if not value:
            raise ValueError("evidence node identity is required")
        return value

    @field_validator("payload_checksum")
    @classmethod
    def require_checksum(cls, value: str) -> str:
        value = str(value or "").lower()
        if not value.startswith("sha256:") or len(value) != 71:
            raise ValueError("evidence payload requires a complete sha256 checksum")
        return value


class EvidenceGraphEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")
    edge_id: str
    source_node_id: str
    target_node_id: str
    relationship: EvidenceRelationship
    basis: RelationshipBasis
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_ids: list[str] = Field(default_factory=list)
    explanation: str

    @model_validator(mode="after")
    def inference_is_never_unlabelled(self) -> "EvidenceGraphEdge":
        if self.relationship == EvidenceRelationship.CAUSES:
            if self.basis == RelationshipBasis.OBSERVED_FACT:
                raise ValueError("causality cannot be labelled as a directly observed fact")
            if not self.evidence_ids:
                raise ValueError("causal edge requires supporting evidence")
        if self.basis == RelationshipBasis.AI_INFERRED and not self.evidence_ids:
            raise ValueError("AI-inferred edge requires traceable evidence")
        return self


class IncidentEvidenceGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["kaims.incident-evidence-graph.v1"] = "kaims.incident-evidence-graph.v1"
    tenant_id: str
    incident_id: UUID
    nodes: list[EvidenceGraphNode]
    edges: list[EvidenceGraphEdge]
    primary_hypothesis_id: str | None = None
    alternative_hypothesis_ids: list[str] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_graph(self) -> "IncidentEvidenceGraph":
        require_tenant_id(self.tenant_id, source="incident evidence graph")
        node_ids = [node.node_id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("evidence graph node identities must be unique")
        known = set(node_ids)
        for edge in self.edges:
            if edge.source_node_id not in known or edge.target_node_id not in known:
                raise ValueError("evidence graph edge references an unknown node")
        hypotheses = {node.node_id for node in self.nodes if node.node_type == EvidenceNodeType.HYPOTHESIS}
        if self.primary_hypothesis_id and self.primary_hypothesis_id not in hypotheses:
            raise ValueError("primary hypothesis is not present in the graph")
        if any(item not in hypotheses for item in self.alternative_hypothesis_ids):
            raise ValueError("alternative hypothesis is not present in the graph")
        return self


def _checksum(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _observed_at(row: dict[str, Any]) -> datetime:
    for key in ("observed_at", "timestamp", "occurred_at", "collected_at"):
        raw = row.get(key)
        if isinstance(raw, datetime):
            return raw if raw.tzinfo else raw.replace(tzinfo=UTC)
        if raw:
            try:
                parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
            except ValueError:
                pass
    return datetime.now(UTC)


_SOURCE_TYPES = {
    "alert": EvidenceNodeType.ALERT, "telemetry": EvidenceNodeType.METRIC,
    "metrics": EvidenceNodeType.METRIC, "logs": EvidenceNodeType.LOG,
    "traces": EvidenceNodeType.TRACE, "topology": EvidenceNodeType.TOPOLOGY,
    "dependency": EvidenceNodeType.TOPOLOGY, "changes": EvidenceNodeType.CHANGE,
    "deployment": EvidenceNodeType.DEPLOYMENT, "code": EvidenceNodeType.CONFIGURATION,
    "history": EvidenceNodeType.SIMILAR_INCIDENT, "ticket": EvidenceNodeType.TICKET,
    "runbooks": EvidenceNodeType.RUNBOOK, "data": EvidenceNodeType.DATABASE,
    "database": EvidenceNodeType.DATABASE, "infrastructure": EvidenceNodeType.INFRASTRUCTURE,
}


def build_incident_evidence_graph(
    *, tenant_id: str, incident_id: UUID, evidence: list[dict[str, Any]],
    hypotheses: list[dict[str, Any]], conclusive_primary_id: str | None, data_gaps: list[str],
) -> IncidentEvidenceGraph:
    nodes: list[EvidenceGraphNode] = []
    edges: list[EvidenceGraphEdge] = []
    known_evidence: set[str] = set()
    for index, row in enumerate(evidence):
        evidence_id = str(row.get("evidence_id") or row.get("id") or f"evidence:{index}")
        source = str(row.get("source") or row.get("source_type") or "alert").lower()
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        resource_ids = [str(item) for item in row.get("resource_ids", []) if str(item).strip()]
        resource_id = str(row.get("resource_id") or metadata.get("resource_id") or "").strip()
        if resource_id and resource_id not in resource_ids:
            resource_ids.append(resource_id)
        checksum = str(row.get("payload_checksum") or row.get("checksum") or "")
        if not checksum.startswith("sha256:") or len(checksum) != 71:
            checksum = _checksum(row)
        nodes.append(EvidenceGraphNode(
            node_id=evidence_id, node_type=_SOURCE_TYPES.get(source, EvidenceNodeType.INFRASTRUCTURE),
            label=str(row.get("title") or row.get("summary") or row.get("uri") or evidence_id)[:300],
            source=source, observed_at=_observed_at(row), resource_ids=resource_ids,
            reliability=max(0.0, min(float(row.get("reliability_score") or row.get("confidence") or 0.5), 1.0)),
            payload_checksum=checksum,
            provenance={"uri": row.get("uri"), "collector": metadata.get("collector") or source,
                        "relationship_source": metadata.get("relationship_source")},
        ))
        known_evidence.add(evidence_id)
    hypothesis_ids: list[str] = []
    for index, hypothesis in enumerate(hypotheses):
        hypothesis_id = str(hypothesis.get("hypothesis_id") or f"hypothesis:{index}")
        hypothesis_ids.append(hypothesis_id)
        nodes.append(EvidenceGraphNode(
            node_id=hypothesis_id, node_type=EvidenceNodeType.HYPOTHESIS,
            label=str(hypothesis.get("claim") or "Unresolved causal hypothesis")[:300],
            source="resolution-agent", observed_at=datetime.now(UTC),
            resource_ids=[str(item) for item in hypothesis.get("affected_resource_ids", [])],
            reliability=max(0.0, min(float(hypothesis.get("confidence") or 0.0), 1.0)),
            payload_checksum=_checksum(hypothesis),
            provenance={"status": hypothesis.get("status"), "model_generated": True},
        ))
        for relationship, field in ((EvidenceRelationship.SUPPORTS, "supporting_evidence_ids"),
                                    (EvidenceRelationship.CONTRADICTS, "contradicting_evidence_ids")):
            for evidence_id in dict.fromkeys(str(item) for item in hypothesis.get(field, [])):
                if evidence_id not in known_evidence:
                    continue
                edges.append(EvidenceGraphEdge(
                    edge_id=f"{relationship.value.lower()}:{evidence_id}:{hypothesis_id}",
                    source_node_id=evidence_id, target_node_id=hypothesis_id,
                    relationship=relationship, basis=RelationshipBasis.STRONG_CORRELATION,
                    confidence=max(0.0, min(float(hypothesis.get("confidence") or 0.0), 1.0)),
                    evidence_ids=[evidence_id],
                    explanation="Evidence was deterministically classified against this falsifiable hypothesis.",
                ))
        causal_sequence = [str(item).strip() for item in hypothesis.get("causal_sequence", []) if str(item).strip()]
        causal_evidence = [
            str(item) for item in hypothesis.get("supporting_evidence_ids", [])
            if str(item) in known_evidence
        ]
        path_node_ids: list[str] = []
        if causal_evidence:
            for path_index, label in enumerate(causal_sequence):
                path_id = f"{hypothesis_id}:causal:{path_index}"
                path_node_ids.append(path_id)
                nodes.append(EvidenceGraphNode(
                    node_id=path_id, node_type=EvidenceNodeType.RESOURCE, label=label,
                    source="resolution-agent", observed_at=datetime.now(UTC), resource_ids=[],
                    reliability=max(0.0, min(float(hypothesis.get("confidence") or 0.0), 1.0)),
                    payload_checksum=_checksum({"hypothesis_id": hypothesis_id, "sequence": path_index, "label": label}),
                    provenance={"relationship_source": "inferred", "hypothesis_id": hypothesis_id},
                ))
            for path_index, (source_id, target_id) in enumerate(zip(path_node_ids, path_node_ids[1:])):
                edges.append(EvidenceGraphEdge(
                    edge_id=f"causes:{hypothesis_id}:{path_index}",
                    source_node_id=source_id, target_node_id=target_id,
                    relationship=EvidenceRelationship.CAUSES, basis=RelationshipBasis.AI_INFERRED,
                    confidence=max(0.0, min(float(hypothesis.get("confidence") or 0.0), 1.0)),
                    evidence_ids=causal_evidence,
                    explanation="Candidate causal step inferred from cited evidence; it is not an observed fact.",
                ))
    primary = conclusive_primary_id if conclusive_primary_id in set(hypothesis_ids) else None
    return IncidentEvidenceGraph(
        tenant_id=tenant_id, incident_id=incident_id, nodes=nodes, edges=edges,
        primary_hypothesis_id=primary,
        alternative_hypothesis_ids=[item for item in hypothesis_ids if item != primary],
        data_gaps=list(dict.fromkeys(str(item) for item in data_gaps if str(item).strip())),
    )
