from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
import logging
from typing import Any
from uuid import UUID

from common.config import get_settings
from common.event_publishers import build_agent_event_contract, build_event_envelope
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
logger = logging.getLogger("kaiops.approval_service")


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
    normalized_incident_id = str(incident_id or "").strip()
    if not normalized_incident_id:
        return {"incident_id": incident_id, "status": "unknown"}

    memory_payload = PENDING_INCIDENTS.get(normalized_incident_id)
    if isinstance(memory_payload, dict):
        memory_payload.setdefault("incident_id", normalized_incident_id)

    if settings.database_enabled:
        try:
            async with app.state.session_factory() as session:
                repo = IncidentRepository(session)
                incident = await repo.get_incident(normalized_incident_id)
                pending = await repo.get_pending_workflow(normalized_incident_id)
                if isinstance(incident, dict):
                    return _build_incident_context(incident, pending)
                if isinstance(pending, dict):
                    return _build_incident_context(memory_payload or {"incident_id": normalized_incident_id}, pending)
        except Exception:
            logger.exception("failed to load incident context", extra={"incident_id": normalized_incident_id})

    if isinstance(memory_payload, dict):
        return _build_incident_context(memory_payload, None)

    return {"incident_id": normalized_incident_id, "status": "unknown"}


def _build_incident_context(base_payload: dict[str, Any], pending_workflow: dict[str, Any] | None) -> dict[str, Any]:
    context = dict(base_payload or {})
    recommendation = context.get("recommendation") if isinstance(context.get("recommendation"), dict) else {}
    decision = context.get("decision") if isinstance(context.get("decision"), dict) else {}

    def _missing(value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            return not value.strip()
        return False

    if isinstance(pending_workflow, dict):
        pending_payload = pending_workflow.get("payload") if isinstance(pending_workflow.get("payload"), dict) else {}
        pending_recommendation = pending_payload.get("recommendation") if isinstance(pending_payload.get("recommendation"), dict) else {}
        pending_decision = pending_payload.get("decision") if isinstance(pending_payload.get("decision"), dict) else {}

        if not recommendation and pending_recommendation:
            recommendation = pending_recommendation
            context["recommendation"] = recommendation
        if not decision and pending_decision:
            decision = pending_decision
            context["decision"] = decision

        if _missing(context.get("incident_id")):
            context["incident_id"] = str(pending_workflow.get("incident_id") or "")
        if _missing(context.get("flow_id")):
            context["flow_id"] = str(pending_workflow.get("flow_id") or decision.get("flow_id") or "")
        if _missing(context.get("trace_id")):
            context["trace_id"] = str(pending_workflow.get("trace_id") or recommendation.get("trace_id") or "")
        if _missing(context.get("status")):
            context["status"] = str(pending_workflow.get("status") or "awaiting_approval")

    recommendation_id = (
        context.get("recommendation_id")
        or recommendation.get("id")
        or context.get("recommended_action_id")
    )
    if recommendation_id:
        context["recommendation_id"] = str(recommendation_id)

    if recommendation:
        if _missing(context.get("trace_id")):
            context["trace_id"] = str(recommendation.get("trace_id") or "")
        correlation_id = recommendation.get("correlation_id")
        if correlation_id and _missing(context.get("correlation_id")):
            context["correlation_id"] = str(correlation_id)

    if decision:
        if _missing(context.get("flow_id")):
            context["flow_id"] = str(decision.get("flow_id") or "")

    incident_id = str(context.get("incident_id") or "").strip()
    if incident_id:
        context["incident_id"] = incident_id

    return context


async def _store_and_publish(approval: Approval) -> None:
    _attach_policy_metadata(approval)
    _enforce_high_risk_human_gate(approval)
    PENDING_INCIDENTS[str(approval.incident_id)] = approval.model_dump(mode="json")
    if settings.database_enabled:
        async with app.state.session_factory() as session:
            repo = IncidentRepository(session)
            await repo.save_approval(approval)
            pending = PENDING_INCIDENTS.get(str(approval.incident_id), {})
            recommendation = pending.get("recommendation", {}) if isinstance(pending.get("recommendation"), dict) else {}
            decision = pending.get("decision", {}) if isinstance(pending.get("decision"), dict) else {}
            recommendation_id = str(approval.recommendation_id)
            status = "awaiting_approval"
            if approval.decision == ApprovalDecision.APPROVED or approval.decision == ApprovalDecision.MODIFIED:
                status = "remediating"
            elif approval.decision == ApprovalDecision.REJECTED:
                status = "failed"
            await repo.save_incident_event(
                build_event_envelope(
                    event_type="incident.approval.recorded",
                    identity={
                        "incident_id": str(approval.incident_id),
                        "alert_id": None,
                        "trace_id": str(recommendation.get("trace_id") or ""),
                        "correlation_id": str(recommendation.get("correlation_id") or "") or None,
                        "causation_id": None,
                        "parent_event_id": None,
                    },
                    scope={
                        "tenant_id": "default",
                        "service": str(pending.get("incident", {}).get("service") if isinstance(pending.get("incident"), dict) else "unknown") or "unknown",
                        "environment": str(pending.get("incident", {}).get("environment") if isinstance(pending.get("incident"), dict) else "prod") or "prod",
                        "region": None,
                        "team": None,
                    },
                    state={
                        "severity": str((recommendation.get("severity") or "warning")).lower(),
                        "status": status,
                        "owner": str(approval.approver or "") or None,
                    },
                    policy={
                        "risk_tier": str(decision.get("risk_tier") or "unknown"),
                        "execution_mode": str(decision.get("execution_mode") or "unknown"),
                        "requires_approval": decision.get("requires_approval"),
                        "policy_version": approval.metadata.get("policy_version"),
                        "policy_reason": approval.metadata.get("policy_reason"),
                    },
                    transport={
                        "provider": str(decision.get("message_bus_provider") or "unknown"),
                        "channel": APPROVAL_EVENTS,
                        "partition": None,
                        "offset": None,
                        "delivery_tag": None,
                    },
                    payload={
                        "recommendation_id": recommendation_id,
                        "decision": approval.decision.value,
                        "approver": approval.approver,
                        "channel": approval.channel,
                        "comment": approval.comment,
                        "modified_action": approval.modified_action,
                    },
                )
            )
            await session.commit()
    payload = _build_approval_event_payload(approval)
    await app.state.producer.publish(APPROVAL_EVENTS, payload, key=str(approval.incident_id))


def _build_approval_event_payload(approval: Approval) -> dict[str, Any]:
    incident_id = str(approval.incident_id)
    pending = PENDING_INCIDENTS.get(incident_id, {})
    recommendation = pending.get("recommendation", {}) if isinstance(pending.get("recommendation"), dict) else {}
    decision = pending.get("decision", {}) if isinstance(pending.get("decision"), dict) else {}
    incident = pending.get("incident", {}) if isinstance(pending.get("incident"), dict) else {}
    flow_id = str(decision.get("flow_id") or incident_id)
    recommendation_id = str(approval.recommendation_id)

    event_contract = build_agent_event_contract(
        flow_id=flow_id,
        incident_id=incident_id,
        trace_id=str(recommendation.get("trace_id") or ""),
        correlation_id=str(recommendation.get("correlation_id") or "") or None,
        agent="approval-service",
        payload={
            "decision": approval.decision.value,
            "approver": approval.approver,
            "channel": approval.channel,
            "topic": APPROVAL_EVENTS,
        },
        metadata={
            "policy_version": approval.metadata.get("policy_version"),
            "policy_reason": approval.metadata.get("policy_reason"),
            "recommendation_id": recommendation_id,
        },
        confidence=1.0,
        reasoning="approval outcome captured for gated remediation",
        citations=[f"recommendation://{recommendation_id}"],
        evidence_ids=[f"incident:{incident_id}"],
    )
    return {
        "approval": approval,
        "recommendation": recommendation,
        "decision": decision,
        "incident": incident,
        "event_contract": event_contract,
    }


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
