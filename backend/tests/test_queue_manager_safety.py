from common.message_processing import extract_processing_identities
from api_gateway.auth_policy import ADMIN_ROLE, route_auth_rule


def test_queue_manager_routes_require_administrator() -> None:
    assert route_auth_rule("GET", "/operations/queues") == {ADMIN_ROLE}
    assert route_auth_rule("POST", "/operations/queues/cancel-alert") == {ADMIN_ROLE}
    assert route_auth_rule("DELETE", "/operations/queues/kaiops.worker.raw-alerts/messages") == {ADMIN_ROLE}


def test_processing_identities_follow_alert_across_pipeline_envelopes() -> None:
    identities = extract_processing_identities(
        {
            "alert_id": "alert-123",
            "incident_id": "incident-456",
            "event_envelope": {"event_id": "event-789", "alert_id": "alert-123"},
        }
    )
    assert identities[0:2] == ["alert-123", "incident-456"]
    assert "event-789" in identities


def test_processing_identities_are_unique_and_ignore_empty_values() -> None:
    assert extract_processing_identities({"alert_id": "same", "id": "same", "incident_id": ""}) == ["same"]
