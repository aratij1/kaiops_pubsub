from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from resolution_agent.contracts import Hypothesis, RCAResult, ResolutionOption, ResolutionOutcome


def test_non_conclusive_rca_cannot_fabricate_a_root_cause() -> None:
    with pytest.raises(ValidationError, match="must not assert a root cause"):
        RCAResult(
            incident_id=uuid4(),
            correlation_id="trace-1",
            outcome=ResolutionOutcome.INSUFFICIENT_EVIDENCE,
            root_cause="A plausible but unproven deployment regression",
            confidence=0.4,
        )


def test_supported_rca_requires_multiple_evidence_items() -> None:
    with pytest.raises(ValidationError, match="at least two"):
        RCAResult(
            incident_id=uuid4(),
            correlation_id="trace-2",
            outcome=ResolutionOutcome.EVIDENCE_SUPPORTED,
            root_cause="Connection pool leak",
            leading_hypothesis_id="H1",
            confidence=0.9,
            supporting_evidence_ids=["LOG-1"],
        )


def test_evidence_cannot_support_and_contradict_same_hypothesis() -> None:
    with pytest.raises(ValidationError, match="both support and contradict"):
        Hypothesis(
            incident_id=uuid4(),
            correlation_id="trace-3",
            title="Database saturation",
            description="Database saturation caused request timeouts.",
            suspected_component="orders-db",
            probability=0.5,
            supporting_evidence_ids=["METRIC-1"],
            contradicting_evidence_ids=["METRIC-1"],
        )


def test_supported_rca_carries_ranked_typed_resolution_options() -> None:
    incident_id = uuid4()
    option = ResolutionOption(
        option_id="restart-container-app-revision",
        incident_id=incident_id,
        correlation_id="trace-4",
        title="Restart the unhealthy revision",
        objective="Restore healthy request processing.",
        action_type="restart_container_app_revision",
        target={"service": "checkout"},
        reasoning="The option is backed by the confirmed RCA and governed catalog.",
        supporting_evidence_ids=["LOG-1", "METRIC-1"],
        confidence=0.9,
        estimated_success_probability=0.8,
        risk_level="MEDIUM",
        automation_eligibility="HITL",
    )

    result = RCAResult(
        incident_id=incident_id,
        correlation_id="trace-4",
        outcome=ResolutionOutcome.EVIDENCE_SUPPORTED,
        root_cause="The active revision exhausted its connection pool.",
        leading_hypothesis_id="H1",
        confidence=0.9,
        supporting_evidence_ids=["LOG-1", "METRIC-1"],
        resolution_options=[option],
    )

    assert result.resolution_options[0].automation_eligibility == "HITL"
