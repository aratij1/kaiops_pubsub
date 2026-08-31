from common.kafka import normalize_payload
from common.models import Alert, Incident


def test_normalize_payload_handles_nested_models() -> None:
    alert = Alert(source="prometheus", name="A", service="payments", description="test")
    incident = Incident(service="payments", title="incident")

    payload = normalize_payload({"alert": alert, "incident": incident})

    assert payload["alert"]["id"] == str(alert.id)
    assert payload["incident"]["id"] == str(incident.id)
