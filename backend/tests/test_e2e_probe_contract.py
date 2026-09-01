from scripts.e2e_alert_lifecycle_probe import summarize_context_evidence


def test_context_evidence_summary_reads_report_ui_snapshot_manifest() -> None:
    summary = summarize_context_evidence(
        {"metadata": {"context_complete": True, "context_source": "realtime_collection"}},
        {
            "quality_score": 0.82,
            "source_manifest": {
                "logs": {"result_count": 4},
                "topology": {"fresh_count": 2},
                "traces": {"result_count": 0},
            },
        },
    )

    assert summary == {
        "evidence_present": True,
        "evidence_count": 6,
        "collected_sources": ["logs", "topology"],
        "context_complete": True,
        "context_source": "realtime_collection",
        "snapshot_quality": 0.82,
    }


def test_context_evidence_summary_accepts_discovery_evidence_before_snapshot_projection() -> None:
    summary = summarize_context_evidence(
        {"metadata": {"discovery_evidence": [{"id": "LOG-1"}]}}
    )

    assert summary["evidence_present"] is True
    assert summary["evidence_count"] == 0


def test_context_evidence_summary_rejects_empty_context_shell() -> None:
    summary = summarize_context_evidence({"metadata": {"context_complete": False}})

    assert summary["evidence_present"] is False
    assert summary["collected_sources"] == []
