from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

from common.config import get_settings
from common.event_publishers import build_agent_event_contract, build_event_envelope
from common.kafka import KafkaConsumer, consume_forever as consume_kafka_forever
from common.models import Context, Incident, Recommendation
from common.rabbitmq import RabbitMQConsumer, consume_forever as consume_rabbitmq_forever
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

ConsumeRunner = Callable[[Any, Callable[[dict], Awaitable[None]]], Coroutine[Any, Any, None]]


def _build_resolution_event_payload(
    *,
    context: Context,
    incident: Incident,
    recommendation: Recommendation,
    decision_payload: dict[str, Any],
) -> dict[str, Any]:
    flow_id = str(decision_payload.get("flow_id") or incident.id)
    event_contract = build_agent_event_contract(
        flow_id=flow_id,
        incident_id=str(incident.id),
        trace_id=str(incident.trace_id or context.alert.trace_id or ""),
        correlation_id=str(context.alert.correlation_id or "") or None,
        agent="resolution-agent",
        payload={
            "recommended_action": recommendation.recommended_action,
            "risk": recommendation.risk,
            "topic": RESOLUTION_EVENTS,
        },
        metadata={
            "policy_version": recommendation.metadata.get("policy_version"),
            "policy_reason": recommendation.metadata.get("policy_reason"),
            "workflow": decision_payload.get("workflow"),
        },
        confidence=float(recommendation.confidence),
        reasoning=str(recommendation.metadata.get("reasoning") or recommendation.rationale or ""),
        citations=list(recommendation.metadata.get("citations", [])),
        evidence_ids=list(recommendation.metadata.get("evidence_ids", [])),
    )
    return {
        "recommendation": recommendation,
        "context": context,
        "incident": incident,
        "decision": decision_payload,
        "event_contract": event_contract,
    }


async def _persist_resolution_event(
    *,
    app: FastAPI,
    context: Context,
    incident: Incident,
    recommendation: Recommendation,
    decision_payload: dict[str, Any],
) -> None:
    if not settings.database_enabled or getattr(app.state, "session_factory", None) is None:
        return
    metadata = recommendation.metadata if isinstance(recommendation.metadata, dict) else {}
    orchestration = (
        metadata.get("orchestration_decision")
        if isinstance(metadata.get("orchestration_decision"), dict)
        else {}
    )
    requires_approval = decision_payload.get("requires_approval")
    if requires_approval is None:
        requires_approval = orchestration.get("requires_approval")
    status = "awaiting_approval" if bool(requires_approval) else "remediating"
    provider = (
        decision_payload.get("message_bus_provider")
        or orchestration.get("message_bus_provider")
        or "unknown"
    )
    async with app.state.session_factory() as session:
        repo = IncidentRepository(session)
        await repo.save_incident_event(
            build_event_envelope(
                event_type="incident.recommendation.generated",
                identity={
                    "incident_id": str(incident.id),
                    "alert_id": str(context.alert.id),
                    "trace_id": str(incident.trace_id or context.alert.trace_id or ""),
                    "correlation_id": str(context.alert.correlation_id or "") or None,
                    "causation_id": None,
                    "parent_event_id": None,
                },
                scope={
                    "tenant_id": "default",
                    "service": str(context.alert.service or "unknown"),
                    "environment": str(context.alert.environment or "prod"),
                    "region": None,
                    "team": str(context.alert.metadata.get("owner_team") or "") or None,
                },
                state={
                    "severity": str(getattr(context.alert.severity, "value", context.alert.severity) or "warning").lower(),
                    "status": status,
                    "owner": None,
                },
                policy={
                    "risk_tier": str(decision_payload.get("risk_tier") or orchestration.get("risk_tier") or "unknown"),
                    "execution_mode": str(decision_payload.get("execution_mode") or orchestration.get("execution_mode") or "unknown"),
                    "requires_approval": requires_approval,
                    "policy_version": decision_payload.get("policy_version") or orchestration.get("policy_version") or metadata.get("policy_version"),
                    "policy_reason": decision_payload.get("policy_reason") or orchestration.get("policy_reason") or metadata.get("policy_reason"),
                },
                transport={
                    "provider": str(provider),
                    "channel": RESOLUTION_EVENTS,
                    "partition": None,
                    "offset": None,
                    "delivery_tag": None,
                },
                ai={
                    "confidence": float(recommendation.confidence),
                    "model_provider": str((metadata.get("model_usage") or [{}])[0].get("provider") if isinstance(metadata.get("model_usage"), list) and metadata.get("model_usage") else "") or None,
                    "model_name": str((metadata.get("model_usage") or [{}])[0].get("model") if isinstance(metadata.get("model_usage"), list) and metadata.get("model_usage") else "") or None,
                    "fallback_reason": None,
                },
                payload={
                    "recommendation_id": str(recommendation.id),
                    "recommended_action": recommendation.recommended_action,
                    "root_cause": recommendation.root_cause,
                    "impact": recommendation.impact,
                    "risk": recommendation.risk,
                },
            )
        )
        await session.commit()


async def startup(app: FastAPI) -> None:
    workers = max(1, int(getattr(settings, "message_bus_worker_count", 1) or 1))
    consumers: list[tuple[str, Any, ConsumeRunner]] = []
    for worker in range(workers):
        consumers.append((f"rabbitmq-w{worker + 1}", RabbitMQConsumer(settings, CONTEXT_EVENTS), consume_rabbitmq_forever))
    if settings.kafka_enabled:
        for worker in range(workers):
            consumers.insert(
                worker,
                (f"kafka-w{worker + 1}", KafkaConsumer(settings, CONTEXT_EVENTS), consume_kafka_forever),
            )

    async def handle(payload: dict) -> None:
        context = Context.model_validate(payload["context"])
        incident = Incident.model_validate(payload["incident"])
        decision_payload = payload.get("decision", {}) if isinstance(payload.get("decision"), dict) else {}
        recommendation = await agent.resolve_with_runtime(context)
        policy_version = str(decision_payload.get("policy_version") or "").strip()
        policy_reason = str(decision_payload.get("policy_reason") or "").strip()
        if policy_version:
            recommendation.metadata["policy_version"] = policy_version
        if policy_reason:
            recommendation.metadata["policy_reason"] = policy_reason
        if decision_payload:
            recommendation.metadata["orchestration_decision"] = {
                "workflow": decision_payload.get("workflow"),
                "requires_approval": decision_payload.get("requires_approval"),
                "message_bus_provider": decision_payload.get("message_bus_provider"),
                "stream_count": decision_payload.get("stream_count"),
                "stream_threshold": decision_payload.get("stream_threshold"),
            }
        if settings.database_enabled:
            async with app.state.session_factory() as session:
                repo = IncidentRepository(session)
                await repo.save_recommendation_as_audit(recommendation)
                await session.commit()
        await _persist_resolution_event(
            app=app,
            context=context,
            incident=incident,
            recommendation=recommendation,
            decision_payload=decision_payload,
        )
        payload_out = _build_resolution_event_payload(
            context=context,
            incident=incident,
            recommendation=recommendation,
            decision_payload=decision_payload,
        )
        await app.state.producer.publish(RESOLUTION_EVENTS, payload_out, key=str(context.incident_id))
        EVENTS_PROCESSED.labels(settings.service_name, CONTEXT_EVENTS, "ok").inc()

    for source, consumer, consume_forever in consumers:
        task = asyncio.create_task(consume_forever(consumer, handle), name=f"resolution-agent-{source}-consumer")
        tasks.append(task)


async def shutdown(_: FastAPI) -> None:
    for task in tasks:
        task.cancel()


app = create_app(title="KaiMS Resolution Intelligence Agent", settings=settings, startup=startup, shutdown=shutdown)


@app.post("/resolve", response_model=Recommendation)
async def resolve(context: Context) -> Recommendation:
    recommendation = await agent.resolve_with_runtime(context)
    synthetic_incident = Incident(
        id=context.incident_id,
        service=context.alert.service,
        severity=context.alert.severity,
        title=f"{context.alert.service}: {context.alert.name}",
    )
    payload_out = _build_resolution_event_payload(
        context=context,
        incident=synthetic_incident,
        recommendation=recommendation,
        decision_payload={},
    )
    await app.state.producer.publish(RESOLUTION_EVENTS, payload_out)
    return recommendation
