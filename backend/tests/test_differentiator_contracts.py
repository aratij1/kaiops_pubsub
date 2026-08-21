from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from common.differentiator_contracts import (
    CodePatchProposal,
    EvidenceCouncilVote,
    PreventiveRecommendation,
    TemporalGraphEdge,
    TemporalGraphNode,
    TemporalServiceGraph,
    decide_evidence_council,
)


def test_code_patch_is_review_only_and_requires_evidence_diff_and_tests() -> None:
    proposal = CodePatchProposal(
        tenant_id="tenant-a", incident_id=uuid4(), repository_id="payments", base_revision="abc123",
        source_uri="repo://payments/app.py", title="Bound the connection pool", explanation="Evidence-backed fix",
        unified_diff="--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new", supporting_code_evidence_ids=["CODE-1"],
        test_plan=["Run the connection-pool regression test"],
    )
    assert proposal.review_required is True and proposal.executable is False

    with pytest.raises(ValidationError, match="unified diff"):
        proposal.model_copy(update={"unified_diff": "replace the code"}).model_dump()
        CodePatchProposal.model_validate({**proposal.model_dump(), "unified_diff": "replace the code"})


def test_temporal_graph_snapshot_excludes_expired_dependency() -> None:
    now = datetime.now(UTC)
    graph = TemporalServiceGraph(
        tenant_id="tenant-a",
        nodes=[TemporalGraphNode(node_id="service:api", kind="service", label="api"), TemporalGraphNode(node_id="service:db", kind="service", label="db")],
        edges=[TemporalGraphEdge(edge_id="edge-1", source_node_id="service:api", relation="DEPENDS_ON", target_node_id="service:db", valid_from=now - timedelta(hours=2), valid_to=now - timedelta(hours=1), observed_at=now - timedelta(hours=2), evidence_ids=["TOPOLOGY-1"], confidence=0.9)],
    )
    assert graph.snapshot(now)["edges"] == []
    assert len(graph.snapshot(now - timedelta(minutes=90))["edges"]) == 1


def _vote(judge: str, role: str, disposition: str = "SUPPORTED", evidence: list[str] | None = None) -> EvidenceCouncilVote:
    return EvidenceCouncilVote(judge_id=judge, role=role, disposition=disposition, confidence=0.9, supporting_evidence_ids=evidence or ["LOG-1"], rationale="Reviewed independent evidence.")


def test_evidence_council_requires_independent_roles_and_unanimous_support() -> None:
    decision = decide_evidence_council([_vote("causal-1", "causal", evidence=["LOG-1"]), _vote("ops-1", "operations", evidence=["METRIC-1"]), _vote("safety-1", "safety", evidence=["LOG-1", "METRIC-1"])])
    assert decision.disposition == "SUPPORTED"
    assert decision.human_review_required is True

    conflict = decide_evidence_council([_vote("causal-1", "causal"), _vote("ops-1", "operations", "CONFLICTING_EVIDENCE"), _vote("safety-1", "safety")])
    assert conflict.disposition == "CONFLICTING_EVIDENCE"


def test_preventive_recommendation_cannot_carry_commands_or_authorize_execution() -> None:
    recommendation = PreventiveRecommendation(
        tenant_id="tenant-a", service="payments-api", risk_signal="Pool utilization rising",
        forecast_window_seconds=3600, confidence=0.8, evidence_ids=["METRIC-1", "METRIC-2"],
        recommended_review="Review capacity and pool configuration before the forecast window.",
    )
    assert recommendation.mode == "SHADOW" and recommendation.execution_authorized is False
    with pytest.raises(ValidationError):
        PreventiveRecommendation.model_validate({**recommendation.model_dump(), "commands": ["kubectl scale deployment payments-api"]})
