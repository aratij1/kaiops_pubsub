from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from alert_intelligence.triage import DeterministicTicketTriage
from common.incident_contracts import AuditMetadata, CanonicalAlert, CanonicalTicket, EventEnvelopeV1, TicketSeverity


def alert(**overrides) -> CanonicalAlert:
    values = {
        "alert_id": "alert-1",
        "source": "prometheus",
        "source_reference": "fp-1",
        "idempotency_key": "idem-1",
        "title": "Payments complete outage",
        "description": "All customers cannot pay",
        "affected_service": "payments",
        "environment": "prod",
        "observed_severity": "critical",
        "correlation_id": "corr-1",
        "observed_at": datetime(2026, 8, 3, tzinfo=UTC),
        "labels": {"team": "payments-sre"},
    }
    values.update(overrides)
    return CanonicalAlert(**values)


def test_p1_triage_is_explainable_and_escalated() -> None:
    ticket = DeterministicTicketTriage().triage(alert())
    assert ticket.severity == TicketSeverity.P1
    assert ticket.priority == 100
    assert ticket.escalation_required is True
    assert ticket.assigned_team == "payments-sre"
    assert ticket.evidence[0].evidence_id == "alert-1"
    assert ticket.audit_metadata.ai_used is False
    assert "critical-impact" in ticket.audit_metadata.rules_fired


def test_noise_is_classified_without_ai() -> None:
    ticket = DeterministicTicketTriage().triage(
        alert(title="Synthetic test alert", description="heartbeat", observed_severity="warning")
    )
    assert ticket.severity == TicketSeverity.P4
    assert ticket.noise is True
    assert ticket.false_positive is True


def test_ai_decision_requires_provider_model_and_evidence() -> None:
    with pytest.raises(ValidationError):
        AuditMetadata(tenant_id="t1", rationale="model classification", ai_used=True)

    base = DeterministicTicketTriage().triage(alert()).model_dump()
    base["evidence"] = []
    base["audit_metadata"] = {
        "tenant_id": "t1",
        "rationale": "model classification",
        "ai_used": True,
        "model_provider": "approved-provider",
        "model_name": "classifier-v1",
    }
    with pytest.raises(ValidationError):
        CanonicalTicket.model_validate(base)


def test_event_envelope_rejects_unknown_fields() -> None:
    event = EventEnvelopeV1(
        event_type="ticket.triaged",
        correlation_id="corr-1",
        incident_id="inc-1",
        source="alert-intelligence",
        payload={"ticket_id": "kai-alert-1"},
    )
    assert event.schema_version == "1.0"
    with pytest.raises(ValidationError):
        EventEnvelopeV1.model_validate({**event.model_dump(), "unexpected": True})

