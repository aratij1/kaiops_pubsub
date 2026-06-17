from alert_intelligence import AlertIntelligenceAgent
from common.models import Alert, AlertSeverity


def make_alert(description: str = "payment latency above threshold") -> Alert:
    return Alert(
        source="prometheus",
        name="PaymentLatencyHigh",
        service="payments",
        severity=AlertSeverity.WARNING,
        description=description,
        labels={"deployment": "payments-api", "team": "payments-sre"},
    )


def test_alert_intelligence_deduplicates_and_classifies() -> None:
    agent = AlertIntelligenceAgent()
    first, first_incident = agent.process(make_alert())
    second, _ = agent.process(make_alert())

    assert first.severity == AlertSeverity.CRITICAL
    assert second.deduplicated_count == 2
    assert second.correlation_id == first.correlation_id
    assert first_incident.owner_team == "payments-sre"


def test_alert_intelligence_uses_embedding_correlation() -> None:
    agent = AlertIntelligenceAgent(correlation_threshold=0.2)
    first, _ = agent.process(make_alert("checkout payment latency high"))
    correlated, _ = agent.process(make_alert("payment checkout latency degraded"))

    assert correlated.correlation_id == first.correlation_id
