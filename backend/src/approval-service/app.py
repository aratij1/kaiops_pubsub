from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from common.config import get_settings
from common.database import ApprovalAssignmentRecord, ApprovalCapacityRecord
from common.event_publishers import build_agent_event_contract, build_event_envelope
from common.kafka import KafkaConsumer, consume_forever as consume_kafka_forever
from common.models import Approval, ApprovalDecision
from common.orchestration.execution_plan_contract import verify_plan_fingerprint
from common.rabbitmq import RabbitMQConsumer, consume_forever as consume_rabbitmq_forever
from common.repository import IncidentRepository
from common.service import create_app
from common.topics import APPROVAL_EVENTS, RESOLUTION_EVENTS
from common.tenant_identity import require_tenant_id
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select

settings = get_settings()
settings.service_name = "approval-service"
tasks: list[asyncio.Task] = []
_background_tasks: set[asyncio.Task] = set()

ConsumeRunner = Callable[[Any, Callable[[dict], Awaitable[None]]], Coroutine[Any, Any, None]]

PENDING_INCIDENTS: dict[str, dict] = {}
_HIGH_RISK_SEVERITIES = {"high", "critical"}
_NON_HUMAN_APPROVERS = {"", "system", "rca-agent", "automation-agent", "orchestrator"}
logger = logging.getLogger("kaiops.approval_service")


def _looks_like_uuid(value: Any) -> bool:
    try:
        UUID(str(value or "").strip())
    except (TypeError, ValueError):
        return False
    return True


def _first_recommendation_id(*payloads: Any) -> str:
    recommendation_keys = {
        "recommendation_id",
        "remediation_recommendation_id",
        "recommended_action_id",
    }
    object_keys = {"recommendation", "approval", "source_payload", "data", "payload", "completed_payload"}

    def visit(value: Any, *, depth: int = 0) -> str:
        if depth > 6:
            return ""
        if isinstance(value, dict):
            for key in recommendation_keys:
                token = str(value.get(key) or "").strip()
                if _looks_like_uuid(token):
                    return token
            recommendation = value.get("recommendation")
            if isinstance(recommendation, dict):
                token = str(recommendation.get("id") or "").strip()
                if _looks_like_uuid(token):
                    return token
            for key in object_keys:
                nested = value.get(key)
                if isinstance(nested, dict):
                    found = visit(nested, depth=depth + 1)
                    if found:
                        return found
            return ""
        if isinstance(value, list):
            for item in value:
                found = visit(item, depth=depth + 1)
                if found:
                    return found
        return ""

    for payload in payloads:
        found = visit(payload)
        if found:
            return found
    return ""


def _recommendation_id_from_repository_payload(payload: Any) -> str:
    token = _first_recommendation_id(payload)
    if token:
        return token
    if isinstance(payload, dict):
        direct_id = str(payload.get("id") or "").strip()
        if _looks_like_uuid(direct_id):
            return direct_id
    return ""


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
        recommendation = payload.get("recommendation", {}) if isinstance(payload.get("recommendation"), dict) else {}
        metadata = recommendation.get("metadata", {}) if isinstance(recommendation.get("metadata"), dict) else {}
        control = metadata.get("resolution_control", {}) if isinstance(metadata.get("resolution_control"), dict) else {}
        if control.get("disposition") in {"watch_only", "investigate", "execution_ready"}:
            PENDING_INCIDENTS.pop(incident_id, None)
            return
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
    recommendation_id: UUID | None = None
    tenant_id: str = Field(min_length=1, max_length=128)
    plan_id: UUID | None = None
    plan_fingerprint: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    approver: str
    approver_role: str = Field(default="hitl-reviewer", pattern="^(admin|hitl-reviewer)$")
    authorization_scope: str = Field(default="execution", pattern="^(dry_run|execution)$")
    channel: str = Field(default="web", pattern="^(slack|teams|email|web)$")
    comment: str | None = None

    @field_validator("tenant_id")
    @classmethod
    def tenant_must_be_explicit(cls, value: str) -> str:
        return require_tenant_id(value, source="approval request identity")


class ModifyRequest(ApprovalRequest):
    modified_action: str


class CapacityRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=128)
    username: str = Field(min_length=1, max_length=255)
    resource_names: list[str] = Field(min_length=1, max_length=50)
    weekly_hours: int = Field(ge=1, le=168)
    timezone: str = Field(default="UTC", max_length=64)
    working_days: list[int] = Field(default=[0, 1, 2, 3, 4], min_length=1, max_length=7)
    work_start: str = Field(default="09:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    work_end: str = Field(default="17:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    active: bool = True


class AssignmentTicket(BaseModel):
    incident_id: str = Field(min_length=1, max_length=128)
    service: str = Field(default="unknown", max_length=128)
    severity: str = Field(default="medium", max_length=32)
    resource_names: list[str] = Field(default_factory=list, max_length=50)
    estimated_hours: int | None = Field(default=None, ge=1, le=168)


class AutoAssignRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=128)
    tickets: list[AssignmentTicket] = Field(min_length=1, max_length=500)


def _capacity_payload(row: ApprovalCapacityRecord, allocated: int = 0) -> dict[str, Any]:
    return {
        "id": str(row.id), "username": row.username, "resource_names": row.resource_names or [],
        "weekly_hours": row.weekly_hours, "allocated_hours": allocated,
        "remaining_hours": max(0, row.weekly_hours - allocated), "timezone": row.timezone,
        "working_days": row.working_days or [], "work_start": row.work_start,
        "work_end": row.work_end, "active": row.active,
    }


def _is_working_now(row: ApprovalCapacityRecord) -> bool:
    try:
        local = datetime.now(ZoneInfo(row.timezone))
    except ZoneInfoNotFoundError:
        return False
    current = local.strftime("%H:%M")
    return local.weekday() in set(row.working_days or []) and row.work_start <= current < row.work_end


def _current_week_start() -> datetime:
    now = datetime.now(timezone.utc)
    return (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)


@app.get("/capacity")
async def list_capacity(tenant_id: str = Query(min_length=1, max_length=128)) -> dict[str, Any]:
    tenant_id = require_tenant_id(tenant_id, source="capacity query")
    async with app.state.session_factory() as session:
        capacities = list((await session.scalars(select(ApprovalCapacityRecord).where(ApprovalCapacityRecord.tenant_id == tenant_id).order_by(ApprovalCapacityRecord.username))).all())
        allocated = dict((await session.execute(
            select(ApprovalAssignmentRecord.assignee, func.coalesce(func.sum(ApprovalAssignmentRecord.estimated_hours), 0))
            .where(
                ApprovalAssignmentRecord.status.in_(["assigned", "in_progress"]),
                ApprovalAssignmentRecord.tenant_id == tenant_id,
                ApprovalAssignmentRecord.created_at >= _current_week_start(),
            )
            .group_by(ApprovalAssignmentRecord.assignee)
        )).all())
    return {"rows": [_capacity_payload(row, int(allocated.get(row.username, 0))) for row in capacities]}


@app.put("/capacity/{username}")
async def upsert_capacity(username: str, request: CapacityRequest) -> dict[str, Any]:
    tenant_id = require_tenant_id(request.tenant_id, source="capacity request")
    if username.strip().lower() != request.username.strip().lower():
        raise HTTPException(status_code=422, detail="Path username must match payload username")
    if any(day < 0 or day > 6 for day in request.working_days) or request.work_start >= request.work_end:
        raise HTTPException(status_code=422, detail="Working days and start/end hours are invalid")
    try:
        ZoneInfo(request.timezone)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(status_code=422, detail="Unknown timezone") from exc
    resources = sorted({value.strip().lower() for value in request.resource_names if value.strip()})
    if not resources:
        raise HTTPException(status_code=422, detail="At least one resource name is required")
    async with app.state.session_factory() as session:
        row = await session.scalar(select(ApprovalCapacityRecord).where(ApprovalCapacityRecord.tenant_id == tenant_id, func.lower(ApprovalCapacityRecord.username) == request.username.strip().lower()))
        values = request.model_dump()
        values["username"] = request.username.strip()
        values["resource_names"] = resources
        values["working_days"] = sorted(set(request.working_days))
        if row is None:
            row = ApprovalCapacityRecord(**values)
            session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
        await session.commit()
        await session.refresh(row)
    return _capacity_payload(row)


@app.get("/assignments")
async def list_assignments(tenant_id: str = Query(min_length=1, max_length=128)) -> dict[str, Any]:
    tenant_id = require_tenant_id(tenant_id, source="assignment query")
    async with app.state.session_factory() as session:
        rows = list((await session.scalars(select(ApprovalAssignmentRecord).where(ApprovalAssignmentRecord.tenant_id == tenant_id).order_by(ApprovalAssignmentRecord.created_at.desc()).limit(250))).all())
    return {"rows": [{"incident_id": row.incident_id, "assignee": row.assignee, "service": row.service, "estimated_hours": row.estimated_hours, "status": row.status, "assignment_reason": row.assignment_reason, "created_at": row.created_at.isoformat() if row.created_at else None} for row in rows]}


@app.post("/auto-assign")
async def auto_assign(request: AutoAssignRequest) -> dict[str, Any]:
    tenant_id = require_tenant_id(request.tenant_id, source="auto-assignment request")
    severity_hours = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    results: list[dict[str, Any]] = []
    async with app.state.session_factory() as session:
        capacities = list((await session.scalars(select(ApprovalCapacityRecord).where(ApprovalCapacityRecord.tenant_id == tenant_id, ApprovalCapacityRecord.active.is_(True)))).all())
        existing = {row.incident_id for row in (await session.scalars(select(ApprovalAssignmentRecord).where(ApprovalAssignmentRecord.tenant_id == tenant_id))).all()}
        allocated = dict((await session.execute(
            select(ApprovalAssignmentRecord.assignee, func.coalesce(func.sum(ApprovalAssignmentRecord.estimated_hours), 0))
            .where(
                ApprovalAssignmentRecord.status.in_(["assigned", "in_progress"]),
                ApprovalAssignmentRecord.tenant_id == tenant_id,
                ApprovalAssignmentRecord.created_at >= _current_week_start(),
            )
            .group_by(ApprovalAssignmentRecord.assignee)
        )).all())
        for ticket in request.tickets:
            if ticket.incident_id in existing:
                results.append({"incident_id": ticket.incident_id, "status": "already_assigned"})
                continue
            hours = ticket.estimated_hours or severity_hours.get(ticket.severity.lower(), 2)
            required = {ticket.service.strip().lower(), *(value.strip().lower() for value in ticket.resource_names)} - {"", "unknown"}
            eligible = []
            for capacity in capacities:
                skills = set(capacity.resource_names or [])
                remaining = capacity.weekly_hours - int(allocated.get(capacity.username, 0))
                matches = not required or bool(required & skills) or "all" in skills or "*" in skills
                if remaining >= hours and matches and _is_working_now(capacity):
                    eligible.append((remaining, -int(allocated.get(capacity.username, 0)), capacity.username, capacity))
            if not eligible:
                results.append({"incident_id": ticket.incident_id, "status": "unassigned", "reason": "No on-duty responder has matching resources and remaining capacity."})
                continue
            _, _, _, selected = max(eligible)
            reason = f"Matched {ticket.service} resources; {selected.weekly_hours - int(allocated.get(selected.username, 0))}h capacity available before assignment."
            session.add(ApprovalAssignmentRecord(tenant_id=tenant_id, incident_id=ticket.incident_id, assignee=selected.username, service=ticket.service, estimated_hours=hours, assignment_reason=reason))
            allocated[selected.username] = int(allocated.get(selected.username, 0)) + hours
            existing.add(ticket.incident_id)
            results.append({"incident_id": ticket.incident_id, "status": "assigned", "assignee": selected.username, "estimated_hours": hours, "reason": reason})
        await session.commit()
    return {"rows": results, "assigned": sum(1 for row in results if row["status"] == "assigned")}


@app.post("/approve", response_model=Approval)
async def approve(request: ApprovalRequest) -> Approval:
    approval = await _approval_from_request(request, ApprovalDecision.APPROVED)
    await _store_and_publish(approval)
    return approval


@app.post("/reject", response_model=Approval)
async def reject(request: ApprovalRequest) -> Approval:
    approval = await _approval_from_request(request, ApprovalDecision.REJECTED)
    await _store_and_publish(approval)
    return approval


@app.post("/request-evidence", response_model=Approval)
async def request_evidence(request: ApprovalRequest) -> Approval:
    if not str(request.comment or "").strip():
        raise HTTPException(status_code=422, detail="An evidence request reason is required.")
    approval = await _approval_from_request(request, ApprovalDecision.EVIDENCE_REQUESTED)
    await _store_and_publish(approval)
    return approval


@app.post("/modify", response_model=Approval)
async def modify(request: ModifyRequest) -> Approval:
    raise HTTPException(
        status_code=409,
        detail=(
            "Free-text approval modifications are disabled. Generate a new typed execution plan "
            "with a new plan_id and plan_fingerprint, then submit a new approval."
        ),
    )
    await _store_and_publish(approval)
    return approval


async def _approval_from_request(
    request: ApprovalRequest,
    decision: ApprovalDecision,
    *,
    modified_action: str | None = None,
) -> Approval:
    pending = (
        await _load_approval_context(request.incident_id, tenant_id=request.tenant_id)
        if decision == ApprovalDecision.APPROVED
        else {}
    )
    recommendation_id = request.recommendation_id or await _resolve_recommendation_id(
        request.incident_id,
        tenant_id=request.tenant_id,
    )
    recommendation = pending.get("recommendation", {}) if isinstance(pending, dict) else {}
    metadata = recommendation.get("metadata", {}) if isinstance(recommendation, dict) else {}
    plan = metadata.get("execution_plan", {}) if isinstance(metadata, dict) else {}
    if decision == ApprovalDecision.MODIFIED:
        raise HTTPException(status_code=409, detail="Modified approvals cannot authorize execution.")
    if decision == ApprovalDecision.APPROVED:
        expected_tenant = str(plan.get("tenant_id") or "").strip()
        expected_plan_id = str(plan.get("plan_id") or "").strip()
        expected_fingerprint = str(plan.get("plan_fingerprint") or "").strip()
        if not verify_plan_fingerprint(plan):
            raise HTTPException(status_code=409, detail="Approval blocked: execution plan fingerprint is invalid.")
        if not expected_tenant or expected_tenant.lower() == "default":
            raise HTTPException(status_code=409, detail="Approval blocked: execution plan has no verified tenant.")
        if request.tenant_id != expected_tenant:
            raise HTTPException(status_code=403, detail="Approval tenant does not match the execution plan tenant.")
        if str(request.plan_id or "") != expected_plan_id or request.plan_fingerprint != expected_fingerprint:
            raise HTTPException(status_code=409, detail="Approval is not bound to the current execution plan fingerprint.")
        expiry = datetime.fromisoformat(str(plan.get("expiry") or "").replace("Z", "+00:00"))
        if expiry <= datetime.now(timezone.utc):
            raise HTTPException(status_code=409, detail="Approval blocked: execution plan has expired.")
    else:
        expected_plan_id = str(request.plan_id or "") or None
        expected_fingerprint = request.plan_fingerprint
        expiry = None
    return Approval(
        tenant_id=request.tenant_id,
        incident_id=request.incident_id,
        recommendation_id=recommendation_id,
        plan_id=expected_plan_id,
        plan_fingerprint=expected_fingerprint,
        approval_expires_at=expiry,
        approver_role=request.approver_role,
        authorization_scope=request.authorization_scope,
        decision=decision,
        approver=request.approver,
        channel=request.channel,
        comment=request.comment,
        modified_action=modified_action,
        metadata={
            "execution_confirmation_required": True,
            "authorization_scope": request.authorization_scope,
            **({"execution_plan": plan} if decision == ApprovalDecision.APPROVED else {}),
        },
    )


async def _load_approval_context(incident_id: UUID, *, tenant_id: str) -> dict[str, Any]:
    normalized_incident_id = str(incident_id)
    normalized_tenant = require_tenant_id(tenant_id, source="approval request identity")
    memory_payload = PENDING_INCIDENTS.get(normalized_incident_id)
    if isinstance(memory_payload, dict):
        recommendation = memory_payload.get("recommendation")
        metadata = recommendation.get("metadata") if isinstance(recommendation, dict) else {}
        plan = metadata.get("execution_plan") if isinstance(metadata, dict) else {}
        if isinstance(plan, dict):
            plan_tenant = str(plan.get("tenant_id") or "").strip()
            if plan_tenant == normalized_tenant:
                return memory_payload
            if plan_tenant:
                raise HTTPException(status_code=403, detail="Approval tenant does not match the execution plan tenant.")

    if not settings.database_enabled:
        return memory_payload if isinstance(memory_payload, dict) else {}

    try:
        async with app.state.session_factory() as session:
            repo = IncidentRepository(session)
            incident = await repo.get_incident(normalized_incident_id, tenant_id=normalized_tenant)
            if not isinstance(incident, dict):
                raise HTTPException(status_code=404, detail="No tenant-scoped incident exists for this approval.")
            recommendation = await repo.get_latest_recommendation_for_incident(
                normalized_incident_id,
                tenant_id=normalized_tenant,
            )
            pending = await repo.get_pending_workflow(normalized_incident_id)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "failed to restore durable approval context",
            extra={"incident_id": normalized_incident_id, "tenant_id": normalized_tenant},
        )
        raise HTTPException(status_code=503, detail="Durable approval context is temporarily unavailable.") from exc

    restored = _build_incident_context(
        {
            **incident,
            **({"recommendation": recommendation} if isinstance(recommendation, dict) else {}),
        },
        pending,
    )
    if isinstance(recommendation, dict):
        restored["recommendation"] = recommendation
    PENDING_INCIDENTS[normalized_incident_id] = restored
    return restored


async def _resolve_recommendation_id(incident_id: UUID, *, tenant_id: str) -> UUID:
    normalized_incident_id = str(incident_id)
    memory_payload = PENDING_INCIDENTS.get(normalized_incident_id)
    token = _first_recommendation_id(memory_payload)
    if token:
        return UUID(token)

    if settings.database_enabled:
        try:
            async with app.state.session_factory() as session:
                repo = IncidentRepository(session)
                recommendation = await repo.get_latest_recommendation_for_incident(
                    normalized_incident_id,
                    tenant_id=tenant_id,
                )
                pending = await repo.get_pending_workflow(normalized_incident_id)
                token = _recommendation_id_from_repository_payload(recommendation) or _first_recommendation_id(pending)
                if token:
                    return UUID(token)
        except Exception:
            logger.exception("failed to resolve approval recommendation", extra={"incident_id": normalized_incident_id})

    raise HTTPException(
        status_code=422,
        detail=(
            "Approval requires a recommendation_id, and no recommendation is linked "
            f"to incident {normalized_incident_id}."
        ),
    )


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
                recommendation = await repo.get_latest_recommendation_for_incident(normalized_incident_id)
                if isinstance(recommendation, dict):
                    memory_payload = {
                        **(memory_payload if isinstance(memory_payload, dict) else {}),
                        "recommendation": recommendation,
                        "recommendation_id": _recommendation_id_from_repository_payload(recommendation),
                    }
                if isinstance(incident, dict):
                    return _build_incident_context({**incident, **(memory_payload or {})}, pending)
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

    recommendation_id = _first_recommendation_id(context, recommendation, pending_workflow)
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
    incident_id = str(approval.incident_id)
    pending_context = PENDING_INCIDENTS.get(incident_id, {})
    if not isinstance(pending_context, dict):
        pending_context = {}
    PENDING_INCIDENTS[incident_id] = {
        **pending_context,
        "approval": approval.model_dump(mode="json"),
    }
    if settings.database_enabled:
        async with app.state.session_factory() as session:
            repo = IncidentRepository(session)
            await repo.save_approval(approval)
            pending = PENDING_INCIDENTS.get(incident_id, {})
            recommendation = pending.get("recommendation", {}) if isinstance(pending.get("recommendation"), dict) else {}
            decision = pending.get("decision", {}) if isinstance(pending.get("decision"), dict) else {}
            recommendation_id = str(approval.recommendation_id)
            status = "awaiting_approval"
            if approval.decision == ApprovalDecision.APPROVED:
                status = "approved"
            elif approval.decision == ApprovalDecision.REJECTED:
                status = "failed"
            elif approval.decision == ApprovalDecision.EVIDENCE_REQUESTED:
                status = "investigating"
            await repo.update_incident_approval_status(
                approval.incident_id,
                status=status,
                approval=approval,
            )
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
                        "tenant_id": approval.tenant_id,
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
                        "authorization_scope": approval.authorization_scope,
                    },
                )
            )
            await session.commit()
    payload = _build_approval_event_payload(approval)
    if settings.temporal_pilot_enabled:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{settings.orchestrator_url.rstrip('/')}/temporal/workflows/{approval.incident_id}/approval",
                    json=approval.model_dump(mode="json"),
                )
                response.raise_for_status()
        except Exception:
            logger.exception("temporal approval signal failed; publishing existing approval event fallback")
            await app.state.producer.publish(APPROVAL_EVENTS, payload, key=str(approval.incident_id))
    else:
        await app.state.producer.publish(APPROVAL_EVENTS, payload, key=str(approval.incident_id))
    _publish_evaluation_feedback(approval)


async def _post_evaluation_feedback(recommendation_id: str, body: dict[str, Any]) -> None:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f"{settings.evaluation_service_url.rstrip('/')}/evaluations/by-recommendation/{recommendation_id}/feedback",
                json=body,
            )
        response.raise_for_status()
    except Exception as exc:
        logger.warning("evaluation_service_feedback_publish_failed", extra={"error": str(exc)})


def _publish_evaluation_feedback(approval: Approval) -> None:
    """Fire-and-forget: never awaited, never allowed to affect the approval flow."""
    body = {
        "decision": approval.decision.value,
        "approver": approval.approver,
        "comment": approval.comment,
    }
    task = asyncio.create_task(_post_evaluation_feedback(str(approval.recommendation_id), body))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


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
            "authorization_scope": approval.authorization_scope,
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
    signed_envelope = build_event_envelope(
        event_type="incident.approval.decided",
        identity={
            "incident_id": incident_id,
            "alert_id": None,
            "trace_id": str(recommendation.get("trace_id") or ""),
            "correlation_id": str(recommendation.get("correlation_id") or "") or None,
            "causation_id": None,
            "parent_event_id": None,
        },
        scope={
            "tenant_id": approval.tenant_id,
            "service": str(incident.get("service") or "unknown"),
            "environment": str(incident.get("environment") or "unknown"),
        },
        state={"status": approval.decision.value},
        policy={"requires_approval": True},
        transport={"provider": "message-bus", "channel": APPROVAL_EVENTS},
        payload={
            "approval_id": str(approval.id),
            "recommendation_id": recommendation_id,
            "plan_id": str(approval.plan_id or ""),
            "plan_fingerprint": str(approval.plan_fingerprint or ""),
            "decision": approval.decision.value,
            "authorization_scope": approval.authorization_scope,
        },
    )
    return {
        "approval": approval,
        "recommendation": recommendation,
        "decision": decision,
        "incident": incident,
        "event_contract": event_contract,
        "signed_envelope": signed_envelope,
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
