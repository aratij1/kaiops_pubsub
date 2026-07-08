from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

from alert_intelligence import AlertIntelligenceAgent
from common.config import get_settings
from common.kafka import KafkaConsumer, consume_forever as consume_kafka_forever
from common.models import Alert
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

    async def handle(payload: dict) -> None:
        alert, incident = await agent.process(Alert.model_validate(payload))
        if settings.database_enabled:
            async with app.state.session_factory() as session:
                repo = IncidentRepository(session)
                await repo.save_alert(alert)
                await repo.save_incident(incident)
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
