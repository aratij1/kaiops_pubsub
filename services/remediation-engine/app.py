from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

from common.config import get_settings
from common.kafka import KafkaConsumer, consume_forever as consume_kafka_forever
from common.models import Approval, ApprovalDecision, RemediationAction, RemediationStatus
from common.rabbitmq import RabbitMQConsumer, consume_forever as consume_rabbitmq_forever
from common.repository import IncidentRepository
from common.service import create_app
from common.telemetry import EVENTS_PROCESSED
from common.topics import APPROVAL_EVENTS, REMEDIATION_EVENTS
from fastapi import FastAPI
from remediation_engine import RemediationEngine

settings = get_settings()
settings.service_name = "remediation-engine"
engine = RemediationEngine()
tasks: list[asyncio.Task] = []

ConsumeRunner = Callable[[Any, Callable[[dict], Awaitable[None]]], Coroutine[Any, Any, None]]


async def startup(app: FastAPI) -> None:
    workers = max(1, int(getattr(settings, "message_bus_worker_count", 1) or 1))
    consumers: list[tuple[str, Any, ConsumeRunner]] = []
    for worker in range(workers):
        consumers.append(
            (f"rabbitmq-w{worker + 1}", RabbitMQConsumer(settings, APPROVAL_EVENTS), consume_rabbitmq_forever)
        )
    if settings.kafka_enabled:
        for worker in range(workers):
            consumers.insert(
                worker,
                (f"kafka-w{worker + 1}", KafkaConsumer(settings, APPROVAL_EVENTS), consume_kafka_forever),
            )

    async def handle_approval(payload: dict) -> None:
        approval = Approval.model_validate(payload)
        action = await execute_approval(approval)
        await app.state.producer.publish(REMEDIATION_EVENTS, action, key=str(action.incident_id))
        EVENTS_PROCESSED.labels(settings.service_name, APPROVAL_EVENTS, "ok").inc()

    for source, approval_consumer, consume_forever in consumers:
        task = asyncio.create_task(consume_forever(approval_consumer, handle_approval), name=f"remediation-engine-{source}-consumer")
        tasks.append(task)


async def shutdown(_: FastAPI) -> None:
    for task in tasks:
        task.cancel()


app = create_app(title="KaiMS Remediation Engine", settings=settings, startup=startup, shutdown=shutdown)


@app.post("/execute", response_model=RemediationAction)
async def execute_approval(approval: Approval) -> RemediationAction:
    if approval.decision == ApprovalDecision.REJECTED:
        action = RemediationAction(
            incident_id=approval.incident_id,
            approval_id=approval.id,
            action_type="rejected",
            target=str(approval.incident_id),
            status=RemediationStatus.SKIPPED,
            output="human rejected remediation",
        )
    else:
        action = engine.build_action(approval)
        if not engine.is_action_allowed(action.action_type):
            action.status = RemediationStatus.SKIPPED
            action.error = f"Action type '{action.action_type}' is not allowlisted"
            action.output = "remediation blocked by allowlist policy"
        else:
            action = await engine.execute(action)

    if settings.database_enabled:
        async with app.state.session_factory() as session:
            repo = IncidentRepository(session)
            await repo.save_action(action)
            await repo.save_action_audit(action)
            await session.commit()
    return action
