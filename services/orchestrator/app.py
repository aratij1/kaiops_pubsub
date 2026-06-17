from __future__ import annotations

import asyncio

import httpx
from common.config import get_settings
from common.kafka import KafkaConsumer, consume_forever
from common.models import Alert, Incident
from common.service import create_app
from common.telemetry import EVENTS_PROCESSED
from common.topics import ENRICHED_ALERTS
from fastapi import FastAPI
from orchestrator import OrchestratorAgent

settings = get_settings()
settings.service_name = "orchestrator"
agent = OrchestratorAgent()
tasks: list[asyncio.Task] = []


async def startup(app: FastAPI) -> None:
    consumer = KafkaConsumer(settings, ENRICHED_ALERTS)

    async def handle(payload: dict) -> None:
        alert = Alert.model_validate(payload["alert"])
        incident = Incident.model_validate(payload["incident"])
        decision = agent.decide_workflow(alert, incident)
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"{settings.context_agent_url}/collect",
                json={
                    "alert": alert.model_dump(mode="json"),
                    "incident": incident.model_dump(mode="json"),
                    "decision": decision.__dict__,
                },
            )
        EVENTS_PROCESSED.labels(settings.service_name, ENRICHED_ALERTS, "ok").inc()

    tasks.append(asyncio.create_task(consume_forever(consumer, handle)))


async def shutdown(_: FastAPI) -> None:
    for task in tasks:
        task.cancel()


app = create_app(title="KaiOps Orchestrator", settings=settings, startup=startup, shutdown=shutdown)


@app.post("/decide")
async def decide(payload: dict) -> dict:
    alert = Alert.model_validate(payload["alert"])
    incident = Incident.model_validate(payload["incident"])
    return agent.decide_workflow(alert, incident).__dict__
