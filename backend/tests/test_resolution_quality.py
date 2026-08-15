from datetime import datetime, timezone

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


def test_connector_aliases_do_not_fake_independent_corroboration() -> None:
    quality = assess_evidence_quality(
        [
            {"evidence_id": "a", "source": "prometheus", "diagnostic_signals": ["metric_anomaly"]},
            {"evidence_id": "b", "source": "telemetry", "diagnostic_signals": ["metric_anomaly"]},
        ],
        accepted_ids=["a", "b"],
    )
    assert quality.independent_sources == 1
    assert quality.sufficiency == "partial"
    assert quality.confidence_ceiling == 0.69


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


def test_stale_direct_evidence_cannot_support_high_confidence() -> None:
    quality = assess_evidence_quality(
        [
            {
                "evidence_id": "a",
                "source": "prometheus",
                "uri": "prometheus://checkout/errors",
                "diagnostic_signals": ["metric_anomaly"],
                "observed_at": "2026-08-14T10:00:00Z",
            },
            {
                "evidence_id": "b",
                "source": "opensearch",
                "uri": "opensearch://checkout/errors",
                "diagnostic_signals": ["error_code"],
                "observed_at": "2026-08-14T10:00:00Z",
            },
        ],
        accepted_ids=["a", "b"],
        reference_time=datetime(2026, 8, 15, 10, 0, tzinfo=timezone.utc),
    )
    assert quality.sufficiency == "stale"
    assert quality.fresh_direct_evidence == 0
    assert quality.confidence_ceiling <= 0.59


def test_duplicate_evidence_does_not_inflate_corroboration() -> None:
    row = {
        "uri": "prometheus://checkout/errors",
        "snippet": "error rate 8%",
        "diagnostic_signals": ["metric_anomaly"],
    }
    quality = assess_evidence_quality(
        [
            {**row, "evidence_id": "a", "source": "prometheus"},
            {**row, "evidence_id": "b", "source": "opensearch"},
        ],
        accepted_ids=["a", "b"],
    )
    assert quality.accepted_evidence == 1
    assert quality.independent_sources == 1


def test_remediation_gate_blocks_degraded_context_and_partial_evidence() -> None:
    gate = remediation_quality_gate(
        {
            "commands": ["kubectl rollout restart deployment/checkout -n prod"],
            "mutating": True,
            "validation_commands": ["kubectl rollout status deployment/checkout -n prod"],
            "rollback_commands": ["kubectl rollout undo deployment/checkout -n prod"],
            "approval_required": False,
        },
        rca_confidence=0.9,
        impact_confidence=0.8,
        risk="medium",
        environment="staging",
        fallback_used=False,
        evidence_quality={"sufficiency": "partial"},
        context_degraded=True,
    )
    assert not gate["trusted_for_auto_execution"]
    assert len(gate["blockers"]) == 2
