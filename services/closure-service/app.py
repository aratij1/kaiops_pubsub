from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

from closure_service import ClosureValidationAgent
from common.config import get_settings
from common.kafka import KafkaConsumer, consume_forever as consume_kafka_forever
from common.models import RemediationAction, ResolutionReport
from common.rabbitmq import RabbitMQConsumer, consume_forever as consume_rabbitmq_forever
from common.repository import IncidentRepository
from common.service import create_app
from common.telemetry import EVENTS_PROCESSED
from common.topics import CLOSURE_EVENTS, REMEDIATION_EVENTS
from fastapi import FastAPI

settings = get_settings()
settings.service_name = "closure-service"
agent = ClosureValidationAgent()
tasks: list[asyncio.Task] = []

ConsumeRunner = Callable[[Any, Callable[[dict], Awaitable[None]]], Coroutine[Any, Any, None]]


async def startup(app: FastAPI) -> None:
    workers = max(1, int(getattr(settings, "message_bus_worker_count", 1) or 1))
    consumers: list[tuple[str, Any, ConsumeRunner]] = []
    for worker in range(workers):
        consumers.append(
            (f"rabbitmq-w{worker + 1}", RabbitMQConsumer(settings, REMEDIATION_EVENTS), consume_rabbitmq_forever)
        )
    if settings.kafka_enabled:
        for worker in range(workers):
            consumers.insert(
                worker,
                (f"kafka-w{worker + 1}", KafkaConsumer(settings, REMEDIATION_EVENTS), consume_kafka_forever),
            )

    async def handle(payload: dict) -> None:
        action = RemediationAction.model_validate(payload)
        report = await validate(action)
        await app.state.producer.publish(CLOSURE_EVENTS, report, key=str(action.incident_id))
        EVENTS_PROCESSED.labels(settings.service_name, REMEDIATION_EVENTS, "ok").inc()

    for source, consumer, consume_forever in consumers:
        task = asyncio.create_task(consume_forever(consumer, handle), name=f"closure-service-{source}-consumer")
        tasks.append(task)


async def shutdown(_: FastAPI) -> None:
    for task in tasks:
        task.cancel()


app = create_app(title="KaiMS Closure Service", settings=settings, startup=startup, shutdown=shutdown)


@app.post("/validate", response_model=ResolutionReport)
async def validate(action: RemediationAction) -> ResolutionReport:
    report = await agent.validate(action)
    if settings.database_enabled:
        async with app.state.session_factory() as session:
            repo = IncidentRepository(session)
            await repo.save_report(report)
            await repo.save_knowledge_base(report)
            await session.commit()
    return report
