from __future__ import annotations

import asyncio

from common.config import get_settings
from common.kafka import KafkaConsumer, consume_forever
from common.models import Context, Incident, Recommendation
from common.repository import IncidentRepository
from common.service import create_app
from common.telemetry import EVENTS_PROCESSED
from common.topics import CONTEXT_EVENTS, RESOLUTION_EVENTS
from fastapi import FastAPI
from resolution_agent import ResolutionIntelligenceAgent

settings = get_settings()
settings.service_name = "resolution-agent"
agent = ResolutionIntelligenceAgent()
tasks: list[asyncio.Task] = []


async def startup(app: FastAPI) -> None:
    consumer = KafkaConsumer(settings, CONTEXT_EVENTS)

    async def handle(payload: dict) -> None:
        context = Context.model_validate(payload["context"])
        incident = Incident.model_validate(payload["incident"])
        recommendation = await agent.resolve(context)
        if settings.database_enabled:
            async with app.state.session_factory() as session:
                repo = IncidentRepository(session)
                await repo.save_recommendation_as_audit(recommendation)
                await session.commit()
        await app.state.producer.publish(
            RESOLUTION_EVENTS,
            {"recommendation": recommendation, "context": context, "incident": incident},
            key=str(context.incident_id),
        )
        EVENTS_PROCESSED.labels(settings.service_name, CONTEXT_EVENTS, "ok").inc()

    tasks.append(asyncio.create_task(consume_forever(consumer, handle)))


async def shutdown(_: FastAPI) -> None:
    for task in tasks:
        task.cancel()


app = create_app(title="KaiOps Resolution Intelligence Agent", settings=settings, startup=startup, shutdown=shutdown)


@app.post("/resolve", response_model=Recommendation)
async def resolve(context: Context) -> Recommendation:
    recommendation = await agent.resolve(context)
    await app.state.producer.publish(RESOLUTION_EVENTS, {"recommendation": recommendation, "context": context})
    return recommendation
