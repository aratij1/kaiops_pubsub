from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from common.models import Alert, AlertSeverity, Incident
MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "orchestrator" / "app.py"
SPEC = importlib.util.spec_from_file_location("orchestrator_service_app", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
orchestrator_app = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(orchestrator_app)


class FakeSession:
    def __init__(self) -> None:
        self.committed = False
        self.saved_envelopes: list[dict] = []

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True


class FakeRepository:
    def __init__(self, session: FakeSession) -> None:
        self.session = session

    async def save_incident_event(self, envelope: dict) -> None:
        self.session.saved_envelopes.append(envelope)


@pytest.mark.asyncio
async def test_orchestrator_persists_metadata_envelope_before_publish(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_session = FakeSession()
    app = SimpleNamespace(state=SimpleNamespace(session_factory=lambda: fake_session))

    monkeypatch.setattr(orchestrator_app, "IncidentRepository", FakeRepository)

    alert = Alert(
        source="prometheus",
        name="PaymentsLatencyHigh",
        service="payments",
        severity=AlertSeverity.CRITICAL,
        description="latency increased",
    )
    incident = Incident(service="payments", severity=AlertSeverity.CRITICAL, title="payments latency")
    decision = {
        "message_bus_provider": "rabbitmq",
        "risk_tier": "high",
        "execution_mode": "human-approval",
        "requires_approval": True,
        "policy_version": "policy-v1",
        "policy_reason": "critical severity",
        "workflow": "approval-gated",
        "next_action": "notify-oncall",
    }

    envelope = orchestrator_app.build_orchestration_envelope(
        alert=alert,
        incident=incident,
        decision=decision,
        transport_provider="rabbitmq",
        channel="orchestration-events",
    )

    await orchestrator_app._persist_orchestration_event(app, envelope)

    assert fake_session.committed is True
    assert len(fake_session.saved_envelopes) == 1
    assert fake_session.saved_envelopes[0]["event_type"] == "incident.workflow.selected"
    assert fake_session.saved_envelopes[0]["identity"]["incident_id"] == str(incident.id)
