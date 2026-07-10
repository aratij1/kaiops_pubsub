from common.models import AgentEventContractV1, Alert, AlertSeverity, Evidence


def test_alert_defaults_and_serialization() -> None:
    alert = Alert(
        source="Prometheus",
        name="PaymentLatencyHigh",
        service="payments",
        severity=AlertSeverity.CRITICAL,
        description="payment latency above threshold",
    )

    payload = alert.model_dump(mode="json")

    assert payload["source"] == "prometheus"
    assert payload["severity"] == "critical"
    assert payload["deduplicated_count"] == 1


def test_evidence_contract_defaults() -> None:
    evidence = Evidence(id="ev-1", type="runbook", source="knowledge-router", confidence=0.8)

    assert evidence.id == "ev-1"
    assert evidence.metadata == {}
    assert evidence.content is None


def test_agent_event_contract_shape() -> None:
    event = AgentEventContractV1(
        flow_id="flow-1",
        incident_id="inc-1",
        trace_id="trace-1",
        agent="resolution-agent",
        payload={"recommended_action": "rollback"},
        confidence=0.82,
        evidence_ids=["ev-1"],
    )

    payload = event.model_dump(mode="json")
    assert payload["version"] == "v1"
    assert payload["agent"] == "resolution-agent"
    assert payload["confidence"] == 0.82
    assert payload["evidence_ids"] == ["ev-1"]
