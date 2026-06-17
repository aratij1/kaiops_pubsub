from __future__ import annotations

import asyncio

from fastapi import FastAPI

from closure_service import ClosureValidationAgent
from common.config import get_settings
from common.kafka import KafkaConsumer, consume_forever
from common.models import RemediationAction, ResolutionReport
from common.repository import IncidentRepository
from common.service import create_app
from common.telemetry import EVENTS_PROCESSED
from common.topics import CLOSURE_EVENTS, REMEDIATION_EVENTS

settings = get_settings()
settings.service_name = "closure-service"
agent = ClosureValidationAgent()
tasks: list[asyncio.Task] = []


async def startup(app: FastAPI) -> None:
    consumer = KafkaConsumer(settings, REMEDIATION_EVENTS)

    async def handle(payload: dict) -> None:
        action = RemediationAction.model_validate(payload)
        report = await validate(action)
        await app.state.producer.publish(CLOSURE_EVENTS, report, key=str(action.incident_id))
        EVENTS_PROCESSED.labels(settings.service_name, REMEDIATION_EVENTS, "ok").inc()

    tasks.append(asyncio.create_task(consume_forever(consumer, handle)))


async def shutdown(_: FastAPI) -> None:
    for task in tasks:
        task.cancel()


app = create_app(title="KaiOps Closure Service", settings=settings, startup=startup, shutdown=shutdown)


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
