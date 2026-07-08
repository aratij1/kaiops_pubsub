from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any
from uuid import UUID

from common.config import get_settings
from common.kafka import KafkaConsumer, consume_forever as consume_kafka_forever
from common.models import Approval, ApprovalDecision
from common.rabbitmq import RabbitMQConsumer, consume_forever as consume_rabbitmq_forever
from common.repository import IncidentRepository
from common.service import create_app
from common.topics import APPROVAL_EVENTS, RESOLUTION_EVENTS
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

settings = get_settings()
settings.service_name = "approval-service"
tasks: list[asyncio.Task] = []

ConsumeRunner = Callable[[Any, Callable[[dict], Awaitable[None]]], Coroutine[Any, Any, None]]

PENDING_INCIDENTS: dict[str, dict] = {}
_HIGH_RISK_SEVERITIES = {"high", "critical"}
_NON_HUMAN_APPROVERS = {"", "system", "rca-agent", "automation-agent", "orchestrator"}


async def startup(app: FastAPI) -> None:
    workers = max(1, int(getattr(settings, "message_bus_worker_count", 1) or 1))
    consumers: list[tuple[str, Any, ConsumeRunner]] = []
    for worker in range(workers):
        consumers.append(
            (f"rabbitmq-w{worker + 1}", RabbitMQConsumer(settings, RESOLUTION_EVENTS), consume_rabbitmq_forever)
        )
    if settings.kafka_enabled:
        for worker in range(workers):
            consumers.insert(
                worker,
                (f"kafka-w{worker + 1}", KafkaConsumer(settings, RESOLUTION_EVENTS), consume_kafka_forever),
            )

    async def handle(payload: dict) -> None:
        incident_id = str(payload["recommendation"]["incident_id"])
        PENDING_INCIDENTS[incident_id] = payload

    for source, consumer, consume_forever in consumers:
        task = asyncio.create_task(consume_forever(consumer, handle), name=f"approval-service-{source}-consumer")
        tasks.append(task)


async def shutdown(_: FastAPI) -> None:
    for task in tasks:
        task.cancel()


app = create_app(title="KaiMS Approval Service", settings=settings, startup=startup, shutdown=shutdown)


class ApprovalRequest(BaseModel):
    incident_id: UUID
    recommendation_id: UUID
    approver: str
    channel: str = Field(default="web", pattern="^(slack|teams|email|web)$")
    comment: str | None = None


class ModifyRequest(ApprovalRequest):
    modified_action: str


@app.post("/approve", response_model=Approval)
async def approve(request: ApprovalRequest) -> Approval:
    approval = Approval(
        incident_id=request.incident_id,
        recommendation_id=request.recommendation_id,
        decision=ApprovalDecision.APPROVED,
        approver=request.approver,
        channel=request.channel,
        comment=request.comment,
    )
    await _store_and_publish(approval)
    return approval


@app.post("/reject", response_model=Approval)
async def reject(request: ApprovalRequest) -> Approval:
    approval = Approval(
        incident_id=request.incident_id,
        recommendation_id=request.recommendation_id,
        decision=ApprovalDecision.REJECTED,
        approver=request.approver,
        channel=request.channel,
        comment=request.comment,
    )
    await _store_and_publish(approval)
    return approval


@app.post("/modify", response_model=Approval)
async def modify(request: ModifyRequest) -> Approval:
    approval = Approval(
        incident_id=request.incident_id,
        recommendation_id=request.recommendation_id,
        decision=ApprovalDecision.MODIFIED,
        approver=request.approver,
        channel=request.channel,
        comment=request.comment,
        modified_action=request.modified_action,
    )
    await _store_and_publish(approval)
    return approval


@app.get("/incident/{incident_id}")
async def get_incident(incident_id: str) -> dict:
    if settings.database_enabled:
        async with app.state.session_factory() as session:
            repo = IncidentRepository(session)
            incident = await repo.get_incident(incident_id)
            if incident:
                return incident
    return PENDING_INCIDENTS.get(incident_id, {"incident_id": incident_id, "status": "unknown"})


async def _store_and_publish(approval: Approval) -> None:
    _attach_policy_metadata(approval)
    _enforce_high_risk_human_gate(approval)
    PENDING_INCIDENTS[str(approval.incident_id)] = approval.model_dump(mode="json")
    if settings.database_enabled:
        async with app.state.session_factory() as session:
            repo = IncidentRepository(session)
            await repo.save_approval(approval)
            await session.commit()
    await app.state.producer.publish(APPROVAL_EVENTS, approval, key=str(approval.incident_id))


def _pending_severity_for_incident(incident_id: str) -> str:
    payload = PENDING_INCIDENTS.get(incident_id, {})
    if not isinstance(payload, dict):
        return ""

    recommendation = payload.get("recommendation", {})
    if isinstance(recommendation, dict):
        severity = str(recommendation.get("severity") or "").strip().lower()
        if severity:
            return severity

    incident = payload.get("incident", {})
    if isinstance(incident, dict):
        return str(incident.get("severity") or "").strip().lower()

    return ""


def _attach_policy_metadata(approval: Approval) -> None:
    payload = PENDING_INCIDENTS.get(str(approval.incident_id), {})
    if not isinstance(payload, dict):
        return

    decision = payload.get("decision", {}) if isinstance(payload.get("decision"), dict) else {}
    recommendation = payload.get("recommendation", {}) if isinstance(payload.get("recommendation"), dict) else {}
    recommendation_metadata = recommendation.get("metadata", {}) if isinstance(recommendation.get("metadata"), dict) else {}

    policy_version = str(
        decision.get("policy_version") or recommendation_metadata.get("policy_version") or ""
    ).strip()
    policy_reason = str(
        decision.get("policy_reason") or recommendation_metadata.get("policy_reason") or ""
    ).strip()

    if policy_version:
        approval.metadata["policy_version"] = policy_version
    if policy_reason:
        approval.metadata["policy_reason"] = policy_reason
    if decision:
        approval.metadata["orchestration_decision"] = {
            "workflow": decision.get("workflow"),
            "requires_approval": decision.get("requires_approval"),
            "message_bus_provider": decision.get("message_bus_provider"),
            "stream_count": decision.get("stream_count"),
            "stream_threshold": decision.get("stream_threshold"),
        }


def _enforce_high_risk_human_gate(approval: Approval) -> None:
    severity = _pending_severity_for_incident(str(approval.incident_id))
    if severity not in _HIGH_RISK_SEVERITIES:
        return

    approver = str(approval.approver or "").strip().lower()
    if approver in _NON_HUMAN_APPROVERS or approver.endswith("-agent"):
        raise HTTPException(
            status_code=422,
            detail="High/critical incidents require a human approver identity.",
        )
