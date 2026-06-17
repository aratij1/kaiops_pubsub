from __future__ import annotations

import asyncio

from common.config import get_settings
from common.kafka import KafkaConsumer, consume_forever
from common.models import Approval, ApprovalDecision, RemediationAction, RemediationStatus
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


async def startup(app: FastAPI) -> None:
    consumer = KafkaConsumer(settings, APPROVAL_EVENTS)

    async def handle(payload: dict) -> None:
        approval = Approval.model_validate(payload)
        action = await execute_approval(approval)
        await app.state.producer.publish(REMEDIATION_EVENTS, action, key=str(action.incident_id))
        EVENTS_PROCESSED.labels(settings.service_name, APPROVAL_EVENTS, "ok").inc()

    tasks.append(asyncio.create_task(consume_forever(consumer, handle)))


async def shutdown(_: FastAPI) -> None:
    for task in tasks:
        task.cancel()


app = create_app(title="KaiOps Remediation Engine", settings=settings, startup=startup, shutdown=shutdown)


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
        action = await engine.execute(action)

    if settings.database_enabled:
        async with app.state.session_factory() as session:
            repo = IncidentRepository(session)
            await repo.save_action(action)
            await session.commit()
    return action
