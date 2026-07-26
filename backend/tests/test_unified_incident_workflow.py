from __future__ import annotations

from common.incident_policy import IncidentSeverityPolicy
from common.models import Alert, AlertSeverity, Incident, IncidentStatus, RawAlert
from alert_intelligence.discovery import build_incident_candidate


def _incident(alert: Alert) -> Incident:
    return Incident(
        alert_ids=[alert.id],
        service=alert.service,
        environment=alert.environment,
        severity=alert.severity,
        status=IncidentStatus.INVESTIGATING,
        title=alert.name,
        summary=alert.description,
    )


def test_raw_alert_contract_preserves_source_and_replay_identity() -> None:
    raw = RawAlert(
        source_event_id="prom-123",
        idempotency_key="prometheus:prom-123",
        source="prometheus",
        source_type="monitoring",
        application="checkout",
        service="checkout-api",
        observed_severity=AlertSeverity.HIGH,
        title="HighErrorRate",
        description="5xx rate exceeded threshold",
        raw_payload_ref="landing-pad://prom-123",
        fingerprint="checkout-errors",
    )

    assert raw.source_event_id == "prom-123"
    assert raw.raw_payload_ref.startswith("landing-pad://")
    assert raw.idempotency_key


def test_discovery_candidate_is_grounded_and_policy_owns_final_severity() -> None:
    alert = Alert(
        source="logs",
        name="Checkout unavailable",
        service="checkout-api",
        environment="prod",
        severity=AlertSeverity.WARNING,
        description="Checkout service unavailable for all users",
        labels={"source_event_id": "log-42", "service_criticality": "tier-1"},
    )
    candidate = build_incident_candidate(alert, _incident(alert))
    decision = IncidentSeverityPolicy().evaluate(candidate, service_criticality="tier-1")

    assert candidate.source_event_ids == ["log-42"]
    assert candidate.evidence[0].summary
    assert 0 <= candidate.confidence <= 1
    assert decision.final_severity == AlertSeverity.CRITICAL
    assert "critical-service-escalation" in decision.rules_fired
    assert "broad-scope-escalation" in decision.rules_fired


def test_non_production_limited_scope_is_deterministically_deescalated() -> None:
    alert = Alert(
        source="datadog",
        name="Worker warning",
        service="batch-worker",
        environment="dev",
        severity=AlertSeverity.HIGH,
        description="Warning limited to one worker",
    )
    candidate = build_incident_candidate(
        alert,
        _incident(alert),
        {"affected_users": "none", "scope": "single-instance", "recommended_severity": "high"},
    )
    decision = IncidentSeverityPolicy().evaluate(candidate, service_criticality="low")

    assert decision.final_severity == AlertSeverity.INFO
    assert decision.rules_fired == ["non-production-deescalation", "limited-scope-deescalation"]


def test_discovery_suppresses_known_internal_pipeline_noise() -> None:
    alert = Alert(
        source="logs",
        name="failed to search Jira for fingerprint abc",
        service="app",
        environment="prod",
        severity=AlertSeverity.HIGH,
        description="failed to search Jira for fingerprint abc",
    )

    candidate = build_incident_candidate(alert, _incident(alert))

    assert candidate.actionable is False
    assert "noise" in candidate.actionability_reason.lower()
