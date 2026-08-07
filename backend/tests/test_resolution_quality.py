from ai_workbench_common.resolution_quality import assess_evidence_quality, remediation_quality_gate


def test_confidence_is_capped_without_independent_direct_evidence() -> None:
    quality = assess_evidence_quality(
        [{"evidence_id": "a", "source": "jira", "diagnostic_signals": []}],
        accepted_ids=["a"],
    )
    assert quality.sufficiency == "partial"
    assert quality.confidence_ceiling <= 0.55


def test_independent_sources_with_direct_signal_support_high_confidence() -> None:
    quality = assess_evidence_quality(
        [
            {"evidence_id": "a", "source": "prometheus", "diagnostic_signals": ["metric_anomaly"]},
            {"evidence_id": "b", "source": "opensearch", "diagnostic_signals": ["error_code"]},
        ],
        accepted_ids=["a", "b"],
    )
    assert quality.sufficiency == "sufficient"
    assert quality.independent_sources == 2
    assert quality.confidence_ceiling == 0.95


def test_remediation_gate_requires_validation_rollback_and_approval() -> None:
    gate = remediation_quality_gate(
        {"commands": ["kubectl delete pod checkout"], "approval_required": True},
        rca_confidence=0.9,
        impact_confidence=0.8,
        risk="high",
        environment="prod",
        fallback_used=False,
    )
    assert gate["mandatory_approval"]
    assert gate["requires_human_review"]
    assert not gate["trusted_for_auto_execution"]
    assert len(gate["blockers"]) == 2
