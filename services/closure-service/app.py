from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from datetime import datetime, timezone
from typing import Any

from closure_service import ClosureValidationAgent
from common.config import get_settings
from common.event_publishers import build_agent_event_contract, build_event_envelope
from common.kafka import KafkaConsumer, consume_forever as consume_kafka_forever
from common.models import Incident, IncidentStatus, RemediationAction, ResolutionReport
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


async def _persist_closure_event(
    *,
    app: FastAPI,
    action: RemediationAction,
    report: ResolutionReport,
    source_payload: dict[str, Any],
) -> None:
    if not settings.database_enabled or getattr(app.state, "session_factory", None) is None:
        return
    source_contract = source_payload.get("event_contract", {}) if isinstance(source_payload.get("event_contract"), dict) else {}
    source_recommendation = source_payload.get("source_payload", {}).get("recommendation") if isinstance(source_payload.get("source_payload"), dict) else {}
    recommendation = source_recommendation if isinstance(source_recommendation, dict) else {}
    status = "closed" if bool(report.health_restored) else "failed"

    async with app.state.session_factory() as session:
        repo = IncidentRepository(session)
        incident_payload = await repo.get_incident(str(action.incident_id)) or {}
        final_incident_payload = {
            **(incident_payload if isinstance(incident_payload, dict) else {}),
            "id": str(action.incident_id),
            "service": str((incident_payload or {}).get("service") or action.target or "unknown"),
            "title": str((incident_payload or {}).get("title") or f"Incident {action.incident_id}"),
            "environment": str((incident_payload or {}).get("environment") or "prod"),
            "severity": str((incident_payload or {}).get("severity") or recommendation.get("severity") or "warning").lower(),
            "status": IncidentStatus.CLOSED.value if report.health_restored else IncidentStatus.FAILED.value,
            "closed_at": datetime.now(timezone.utc).isoformat() if report.health_restored else (incident_payload or {}).get("closed_at"),
            "trace_id": str((incident_payload or {}).get("trace_id") or source_contract.get("trace_id") or recommendation.get("trace_id") or "") or None,
        }
        await repo.save_incident(Incident.model_validate(final_incident_payload))
        await repo.save_incident_event(
            build_event_envelope(
                event_type="incident.closure.completed",
                identity={
                    "incident_id": str(action.incident_id),
                    "alert_id": None,
                    "trace_id": str(source_contract.get("trace_id") or recommendation.get("trace_id") or ""),
                    "correlation_id": str(source_contract.get("correlation_id") or recommendation.get("correlation_id") or "") or None,
                    "causation_id": None,
                    "parent_event_id": None,
                },
                scope={
                    "tenant_id": "default",
                    "service": str(action.target or "unknown"),
                    "environment": "prod",
                    "region": None,
                    "team": None,
                },
                state={
                    "severity": str(recommendation.get("severity") or "warning").lower(),
                    "status": status,
                    "owner": None,
                },
                policy={
                    "risk_tier": "unknown",
                    "execution_mode": "unknown",
                    "requires_approval": None,
                    "policy_version": None,
                    "policy_reason": "closure validation completed",
                },
                transport={
                    "provider": "unknown",
                    "channel": CLOSURE_EVENTS,
                    "partition": None,
                    "offset": None,
                    "delivery_tag": None,
                },
                payload={
                    "report_id": str(report.id),
                    "remediation_action_id": str(action.id),
                    "action_taken": report.action_taken,
                    "health_restored": report.health_restored,
                    "alerts_cleared": report.alerts_cleared,
                },
            )
        )
        await session.commit()


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
        await _persist_closure_event(app=app, action=action, report=report, source_payload=payload)
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
