from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
import logging
from datetime import datetime, timezone
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
CAPACITY_PROFILES: dict[str, dict[str, Any]] = {}
ASSIGNMENTS: dict[str, dict[str, Any]] = {}
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


class CapacityProfileRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    resource_names: list[str] = Field(default_factory=list)
    weekly_hours: float = Field(default=8, gt=0, le=168)
    timezone: str = "Asia/Kolkata"
    working_days: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])
    work_start: str = Field(default="09:00", pattern=r"^\d{2}:\d{2}$")
    work_end: str = Field(default="17:00", pattern=r"^\d{2}:\d{2}$")
    active: bool = True


class AssignmentTicket(BaseModel):
    incident_id: str = Field(min_length=1)
    service: str = "unknown"
    severity: str = "medium"
    resource_names: list[str] = Field(default_factory=list)


class AutoAssignRequest(BaseModel):
    tickets: list[AssignmentTicket] = Field(default_factory=list)


def _capacity_rows() -> list[dict[str, Any]]:
    allocated: dict[str, float] = {}
    for assignment in ASSIGNMENTS.values():
        if assignment.get("status") in {"assigned", "in_progress"}:
            username = str(assignment.get("assignee") or "")
            allocated[username] = allocated.get(username, 0.0) + float(assignment.get("estimated_hours") or 0)
    rows = []
    for username, profile in sorted(CAPACITY_PROFILES.items()):
        used = allocated.get(username, 0.0)
        weekly = float(profile["weekly_hours"])
        rows.append({**profile, "allocated_hours": used, "remaining_hours": max(0.0, weekly - used)})
    return rows


@app.get("/capacity")
async def list_capacity() -> dict[str, Any]:
    return {"rows": _capacity_rows()}


@app.put("/capacity/{username}")
async def put_capacity(username: str, request: CapacityProfileRequest) -> dict[str, Any]:
    normalized = username.strip()
    if not normalized or normalized != request.username.strip():
        raise HTTPException(status_code=400, detail="username in path and payload must match")
    days = sorted(set(request.working_days))
    if any(day < 0 or day > 6 for day in days):
        raise HTTPException(status_code=422, detail="working_days must contain values from 0 through 6")
    profile = request.model_dump()
    profile.update(username=normalized, resource_names=sorted(set(filter(None, (name.strip() for name in request.resource_names)))), working_days=days)
    CAPACITY_PROFILES[normalized] = profile
    return {**profile, "allocated_hours": 0.0, "remaining_hours": profile["weekly_hours"]}


@app.get("/assignments")
async def list_assignments() -> dict[str, Any]:
    return {"rows": sorted(ASSIGNMENTS.values(), key=lambda row: row.get("created_at", ""), reverse=True)}


@app.post("/auto-assign")
async def auto_assign(request: AutoAssignRequest) -> dict[str, Any]:
    available = _capacity_rows()
    assigned = 0
    unmatched: list[str] = []
    severity_hours = {"critical": 4.0, "high": 3.0, "medium": 2.0, "low": 1.0}
    for ticket in request.tickets:
        if ticket.incident_id in ASSIGNMENTS:
            continue
        required = {name.lower() for name in [ticket.service, *ticket.resource_names] if name}
        candidates = [row for row in available if row["active"] and row["remaining_hours"] > 0 and ({name.lower() for name in row["resource_names"]} & required or "all" in {name.lower() for name in row["resource_names"]})]
        if not candidates:
            unmatched.append(ticket.incident_id)
            continue
        candidate = max(candidates, key=lambda row: row["remaining_hours"])
        hours = min(candidate["remaining_hours"], severity_hours.get(ticket.severity.lower(), 2.0))
        ASSIGNMENTS[ticket.incident_id] = {
            "incident_id": ticket.incident_id, "assignee": candidate["username"], "service": ticket.service,
            "estimated_hours": hours, "status": "assigned",
            "assignment_reason": f"Matched {ticket.service} to available responder capacity.",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        candidate["remaining_hours"] -= hours
        assigned += 1
    return {"assigned": assigned, "unmatched": unmatched, "rows": list(ASSIGNMENTS.values())}


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
