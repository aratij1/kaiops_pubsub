from uuid import uuid4

import pytest
from pydantic import ValidationError

from common.evidence_graph import (
    EvidenceGraphEdge,
    IncidentEvidenceGraph,
    build_incident_evidence_graph,
)


def test_graph_exposes_primary_alternatives_contradictions_and_gaps():
    incident_id = uuid4()
    graph = build_incident_evidence_graph(
        tenant_id="tenant-a",
        incident_id=incident_id,
        evidence=[
            {"evidence_id": "metric:1", "source": "metrics", "summary": "pool saturation", "reliability_score": .9},
            {"evidence_id": "trace:1", "source": "traces", "summary": "database wait", "reliability_score": .95},
            {"evidence_id": "log:1", "source": "logs", "summary": "healthy dependency", "reliability_score": .8},
        ],
        hypotheses=[
            {"hypothesis_id": "h-primary", "claim": "pool exhaustion caused checkout failures", "confidence": .91,
             "supporting_evidence_ids": ["metric:1", "trace:1"], "contradicting_evidence_ids": [],
             "causal_sequence": ["payment latency", "pool exhaustion", "checkout failures"]},
            {"hypothesis_id": "h-alt", "claim": "dependency outage caused failures", "confidence": .35,
             "supporting_evidence_ids": [], "contradicting_evidence_ids": ["log:1"]},
        ],
        conclusive_primary_id="h-primary",
        data_gaps=["changes"],
    )
    assert graph.primary_hypothesis_id == "h-primary"
    assert graph.alternative_hypothesis_ids == ["h-alt"]
    assert graph.data_gaps == ["changes"]
    assert {edge.relationship for edge in graph.edges} == {"SUPPORTS", "CONTRADICTS", "CAUSES"}
    causal_edges = [edge for edge in graph.edges if edge.relationship == "CAUSES"]
    assert causal_edges and all(edge.basis == "ai_inferred" for edge in causal_edges)


def test_non_conclusive_graph_never_presents_primary_hypothesis_as_fact():
    graph = build_incident_evidence_graph(
        tenant_id="tenant-a", incident_id=uuid4(), evidence=[],
        hypotheses=[{"hypothesis_id": "h1", "claim": "possible cause", "confidence": .8}],
        conclusive_primary_id=None, data_gaps=["logs"],
    )
    assert graph.primary_hypothesis_id is None
    assert graph.alternative_hypothesis_ids == ["h1"]


def test_ai_inferred_and_causal_edges_require_evidence():
    with pytest.raises(ValidationError, match="traceable evidence"):
        EvidenceGraphEdge(
            edge_id="edge-1", source_node_id="a", target_node_id="b", relationship="AFFECTS",
            basis="ai_inferred", confidence=.8, evidence_ids=[], explanation="model inference",
        )
    with pytest.raises(ValidationError, match="causal edge requires"):
        EvidenceGraphEdge(
            edge_id="edge-2", source_node_id="a", target_node_id="b", relationship="CAUSES",
            basis="strong_correlation", confidence=.8, evidence_ids=[], explanation="correlation",
        )


def test_graph_rejects_dangling_edges():
    base = build_incident_evidence_graph(
        tenant_id="tenant-a", incident_id=uuid4(), evidence=[], hypotheses=[],
        conclusive_primary_id=None, data_gaps=[],
    ).model_dump(mode="json")
    base["edges"] = [{
        "edge_id": "dangling", "source_node_id": "missing-a", "target_node_id": "missing-b",
        "relationship": "SUPPORTS", "basis": "strong_correlation", "confidence": .5,
        "evidence_ids": ["missing-a"], "explanation": "invalid",
    }]
    with pytest.raises(ValidationError, match="unknown node"):
        IncidentEvidenceGraph.model_validate(base)
