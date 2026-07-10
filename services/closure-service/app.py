from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

from closure_service import ClosureValidationAgent
from common.config import get_settings
from common.event_publishers import build_agent_event_contract
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


def _extract_remediation_action_payload(payload: dict[str, Any]) -> dict[str, Any]:
    action = payload.get("remediation_action") if isinstance(payload, dict) else None
    if isinstance(action, dict):
        return action
    return payload


def _build_closure_event_payload(
    *,
    action: RemediationAction,
    report: ResolutionReport,
    source_payload: dict[str, Any],
) -> dict[str, Any]:
    incident_id = str(action.incident_id)
    source_contract = source_payload.get("event_contract", {}) if isinstance(source_payload.get("event_contract"), dict) else {}
    flow_id = str(source_contract.get("flow_id") or incident_id)
    trace_id = str(source_contract.get("trace_id") or "")
    correlation_id = str(source_contract.get("correlation_id") or "") or None

    event_contract = build_agent_event_contract(
        flow_id=flow_id,
        incident_id=incident_id,
        trace_id=trace_id,
        correlation_id=correlation_id,
        agent="closure-service",
        payload={
            "action_taken": report.action_taken,
            "health_restored": report.health_restored,
            "alerts_cleared": report.alerts_cleared,
            "topic": CLOSURE_EVENTS,
        },
        metadata={
            "root_cause": report.root_cause,
            "impact": report.impact,
        },
        confidence=1.0 if report.health_restored else 0.7,
        reasoning="closure validation derived from remediation outcome and health checks",
        citations=[f"report://{report.id}"],
        evidence_ids=[f"action:{action.id}", f"incident:{incident_id}"],
    )
    return {
        "report": report,
        "remediation_action": action,
        "event_contract": event_contract,
    }


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
        action = RemediationAction.model_validate(_extract_remediation_action_payload(payload))
        report = await validate(action)
        payload_out = _build_closure_event_payload(action=action, report=report, source_payload=payload)
        await app.state.producer.publish(CLOSURE_EVENTS, payload_out, key=str(action.incident_id))
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
