from __future__ import annotations

import asyncio

from fastapi import FastAPI

from alert_intelligence import AlertIntelligenceAgent
from common.config import get_settings
from common.kafka import KafkaConsumer, consume_forever
from common.models import Alert
from common.repository import IncidentRepository
from common.service import create_app
from common.telemetry import EVENTS_PROCESSED
from common.topics import ENRICHED_ALERTS, RAW_ALERTS

settings = get_settings()
settings.service_name = "alert-intelligence"
agent = AlertIntelligenceAgent()
tasks: list[asyncio.Task] = []


async def startup(app: FastAPI) -> None:
    consumer = KafkaConsumer(settings, RAW_ALERTS)

    async def handle(payload: dict) -> None:
        alert, incident = agent.process(Alert.model_validate(payload))
        if settings.database_enabled:
            async with app.state.session_factory() as session:
                repo = IncidentRepository(session)
                await repo.save_alert(alert)
                await repo.save_incident(incident)
                await session.commit()
        await app.state.producer.publish(ENRICHED_ALERTS, {"alert": alert, "incident": incident}, key=alert.service)
        EVENTS_PROCESSED.labels(settings.service_name, RAW_ALERTS, "ok").inc()

    tasks.append(asyncio.create_task(consume_forever(consumer, handle)))


async def shutdown(_: FastAPI) -> None:
    for task in tasks:
        task.cancel()


app = create_app(title="KaiOps Alert Intelligence", settings=settings, startup=startup, shutdown=shutdown)


@app.post("/process")
async def process(alert: Alert) -> dict:
    enriched, incident = agent.process(alert)
    await app.state.producer.publish(ENRICHED_ALERTS, {"alert": enriched, "incident": incident}, key=alert.service)
    return {"alert": enriched, "incident": incident}
