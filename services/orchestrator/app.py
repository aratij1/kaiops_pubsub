from __future__ import annotations

import asyncio

from common.config import get_settings
from common.event_publishers import RabbitMQPublisher, build_orchestration_envelope
from common.repository import IncidentRepository
from common.kafka import KafkaConsumer, consume_forever as consume_kafka_forever
from common.logging import get_logger
from common.models import Alert, Incident
from common.rabbitmq import RabbitMQConsumer, consume_forever as consume_rabbitmq_forever
from common.service import create_app
from common.telemetry import EVENTS_PROCESSED
from common.topics import ENRICHED_ALERTS, ORCHESTRATION_EVENTS
from fastapi import FastAPI
from orchestrator.message_bus import publish_orchestration_event
from orchestrator import OrchestratorAgent

settings = get_settings()
settings.service_name = "orchestrator"
agent = OrchestratorAgent()
tasks: list[asyncio.Task] = []
logger = get_logger(__name__)


async def _persist_orchestration_event(app: FastAPI, envelope: dict) -> None:
    session_factory = getattr(app.state, "session_factory", None)
    if session_factory is None:
        logger.warning("orchestrator metadata persistence skipped; database session factory unavailable")
        return

    async with session_factory() as session:
        repo = IncidentRepository(session)
        await repo.save_incident_event(envelope)
        await session.commit()


def _build_ingress_consumers() -> list[tuple[str, object, object]]:
    workers = max(1, int(getattr(settings, "message_bus_worker_count", 1) or 1))
    consumers: list[tuple[str, object, object]] = []
    for worker in range(workers):
        consumers.append((f"rabbitmq-w{worker + 1}", RabbitMQConsumer(settings, ENRICHED_ALERTS), consume_rabbitmq_forever))
    if settings.kafka_enabled:
        for worker in range(workers):
            consumers.insert(
                worker,
                (f"kafka-w{worker + 1}", KafkaConsumer(settings, ENRICHED_ALERTS), consume_kafka_forever),
            )
    return consumers


async def startup(app: FastAPI) -> None:
    app.state.message_bus_publishers = {"rabbitmq": app.state.producer}

    if settings.kafka_enabled:
        app.state.message_bus_publishers["kafka"] = app.state.producer

    if settings.kafka_enabled:
        rabbitmq_publisher = RabbitMQPublisher(settings)
        try:
            await rabbitmq_publisher.start()
            app.state.message_bus_publishers["rabbitmq"] = rabbitmq_publisher
        except Exception:
            logger.exception("rabbitmq publisher unavailable; fallback publisher remains active")
            app.state.rabbitmq_publisher = None
        else:
            app.state.rabbitmq_publisher = rabbitmq_publisher
    else:
        app.state.rabbitmq_publisher = None

    async def handle(payload: dict) -> None:
        alert = Alert.model_validate(payload["alert"])
        incident = Incident.model_validate(payload["incident"])
        decision = await agent.decide_workflow_async(alert, incident)
        transport_provider = str(decision.__dict__.get("message_bus_provider") or "kafka")
        event_envelope = build_orchestration_envelope(
            alert=alert,
            incident=incident,
            decision=decision.__dict__,
            transport_provider=transport_provider,
            channel=ORCHESTRATION_EVENTS,
        )
        try:
            await _persist_orchestration_event(app, event_envelope)
        except Exception:
            logger.exception("orchestrator metadata persistence failed")
        provider_used = await publish_orchestration_event(
            producer=app.state.producer,
            publishers=getattr(app.state, "message_bus_publishers", {}),
            topic=ORCHESTRATION_EVENTS,
            alert=alert,
            incident=incident,
            decision=decision.__dict__,
        )
        EVENTS_PROCESSED.labels(settings.service_name, f"{ENRICHED_ALERTS}:{provider_used}", "ok").inc()

    for source, consumer, consume_forever in _build_ingress_consumers():
        task = asyncio.create_task(consume_forever(consumer, handle), name=f"orchestrator-{source}-consumer")
        tasks.append(task)


async def shutdown(app: FastAPI) -> None:
    for task in tasks:
        task.cancel()
    rabbitmq_publisher = getattr(app.state, "rabbitmq_publisher", None)
    if rabbitmq_publisher is not None:
        await rabbitmq_publisher.stop()


app = create_app(title="KaiMS Orchestrator", settings=settings, startup=startup, shutdown=shutdown)


@app.post("/decide")
async def decide(payload: dict) -> dict:
    alert = Alert.model_validate(payload["alert"])
    incident = Incident.model_validate(payload["incident"])
    return (await agent.decide_workflow_async(alert, incident)).__dict__
