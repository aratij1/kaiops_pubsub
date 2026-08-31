from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from common.learning_contracts import (
    AgentOpsTrace,
    IncidentMemoryRecord,
    OperatorCorrection,
    PromotionEvidence,
    assess_autonomy_promotion,
)


def _promotion(**updates) -> PromotionEvidence:
    payload = {
        "tenant_id": "tenant-a",
        "service": "payments-api",
        "action_type": "restart_service",
        "current_tier": "SHADOW",
        "reviewed_attempts": 40,
        "successful_attempts": 39,
        "rollback_attempts": 0,
        "operator_corrections": 1,
        "critical_failures": 0,
        "calibration_samples": [{"confidence": 0.98, "correct": True} for _ in range(39)] + [{"confidence": 0.02, "correct": False}],
        "approved_runbook": True,
        "rollback_tested": True,
        "credential_scope_verified": True,
        "blast_radius_verified": True,
    }
    payload.update(updates)
    return PromotionEvidence.model_validate(payload)


def test_reviewed_recovery_memory_requires_validation_evidence() -> None:
    with pytest.raises(ValidationError, match="validation evidence"):
        IncidentMemoryRecord(
            tenant_id="tenant-a",
            incident_id=uuid4(),
            service="payments-api",
            environment="prod",
            issue_signature="sig-1",
            root_cause="Pool exhaustion",
            resolution_option_id="restart",
            execution_id=uuid4(),
            outcome="RECOVERED",
            rollback_disposition="NOT_REQUIRED",
            operator_reviewed=True,
        )


def test_non_approval_operator_correction_requires_reason() -> None:
    with pytest.raises(ValidationError, match="reason_category"):
        OperatorCorrection(decision="incorrect", actor="operator-a")


def test_agentops_trace_rejects_secret_attributes_and_invalid_duration() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValidationError, match="credential material"):
        AgentOpsTrace(
            trace_id="trace-1", tenant_id="tenant-a", incident_id=uuid4(), agent="resolution-agent",
            started_at=now, completed_at=now + timedelta(seconds=1), tool_calls=2, outcome="completed",
            attributes={"api_key": "must-not-be-recorded"},
        )


def test_shadow_promotes_only_one_tier_when_all_evidence_is_proven() -> None:
    decision = assess_autonomy_promotion(_promotion())

    assert decision.disposition == "PROMOTE"
    assert decision.current_tier == "SHADOW"
    assert decision.recommended_tier == "RECOMMENDATION"
    assert decision.requires_human_approval is True


def test_hitl_cannot_promote_to_hotl_in_phase_5() -> None:
    decision = assess_autonomy_promotion(_promotion(current_tier="HITL"))

    assert decision.disposition == "HOLD"
    assert decision.recommended_tier == "HITL"
    assert "hotl_promotion_not_authorized_in_phase_5" in decision.reason_codes


def test_critical_failure_demotes_even_with_strong_aggregate_metrics() -> None:
    decision = assess_autonomy_promotion(_promotion(current_tier="HITL", critical_failures=1))

    assert decision.disposition == "DEMOTE"
    assert decision.recommended_tier == "RECOMMENDATION"


def test_missing_calibration_samples_holds_promotion() -> None:
    decision = assess_autonomy_promotion(_promotion(calibration_samples=[]))

    assert decision.disposition == "HOLD"
    assert "confidence_calibration_not_proven" in decision.reason_codes
