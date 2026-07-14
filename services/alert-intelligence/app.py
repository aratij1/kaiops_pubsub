from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

from alert_intelligence import AlertIntelligenceAgent
from common.config import get_settings
from common.event_publishers import build_event_envelope
from common.kafka import KafkaConsumer, consume_forever as consume_kafka_forever
from common.models import Alert
from common.pubsub import PubSubConsumer, consume_forever as consume_pubsub_forever
from common.rabbitmq import RabbitMQConsumer, consume_forever as consume_rabbitmq_forever
from common.repository import IncidentRepository
from common.repository_interfaces import SqlAlertHistoryRepository
from common.service import create_app
from common.telemetry import EVENTS_PROCESSED
from common.topics import ENRICHED_ALERTS, RAW_ALERTS
from fastapi import FastAPI

settings = get_settings()
settings.service_name = "alert-intelligence"
agent = AlertIntelligenceAgent()
tasks: list[asyncio.Task] = []

ConsumeRunner = Callable[[Any, Callable[[dict], Awaitable[None]]], Coroutine[Any, Any, None]]


def _build_alert_enriched_envelope(alert: Alert, incident: Any) -> dict[str, Any]:
    severity = str(getattr(alert.severity, "value", alert.severity) or "warning").strip().lower() or "warning"
    return build_event_envelope(
        event_type="incident.alert.enriched",
        identity={
            "incident_id": str(incident.id),
            "alert_id": str(alert.id),
            "trace_id": str(incident.trace_id or alert.trace_id or ""),
            "correlation_id": str(alert.correlation_id or "") or None,
            "causation_id": None,
            "parent_event_id": None,
        },
        scope={
            "tenant_id": "default",
            "service": str(alert.service or "unknown"),
            "environment": str(alert.environment or "prod"),
            "region": None,
            "team": str(alert.metadata.get("owner_team") or "") or None,
        },
        state={
            "severity": severity,
            "status": "investigating",
            "owner": None,
        },
        policy={
            "risk_tier": "unknown",
            "execution_mode": "unknown",
            "requires_approval": None,
            "policy_version": None,
            "policy_reason": "alert enriched and incident opened",
        },
        transport={
            "provider": "unknown",
            "channel": ENRICHED_ALERTS,
            "partition": None,
            "offset": None,
            "delivery_tag": None,
        },
        payload={
            "alert_name": alert.name,
            "alert_source": alert.source,
            "incident_title": incident.title,
            "service": alert.service,
        },
    )

async def startup(app: FastAPI) -> None:
    if settings.database_enabled and getattr(app.state, "session_factory", None) is not None:
        agent.alert_history_repository = SqlAlertHistoryRepository(
            session_factory=app.state.session_factory,
            max_items=2000,
        )

    workers = max(1, int(getattr(settings, "message_bus_worker_count", 1) or 1))
    consumers: list[tuple[str, Any, ConsumeRunner]] = []
    for worker in range(workers):
        consumers.append((f"rabbitmq-w{worker + 1}", RabbitMQConsumer(settings, RAW_ALERTS), consume_rabbitmq_forever))
    if settings.kafka_enabled:
        for worker in range(workers):
            consumers.insert(worker, (f"kafka-w{worker + 1}", KafkaConsumer(settings, RAW_ALERTS), consume_kafka_forever))
    if settings.gcp_pubsub_enabled:
        for worker in range(workers):
            consumers.append((f"pubsub-w{worker + 1}", PubSubConsumer(settings, RAW_ALERTS), consume_pubsub_forever))

    async def handle(payload: dict) -> None:
        raw_alert_payload = payload.get("alert") if isinstance(payload.get("alert"), dict) else payload
        alert, incident = await agent.process(Alert.model_validate(raw_alert_payload))
        if settings.database_enabled:
            async with app.state.session_factory() as session:
                repo = IncidentRepository(session)
                await repo.save_alert(alert)
                await repo.save_incident(incident)
                await repo.save_incident_event(_build_alert_enriched_envelope(alert, incident))
                await session.commit()
        await app.state.producer.publish(ENRICHED_ALERTS, {"alert": alert, "incident": incident}, key=alert.service)
        EVENTS_PROCESSED.labels(settings.service_name, RAW_ALERTS, "ok").inc()

    for source, consumer, consume_forever in consumers:
        task = asyncio.create_task(consume_forever(consumer, handle), name=f"alert-intelligence-{source}-consumer")
        tasks.append(task)


async def shutdown(_: FastAPI) -> None:
    for task in tasks:
        task.cancel()


app = create_app(title="KaiMS Alert Intelligence", settings=settings, startup=startup, shutdown=shutdown)


@app.post("/process")
async def process(alert: Alert) -> dict:
    enriched, incident = await agent.process(alert)
    await app.state.producer.publish(ENRICHED_ALERTS, {"alert": enriched, "incident": incident}, key=alert.service)
    return {"alert": enriched, "incident": incident}
