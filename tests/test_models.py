from common.models import Alert, AlertSeverity


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
