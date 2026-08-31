from __future__ import annotations

import pytest
from common.models import Alert, AlertSeverity, Incident
from fastapi import FastAPI
from orchestrator import OrchestratorAgent
from orchestrator.message_bus import publish_orchestration_event


class CapturePublisher:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def publish(self, topic: str, event: dict, key: str | None = None) -> None:
        self.events.append({"topic": topic, "event": event, "key": key})


def make_alert(stream_count: int) -> Alert:
    return Alert(
        source="prometheus",
        name="PaymentLatencyHigh",
        service="payments",
        severity=AlertSeverity.CRITICAL,
        description="payment latency increasing with stream load",
        labels={"stream_count": str(stream_count)},
    )


def make_incident() -> Incident:
    return Incident(
        service="payments",
        severity=AlertSeverity.CRITICAL,
        title="payments: latency",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stream_count", "expected_provider"),
    [
        (650, "kafka"),
        (100, "rabbitmq"),
    ],
)
async def test_orchestrator_keeps_deployment_transport_for_entire_workflow(stream_count: int, expected_provider: str) -> None:
    app = FastAPI()
    kafka_publisher = CapturePublisher()
    rabbitmq_publisher = CapturePublisher()
    app.state.producer = rabbitmq_publisher
    app.state.message_bus_publishers = {"kafka": kafka_publisher, "rabbitmq": rabbitmq_publisher}

    alert = make_alert(stream_count=stream_count)
    incident = make_incident()
    decision = OrchestratorAgent().decide_workflow(alert, incident).__dict__

    provider_used = await publish_orchestration_event(
        producer=app.state.producer,
        publishers=app.state.message_bus_publishers,
        topic="orchestration-events",
        alert=alert,
        incident=incident,
        decision=decision,
        deployment_provider="rabbitmq",
    )

    assert decision["message_bus_provider"] == expected_provider
    assert provider_used == "rabbitmq"
    assert len(rabbitmq_publisher.events) == 1
    assert len(kafka_publisher.events) == 0
