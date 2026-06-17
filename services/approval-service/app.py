from __future__ import annotations

import asyncio
from uuid import UUID

from common.config import get_settings
from common.kafka import KafkaConsumer, consume_forever
from common.models import Approval, ApprovalDecision
from common.repository import IncidentRepository
from common.service import create_app
from common.topics import APPROVAL_EVENTS, RESOLUTION_EVENTS
from fastapi import FastAPI
from pydantic import BaseModel, Field

settings = get_settings()
settings.service_name = "approval-service"
tasks: list[asyncio.Task] = []

PENDING_INCIDENTS: dict[str, dict] = {}


async def startup(app: FastAPI) -> None:
    consumer = KafkaConsumer(settings, RESOLUTION_EVENTS)

    async def handle(payload: dict) -> None:
        incident_id = str(payload["recommendation"]["incident_id"])
        PENDING_INCIDENTS[incident_id] = payload

    tasks.append(asyncio.create_task(consume_forever(consumer, handle)))


async def shutdown(_: FastAPI) -> None:
    for task in tasks:
        task.cancel()


app = create_app(title="KaiOps Approval Service", settings=settings, startup=startup, shutdown=shutdown)


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
    PENDING_INCIDENTS[str(approval.incident_id)] = approval.model_dump(mode="json")
    if settings.database_enabled:
        async with app.state.session_factory() as session:
            repo = IncidentRepository(session)
            await repo.save_approval(approval)
            await session.commit()
    await app.state.producer.publish(APPROVAL_EVENTS, approval, key=str(approval.incident_id))
