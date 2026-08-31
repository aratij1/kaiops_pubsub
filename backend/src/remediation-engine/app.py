from __future__ import annotations

import asyncio
import re
import hashlib
import os
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any
from uuid import UUID

import httpx

from ai_workbench_common.agent_runtime import PolicyViolation
from common.config import get_settings
from common.continuous_learning import validate_automatic_runbook_use
from common.event_publishers import build_agent_event_contract, build_event_envelope
from common.kafka import KafkaConsumer, consume_forever as consume_kafka_forever
from common.models import Approval, ApprovalDecision, RemediationAction, RemediationStatus, utc_now
from common.rabbitmq import RabbitMQConsumer, consume_forever as consume_rabbitmq_forever
from common.repository import IncidentRepository
from common.service import create_app
from common.telemetry import EVENTS_PROCESSED
from common.topics import APPROVAL_EVENTS, REMEDIATION_EVENTS, RESOLUTION_EVENTS
from fastapi import FastAPI, Header, HTTPException
from remediation_engine import RemediationEngine
from remediation_engine.execution_contract import bind_execution_contract, verify_execution_contract

settings = get_settings()
settings.service_name = "remediation-engine"
engine = RemediationEngine()
tasks: list[asyncio.Task] = []
idempotency_locks: dict[str, asyncio.Lock] = {}

ConsumeRunner = Callable[[Any, Callable[[dict], Awaitable[None]]], Coroutine[Any, Any, None]]


def _first_non_empty(*values: Any) -> str | None:
    for value in values:
        token = str(value or "").strip()
        if token:
            return token
    return None


def _looks_like_uuid(token: str | None) -> bool:
    if not token:
        return False
    try:
        UUID(str(token))
    except (TypeError, ValueError):
        return False
    return True


def _execution_plan_fingerprint(action: RemediationAction) -> str:
    plan = action.parameters.get("execution_plan")
    plan = plan if isinstance(plan, dict) else {}
    normalized = {
        key: [str(item).strip() for item in plan.get(key, []) if str(item).strip()]
        for key in ("commands", "scripts", "queries")
        if isinstance(plan.get(key, []), list)
    }
    return hashlib.sha256(repr(normalized).encode("utf-8")).hexdigest()


def _extract_resolution_context(source_payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    recommendation = source_payload.get("recommendation", {}) if isinstance(source_payload.get("recommendation"), dict) else {}
    decision = source_payload.get("decision", {}) if isinstance(source_payload.get("decision"), dict) else {}
    incident = source_payload.get("incident", {}) if isinstance(source_payload.get("incident"), dict) else {}
    metadata = recommendation.get("metadata", {}) if isinstance(recommendation.get("metadata"), dict) else {}
    orchestration = metadata.get("orchestration_decision", {}) if isinstance(metadata.get("orchestration_decision"), dict) else {}
    return recommendation, decision, incident, orchestration


def _derive_remediation_target(source_payload: dict[str, Any], action: RemediationAction) -> str | None:
    recommendation, _, incident, _ = _extract_resolution_context(source_payload)
    metadata = recommendation.get("metadata", {}) if isinstance(recommendation.get("metadata"), dict) else {}

    candidate_target = _first_non_empty(
        action.target,
        metadata.get("remediation_target"),
        recommendation.get("target"),
        recommendation.get("resource"),
        incident.get("deployment"),
        incident.get("service"),
    )
    if candidate_target and _looks_like_uuid(candidate_target):
        return _first_non_empty(incident.get("service"), metadata.get("service"), candidate_target)
    return candidate_target


def _enrich_action_from_source_payload(action: RemediationAction, source_payload: dict[str, Any]) -> RemediationAction:
    recommendation, _, incident, _ = _extract_resolution_context(source_payload)
    metadata = recommendation.get("metadata", {}) if isinstance(recommendation.get("metadata"), dict) else {}

    target = _derive_remediation_target(source_payload, action)
    if target:
        action.target = target

    service = _first_non_empty(incident.get("service"), metadata.get("service"))
    if service and not str(action.parameters.get("service") or "").strip():
        action.parameters["service"] = service

    environment = _first_non_empty(incident.get("environment"), metadata.get("environment"))
    if environment and not str(action.parameters.get("environment") or "").strip():
        action.parameters["environment"] = environment

    recommended_action = _first_non_empty(recommendation.get("recommended_action"), recommendation.get("action"))
    if recommended_action and not str(action.parameters.get("recommended_action") or "").strip():
        action.parameters["recommended_action"] = recommended_action

    root_cause = _first_non_empty(recommendation.get("root_cause"), recommendation.get("rationale"))
    if root_cause and not str(action.parameters.get("root_cause") or "").strip():
        action.parameters["root_cause"] = root_cause

    impact = _first_non_empty(recommendation.get("impact"))
    if impact and not str(action.parameters.get("impact") or "").strip():
        action.parameters["impact"] = impact

    return action


def _extract_approval_payload(payload: dict[str, Any]) -> dict[str, Any]:
    approval = payload.get("approval") if isinstance(payload, dict) else None
    if isinstance(approval, dict):
        return approval
    return payload


def _build_remediation_event_payload(
    *,
    action: RemediationAction,
    source_payload: dict[str, Any],
    source: str,
) -> dict[str, Any]:
    incident_id = str(action.incident_id)
    recommendation = source_payload.get("recommendation", {}) if isinstance(source_payload.get("recommendation"), dict) else {}
    decision = source_payload.get("decision", {}) if isinstance(source_payload.get("decision"), dict) else {}
    flow_id = str(decision.get("flow_id") or incident_id)
    trace_id = str(recommendation.get("trace_id") or "")
    correlation_id = str(recommendation.get("correlation_id") or "") or None

    event_contract = build_agent_event_contract(
        flow_id=flow_id,
        incident_id=incident_id,
        trace_id=trace_id,
        correlation_id=correlation_id,
        agent="remediation-engine",
        payload={
            "action_type": action.action_type,
            "status": action.status.value,
            "topic": REMEDIATION_EVENTS,
            "source": source,
        },
        metadata={
            "policy_version": action.parameters.get("policy_version"),
            "policy_reason": action.parameters.get("policy_reason") or action.metadata.get("policy_reason"),
        },
        confidence=1.0 if action.status.value == "succeeded" else 0.6,
        reasoning="remediation execution result captured for closure validation",
        citations=[f"action://{action.id}"],
        evidence_ids=[f"incident:{incident_id}"],
    )
    return {
        "remediation_action": action,
        "source_payload": source_payload,
        "event_contract": event_contract,
    }


async def _persist_remediation_event(
    *,
    app: FastAPI,
    action: RemediationAction,
    source_payload: dict[str, Any],
    source: str,
) -> None:
    if not settings.database_enabled or getattr(app.state, "session_factory", None) is None:
        return
    recommendation, decision, incident, orchestration = _extract_resolution_context(source_payload)
    recommendation_metadata = recommendation.get("metadata", {}) if isinstance(recommendation.get("metadata"), dict) else {}
    source_event_contract = source_payload.get("event_contract", {}) if isinstance(source_payload.get("event_contract"), dict) else {}
    source_transport = source_event_contract.get("transport", {}) if isinstance(source_event_contract.get("transport"), dict) else {}

    service_name = _first_non_empty(
        action.parameters.get("service"),
        incident.get("service"),
        recommendation_metadata.get("service"),
        action.target,
        "unknown",
    ) or "unknown"
    if _looks_like_uuid(service_name):
        service_name = _first_non_empty(incident.get("service"), recommendation_metadata.get("service"), "unknown") or "unknown"

    severity_value = _first_non_empty(recommendation.get("severity"), incident.get("severity"), "warning") or "warning"
    risk_tier_value = _first_non_empty(decision.get("risk_tier"), orchestration.get("risk_tier"), recommendation.get("risk"), "medium") or "medium"
    execution_mode_value = _first_non_empty(decision.get("execution_mode"), orchestration.get("execution_mode"), "automated") or "automated"
    transport_provider_value = _first_non_empty(
        decision.get("message_bus_provider"),
        orchestration.get("message_bus_provider"),
        source_transport.get("provider"),
        "rabbitmq",
    ) or "rabbitmq"
    source_channel_value = _first_non_empty(source_transport.get("channel"), source)

    action_status = str(action.status.value or "pending").lower()
    state_status = "remediating"
    if action_status == "succeeded":
        state_status = "validating"
    elif action_status in {"failed", "rejected", "skipped"}:
        state_status = "failed"

    async with app.state.session_factory() as session:
        repo = IncidentRepository(session)
        await repo.save_incident_event(
            build_event_envelope(
                event_type="incident.remediation.executed",
                identity={
                    "incident_id": str(action.incident_id),
                    "alert_id": None,
                    "trace_id": str(recommendation.get("trace_id") or ""),
                    "correlation_id": str(recommendation.get("correlation_id") or "") or None,
                    "causation_id": None,
                    "parent_event_id": None,
                },
                scope={
                    "tenant_id": "default",
                    "service": str(service_name),
                    "environment": str(_first_non_empty(incident.get("environment"), recommendation_metadata.get("environment"), "prod") or "prod"),
                    "region": None,
                    "team": None,
                },
                state={
                    "severity": str(severity_value).lower(),
                    "status": state_status,
                    "owner": None,
                },
                policy={
                    "risk_tier": str(risk_tier_value).lower(),
                    "execution_mode": str(execution_mode_value).lower(),
                    "requires_approval": decision.get("requires_approval") if "requires_approval" in decision else orchestration.get("requires_approval"),
                    "policy_version": action.parameters.get("policy_version") or decision.get("policy_version") or orchestration.get("policy_version") or recommendation_metadata.get("policy_version"),
                    "policy_reason": action.parameters.get("policy_reason") or decision.get("policy_reason") or orchestration.get("policy_reason") or recommendation_metadata.get("policy_reason"),
                },
                transport={
                    "provider": str(transport_provider_value).lower(),
                    "channel": REMEDIATION_EVENTS,
                    "partition": None,
                    "offset": None,
                    "delivery_tag": None,
                },
                payload={
                    "source": source,
                    "source_channel": source_channel_value,
                    "source_event_contract": source_event_contract,
                    "source_payload": source_payload,
                    "approval_id": str(action.approval_id) if action.approval_id else None,
                    "action_id": str(action.id),
                    "action_type": action.action_type,
                    "status": action.status.value,
                    "output": action.output,
                    "error": action.error,
                },
            )
        )
        await session.commit()


async def startup(app: FastAPI) -> None:
    app.state.temporal_client = None
    if settings.remediation_temporal_enabled:
        from temporalio.client import Client

        app.state.temporal_client = await Client.connect(
            settings.temporal_address,
            namespace=settings.temporal_namespace,
        )
    workers = max(1, int(getattr(settings, "message_bus_worker_count", 1) or 1))
    approval_consumers: list[tuple[str, Any, ConsumeRunner]] = []
    resolution_consumers: list[tuple[str, Any, ConsumeRunner]] = []
    for worker in range(workers):
        approval_consumers.append(
            (f"rabbitmq-w{worker + 1}", RabbitMQConsumer(settings, APPROVAL_EVENTS), consume_rabbitmq_forever)
        )
        resolution_consumers.append(
            (f"rabbitmq-w{worker + 1}", RabbitMQConsumer(settings, RESOLUTION_EVENTS), consume_rabbitmq_forever)
        )
    if settings.kafka_enabled:
        for worker in range(workers):
            approval_consumers.insert(
                worker,
                (f"kafka-w{worker + 1}", KafkaConsumer(settings, APPROVAL_EVENTS), consume_kafka_forever),
            )
            resolution_consumers.insert(
                worker,
                (f"kafka-w{worker + 1}", KafkaConsumer(settings, RESOLUTION_EVENTS), consume_kafka_forever),
            )

    async def handle_approval(payload: dict) -> None:
        approval_payload = _extract_approval_payload(payload)
        approval = Approval.model_validate(approval_payload)
        approval = _enrich_approval_from_payload(approval, payload)
        # The cockpit has a distinct confirmation gate after approval. Its
        # approval event records authorization only; execution is initiated by
        # the subsequent POST /execute request.
        if approval.metadata.get("execution_confirmation_required"):
            EVENTS_PROCESSED.labels(settings.service_name, APPROVAL_EVENTS, "awaiting-confirmation").inc()
            return
        if settings.remediation_temporal_enabled:
            # The message bus must not bypass the durable control plane. Direct
            # execution is lost if this service is restarted while Jenkins is
            # running, leaving a permanently non-terminal action behind.
            await execute_approval(approval)
            EVENTS_PROCESSED.labels(settings.service_name, APPROVAL_EVENTS, "workflow-accepted").inc()
            return
        action = await _execute_approval(approval)
        await _request_failure_reconsideration(action=action, source_payload=payload)
        await _persist_remediation_event(app=app, action=action, source_payload=payload, source=APPROVAL_EVENTS)
        payload_out = _build_remediation_event_payload(action=action, source_payload=payload, source=APPROVAL_EVENTS)
        await app.state.producer.publish(REMEDIATION_EVENTS, payload_out, key=str(action.incident_id))
        EVENTS_PROCESSED.labels(settings.service_name, APPROVAL_EVENTS, "ok").inc()

    async def handle_resolution(payload: dict) -> None:
        if _resolution_requires_approval(payload):
            return
        try:
            _validate_auto_execution_policy(payload)
        except PolicyViolation as exc:
            blocked = _build_policy_blocked_action(payload, str(exc))
            if blocked is None:
                return
            await _persist_action(app, blocked)
            payload_out = _build_remediation_event_payload(
                action=blocked,
                source_payload=payload,
                source=RESOLUTION_EVENTS,
            )
            await app.state.producer.publish(REMEDIATION_EVENTS, payload_out, key=str(blocked.incident_id))
            EVENTS_PROCESSED.labels(settings.service_name, RESOLUTION_EVENTS, "policy-blocked").inc()
            return
        approval = _build_auto_approval(payload)
        if approval is None:
            return
        approval = _enrich_approval_from_payload(approval, payload)
        try:
            await _require_persisted_approved_runbook(approval)
        except PolicyViolation as exc:
            blocked = _build_policy_blocked_action(payload, str(exc))
            if blocked is None:
                return
            await _persist_action(app, blocked)
            payload_out = _build_remediation_event_payload(action=blocked, source_payload=payload, source=RESOLUTION_EVENTS)
            await app.state.producer.publish(REMEDIATION_EVENTS, payload_out, key=str(blocked.incident_id))
            EVENTS_PROCESSED.labels(settings.service_name, RESOLUTION_EVENTS, "runbook-blocked").inc()
            return
        if settings.remediation_temporal_enabled:
            await execute_approval(approval)
            EVENTS_PROCESSED.labels(settings.service_name, RESOLUTION_EVENTS, "workflow-accepted").inc()
            return
        action = await _execute_approval(approval)
        await _request_failure_reconsideration(action=action, source_payload=payload)
        await _persist_remediation_event(app=app, action=action, source_payload=payload, source=RESOLUTION_EVENTS)
        payload_out = _build_remediation_event_payload(action=action, source_payload=payload, source=RESOLUTION_EVENTS)
        await app.state.producer.publish(REMEDIATION_EVENTS, payload_out, key=str(action.incident_id))
        EVENTS_PROCESSED.labels(settings.service_name, RESOLUTION_EVENTS, "ok").inc()

    for source, approval_consumer, consume_forever in approval_consumers:
        task = asyncio.create_task(consume_forever(approval_consumer, handle_approval), name=f"remediation-engine-{source}-consumer")
        tasks.append(task)

    for source, resolution_consumer, consume_forever in resolution_consumers:
        task = asyncio.create_task(
            consume_forever(resolution_consumer, handle_resolution),
            name=f"remediation-engine-{source}-resolution-consumer",
        )
        tasks.append(task)


async def shutdown(_: FastAPI) -> None:
    for task in tasks:
        task.cancel()


app = create_app(title="KaiMS Remediation Engine", settings=settings, startup=startup, shutdown=shutdown)


async def _execute_approval(approval: Approval) -> RemediationAction:
    if approval.decision == ApprovalDecision.REJECTED:
        action = RemediationAction(
            incident_id=approval.incident_id,
            approval_id=approval.id,
            action_type="rejected",
            target=str(approval.incident_id),
            status=RemediationStatus.SKIPPED,
            output="human rejected remediation",
        )
    else:
        if _plan_is_validation_only(approval):
            raise HTTPException(
                status_code=409,
                detail="Execution blocked: the approved plan is validation-only (--dry-run true). Attach a governed live executor before executing.",
            )
        if approval.metadata.get("auto_approved"):
            try:
                await _require_persisted_approved_runbook(approval)
            except PolicyViolation as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
        else:
            await _require_persisted_human_approval(approval)
        action = engine.build_action(approval)
        _require_production_credential_reference(approval, action.action_type)
        _require_live_executor_configuration(action)
        if not engine.is_action_allowed(action.action_type):
            action.status = RemediationStatus.SKIPPED
            action.error = f"Action type '{action.action_type}' is not allowlisted"
            action.output = "remediation blocked by allowlist policy"
        else:
            action.idempotency_key = _build_action_idempotency_key(approval, action.action_type)
            bind_execution_contract(action, approval)
            verify_execution_contract(action)
            action.parameters["lifecycle"] = {
                "state": RemediationStatus.DISPATCHING.value,
                "history": [
                    RemediationStatus.POLICY_CHECKED.value,
                    RemediationStatus.APPROVED.value,
                    RemediationStatus.DISPATCHING.value,
                ],
            }
            lock = idempotency_locks.setdefault(action.idempotency_key, asyncio.Lock())
            async with lock:
                existing = await _find_existing_action(app, action.idempotency_key)
                if existing is not None:
                    execution_result = existing.parameters.get("execution_result")
                    execution_result = execution_result if isinstance(execution_result, dict) else {}
                    retryable_connector_skip = (
                        existing.status == RemediationStatus.SKIPPED
                        and not bool(execution_result.get("executed"))
                        and "executor is configured" in str(existing.error or "").lower()
                    )
                    existing_execution = existing.parameters.get("execution_result")
                    existing_execution = existing_execution if isinstance(existing_execution, dict) else {}
                    retryable_legacy_queue_ack = (
                        existing.status == RemediationStatus.SUCCEEDED
                        and str(existing_execution.get("executor") or "").lower() == "jenkins"
                        and not existing_execution.get("build_result")
                    )
                    corrected_failed_plan = (
                        existing.status == RemediationStatus.FAILED
                        and _execution_plan_fingerprint(existing) != _execution_plan_fingerprint(action)
                    )
                    retryable_indeterminate_jenkins = (
                        existing.status == RemediationStatus.FAILED
                        and str(existing_execution.get("executor") or "").lower() == "jenkins"
                        and str(existing_execution.get("build_result") or "").upper() in {"", "UNKNOWN"}
                    )
                    orchestration = existing.parameters.get("orchestration")
                    orchestration = orchestration if isinstance(orchestration, dict) else {}
                    claimable_temporal_intent = (
                        existing.status in {RemediationStatus.PENDING, RemediationStatus.RUNNING}
                        and str(orchestration.get("provider") or "").lower() == "temporal"
                        and str(orchestration.get("status") or "").lower() in {"submitting", "accepted", "workflow_accepted"}
                        and not existing_execution
                    )
                    if (
                        retryable_connector_skip
                        or retryable_legacy_queue_ack
                        or corrected_failed_plan
                        or retryable_indeterminate_jenkins
                        or claimable_temporal_intent
                    ):
                        # Preserve the durable row/idempotency identity while
                        # replacing the historical configuration skip with the
                        # newly configured Jenkins attempt.
                        action.id = existing.id
                        bind_execution_contract(action, approval)
                        verify_execution_contract(action)
                        action.parameters["orchestration"] = {
                            **orchestration,
                            "status": "executing",
                        }
                        action = await engine.execute(action)
                        await _persist_action(app, action)
                        return action
                    # A redelivered or concurrent approval/API request reaches
                    # this branch with the same deterministic key. Return the
                    # durable result instead of invoking Jenkins twice.
                    return existing
                action = await engine.execute(action)
                await _persist_action(app, action)
                return action

    await _persist_action(app, action)
    return action


async def _finalize_api_execution(approval: Approval, action: RemediationAction) -> RemediationAction:
    # The action row is the UI's authoritative execution state. Persist the
    # observed terminal result before publishing its event; otherwise an API
    # caller sees the terminal response while subsequent reads remain stuck on
    # the last non-terminal value.
    await _persist_action(app, action)
    source_payload = {"approval": approval.model_dump(mode="json")}
    await _request_failure_reconsideration(action=action, source_payload=source_payload)
    await _persist_remediation_event(
        app=app,
        action=action,
        source_payload=source_payload,
        source="api-execute",
    )
    payload_out = _build_remediation_event_payload(
        action=action,
        source_payload=source_payload,
        source="api-execute",
    )
    await app.state.producer.publish(REMEDIATION_EVENTS, payload_out, key=str(action.incident_id))
    EVENTS_PROCESSED.labels(settings.service_name, "api-execute", "ok").inc()
    return action


@app.post("/execute-direct", response_model=RemediationAction, include_in_schema=False)
async def execute_approval_direct(approval: Approval, x_kaiops_internal_token: str = Header(default="")) -> RemediationAction:
    """Temporal activity target. Idempotency makes activity retries safe."""
    expected = settings.remediation_internal_token
    if not expected or x_kaiops_internal_token != expected:
        raise HTTPException(status_code=403, detail="Internal remediation activity authentication failed.")
    return await _finalize_api_execution(approval, await _execute_approval(approval))


@app.post("/dispatch-direct", response_model=RemediationAction, include_in_schema=False)
async def dispatch_approval_direct(approval: Approval, x_kaiops_internal_token: str = Header(default="")) -> RemediationAction:
    """Temporal-only, idempotent handoff to an asynchronous executor."""
    expected = settings.remediation_internal_token
    if not expected or x_kaiops_internal_token != expected:
        raise HTTPException(status_code=403, detail="Internal remediation activity authentication failed.")
    if _plan_is_validation_only(approval):
        raise HTTPException(status_code=409, detail="Execution blocked: the approved plan is validation-only.")
    if approval.metadata.get("auto_approved"):
        try:
            await _require_persisted_approved_runbook(approval)
        except PolicyViolation as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    else:
        await _require_persisted_human_approval(approval)
    action = engine.build_action(approval)
    _require_production_credential_reference(approval, action.action_type)
    _require_live_executor_configuration(action)
    action.idempotency_key = _build_action_idempotency_key(approval, action.action_type)
    existing = await _find_existing_action(app, action.idempotency_key)
    if existing is not None:
        existing_result = existing.parameters.get("execution_result")
        if isinstance(existing_result, dict) and existing_result.get("accepted"):
            return existing
        action.id = existing.id
    bind_execution_contract(action, approval)
    verify_execution_contract(action)
    action.status = RemediationStatus.DISPATCHING
    action.parameters["lifecycle"] = {
        "state": RemediationStatus.DISPATCHING.value,
        "history": [RemediationStatus.POLICY_CHECKED.value, RemediationStatus.APPROVED.value, RemediationStatus.DISPATCHING.value],
    }
    await _persist_action(app, action)
    action = await engine.dispatch(action)
    lifecycle = action.parameters.get("lifecycle") if isinstance(action.parameters.get("lifecycle"), dict) else {"history": []}
    lifecycle["state"] = action.status.value
    lifecycle["history"] = [*lifecycle.get("history", []), action.status.value]
    action.parameters["lifecycle"] = lifecycle
    await _persist_action(app, action)
    return action


@app.post("/reconcile-direct", response_model=RemediationAction, include_in_schema=False)
async def reconcile_execution_direct(payload: dict[str, Any], x_kaiops_internal_token: str = Header(default="")) -> RemediationAction:
    """Perform one executor observation and persist only observed truth."""
    expected = settings.remediation_internal_token
    if not expected or x_kaiops_internal_token != expected:
        raise HTTPException(status_code=403, detail="Internal remediation activity authentication failed.")
    approval = Approval.model_validate(payload.get("approval") or {})
    async with app.state.session_factory() as session:
        action = await IncidentRepository(session).find_latest_action_by_incident(approval.incident_id)
    if action is None:
        raise HTTPException(status_code=404, detail="No dispatched remediation action exists for this incident.")
    verify_execution_contract(action)
    previous = action.status.value
    action = await engine.observe(action)
    lifecycle = action.parameters.get("lifecycle") if isinstance(action.parameters.get("lifecycle"), dict) else {"history": []}
    lifecycle["state"] = action.status.value
    if previous != action.status.value:
        lifecycle["history"] = [*lifecycle.get("history", []), action.status.value]
    action.parameters["lifecycle"] = lifecycle
    terminal = {
        RemediationStatus.SUCCEEDED,
        RemediationStatus.EXECUTION_FAILED,
        RemediationStatus.VALIDATION_FAILED,
        RemediationStatus.DISPATCH_FAILED,
        RemediationStatus.POLICY_BLOCKED,
        RemediationStatus.CANCELLED,
        RemediationStatus.TIMED_OUT,
    }
    if action.status in terminal:
        return await _finalize_api_execution(approval, action)
    await _persist_action(app, action)
    return action


@app.post("/timeout-direct", response_model=RemediationAction, include_in_schema=False)
async def timeout_execution_direct(payload: dict[str, Any], x_kaiops_internal_token: str = Header(default="")) -> RemediationAction:
    expected = settings.remediation_internal_token
    if not expected or x_kaiops_internal_token != expected:
        raise HTTPException(status_code=403, detail="Internal remediation activity authentication failed.")
    approval = Approval.model_validate(payload.get("approval") or {})
    async with app.state.session_factory() as session:
        action = await IncidentRepository(session).find_latest_action_by_incident(approval.incident_id)
    if action is None:
        raise HTTPException(status_code=404, detail="No remediation action exists for this incident.")
    action.status = RemediationStatus.TIMED_OUT
    action.error = str(payload.get("error") or "Executor did not reach a terminal state before the remediation deadline.")
    action.completed_at = utc_now()
    lifecycle = action.parameters.get("lifecycle") if isinstance(action.parameters.get("lifecycle"), dict) else {"history": []}
    lifecycle["state"] = RemediationStatus.TIMED_OUT.value
    lifecycle["history"] = [*lifecycle.get("history", []), RemediationStatus.TIMED_OUT.value]
    action.parameters["lifecycle"] = lifecycle
    return await _finalize_api_execution(approval, action)


@app.post("/execution-failed", response_model=RemediationAction, include_in_schema=False)
async def record_execution_failure(payload: dict[str, Any], x_kaiops_internal_token: str = Header(default="")) -> RemediationAction:
    """Persist a truthful terminal result when the durable executor rejects an activity."""
    expected = settings.remediation_internal_token
    if not expected or x_kaiops_internal_token != expected:
        raise HTTPException(status_code=403, detail="Internal remediation activity authentication failed.")
    approval = Approval.model_validate(payload.get("approval") or {})
    async with app.state.session_factory() as session:
        existing = await IncidentRepository(session).find_latest_action_by_incident(approval.incident_id)
    if existing is None:
        preview = engine.build_action(approval)
        preview.idempotency_key = _build_action_idempotency_key(approval, preview.action_type)
        existing = await _find_existing_action(app, preview.idempotency_key)
        action = existing or preview
    else:
        action = existing
    action.status = RemediationStatus.FAILED
    action.error = str(payload.get("error") or "Durable remediation execution failed.").strip()
    action.completed_at = utc_now()
    orchestration = action.parameters.get("orchestration")
    orchestration = orchestration if isinstance(orchestration, dict) else {}
    action.parameters["orchestration"] = {
        **orchestration,
        "status": "failed",
        "http_status": payload.get("http_status"),
    }
    await _persist_action(app, action)
    return action


@app.post("/execute", response_model=RemediationAction, status_code=202)
async def execute_approval(approval: Approval) -> RemediationAction:
    if not settings.remediation_temporal_enabled:
        return await _finalize_api_execution(approval, await _execute_approval(approval))

    client = getattr(app.state, "temporal_client", None)
    if client is None:
        raise HTTPException(status_code=503, detail="Durable remediation orchestration is unavailable.")
    action_preview = engine.build_action(approval)
    # Reject invalid/self-destructive targets before creating a durable
    # workflow or submitting anything to the external executor.
    _require_live_executor_configuration(action_preview)
    readiness = await _execution_plane_readiness(action_preview)
    if not readiness["ready"]:
        raise HTTPException(status_code=503, detail=readiness["reason"])
    workflow_key = _build_action_idempotency_key(approval, action_preview.action_type)
    workflow_id = f"kaiops-remediation-{workflow_key}"
    existing = await _find_existing_action(app, workflow_key)
    if existing is not None and existing.status in {
        RemediationStatus.SUCCEEDED,
        RemediationStatus.SKIPPED,
    }:
        return existing
    if existing is not None:
        action_preview.id = existing.id
    action_preview.idempotency_key = workflow_key
    action_preview.status = RemediationStatus.PENDING
    bind_execution_contract(action_preview, approval)
    verify_execution_contract(action_preview)
    action_preview.parameters["lifecycle"] = {
        "state": RemediationStatus.DISPATCHING.value,
        "history": [
            RemediationStatus.POLICY_CHECKED.value,
            RemediationStatus.APPROVED.value,
            RemediationStatus.DISPATCHING.value,
        ],
    }
    action_preview.parameters["orchestration"] = {
        "provider": "temporal",
        "workflow_id": workflow_id,
        "status": "submitting",
        "executor_readiness": readiness,
    }
    # Persist intent before contacting Temporal. If the process exits between
    # submission and acknowledgement, the deterministic workflow/idempotency
    # IDs make reconciliation safe instead of losing the operator action.
    await _persist_action(app, action_preview)
    # Workflow execution failures live in temporalio.exceptions. Importing this
    # from temporalio.client works in neither the pinned SDK nor current SDKs
    # and caused every durable execution request to fail before workflow start.
    from temporalio.exceptions import WorkflowAlreadyStartedError
    from temporalio.common import WorkflowIDReusePolicy

    try:
        handle = await client.start_workflow(
            "KaiOpsRemediationWorkflow",
            approval.model_dump(mode="json"),
            id=workflow_id,
            task_queue=settings.remediation_temporal_task_queue,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
        )
    except WorkflowAlreadyStartedError:
        handle = client.get_workflow_handle(workflow_id)
    except Exception as exc:
        action_preview.error = f"Temporal workflow submission failed: {type(exc).__name__}"
        action_preview.parameters["orchestration"]["status"] = "submission_failed"
        await _persist_action(app, action_preview)
        raise HTTPException(status_code=503, detail=action_preview.error) from exc
    # The target may be the API gateway carrying this request. A durable
    # workflow must therefore be acknowledged before remediation can restart
    # that gateway; completion is delivered through the persisted action/event
    # stream consumed by the UI.
    # Temporal acceptance proves durable orchestration only. It does not prove
    # that Jenkins (or another adapter) accepted or started the mutation.
    action_preview.status = RemediationStatus.DISPATCHING
    action_preview.started_at = utc_now()
    action_preview.parameters["orchestration"] = {
        "provider": "temporal",
        "workflow_id": workflow_id,
        "status": "workflow_accepted",
        "executor_readiness": readiness,
    }
    await _persist_action(app, action_preview)
    return action_preview


@app.get("/actions/by-incident/{incident_id}/latest", response_model=RemediationAction)
async def latest_action_for_incident(incident_id: UUID) -> RemediationAction:
    session_factory = getattr(app.state, "session_factory", None)
    if session_factory is None:
        raise HTTPException(status_code=503, detail="Remediation persistence is unavailable.")
    async with session_factory() as session:
        action = await IncidentRepository(session).find_latest_action_by_incident(incident_id)
    if action is None:
        raise HTTPException(status_code=404, detail="No remediation action exists for this incident.")
    return action


async def _execution_plane_readiness(action: RemediationAction) -> dict[str, Any]:
    profile = action.parameters.get("connection_profile")
    profile = profile if isinstance(profile, dict) else {}
    executor = str(profile.get("executor_type") or profile.get("connection_type") or action.action_type).strip().lower()
    if executor != "jenkins":
        return {"ready": True, "executor": executor or "native", "reason": "executor configuration accepted"}
    endpoint = str(profile.get("endpoint_url") or "").rstrip("/")
    if not endpoint:
        return {"ready": False, "executor": "jenkins", "reason": "Jenkins endpoint is not configured."}
    username = os.getenv("JENKINS_USERNAME", "").strip()
    token = os.getenv("JENKINS_API_TOKEN", "").strip()
    if not username or not token:
        return {"ready": False, "executor": "jenkins", "reason": "Jenkins runtime credentials are not available."}
    try:
        async with httpx.AsyncClient(auth=(username, token), timeout=httpx.Timeout(6.0, connect=3.0)) as client:
            response = await client.get(f"{endpoint}/api/json")
            response.raise_for_status()
    except Exception as exc:
        return {
            "ready": False,
            "executor": "jenkins",
            "endpoint": endpoint,
            "reason": f"Jenkins execution plane is unavailable ({type(exc).__name__}).",
        }
    return {"ready": True, "executor": "jenkins", "endpoint": endpoint, "reason": "Jenkins API is reachable"}


@app.get("/executors/readiness")
async def execution_plane_readiness() -> dict[str, Any]:
    profile = {
        "executor_type": os.getenv("REMEDIATION_DEFAULT_EXECUTOR", "jenkins"),
        "endpoint_url": os.getenv("REMEDIATION_JENKINS_URL", "http://jenkins:8080"),
    }
    probe = RemediationAction(
        incident_id=UUID("00000000-0000-4000-8000-000000000001"),
        action_type=str(profile["executor_type"]),
        target="readiness-probe",
        parameters={"connection_profile": profile},
    )
    result = await _execution_plane_readiness(probe)
    result["temporal_connected"] = getattr(app.state, "temporal_client", None) is not None
    result["ready"] = bool(result["ready"] and result["temporal_connected"])
    if not result["ready"]:
        raise HTTPException(status_code=503, detail=result)
    return result


@app.get("/executions/{incident_id}/workflow")
async def remediation_workflow_status(incident_id: str, recommendation_id: str, action_type: str = "rollback_deployment") -> dict[str, Any]:
    client = getattr(app.state, "temporal_client", None)
    if not settings.remediation_temporal_enabled or client is None:
        raise HTTPException(status_code=503, detail="Durable remediation orchestration is unavailable.")
    approval = Approval(incident_id=UUID(incident_id), recommendation_id=UUID(recommendation_id))
    workflow_key = _build_action_idempotency_key(approval, action_type)
    return await client.get_workflow_handle(f"kaiops-remediation-{workflow_key}").query("status")


@app.post("/workflow-preflight")
async def remediation_workflow_preflight(approval: Approval) -> dict[str, Any]:
    client = getattr(app.state, "temporal_client", None)
    if not settings.remediation_temporal_enabled or client is None:
        raise HTTPException(status_code=503, detail="Durable remediation orchestration is unavailable.")
    workflow_key = _build_action_idempotency_key(approval, engine.build_action(approval).action_type)
    return await client.execute_workflow(
        "KaiOpsRemediationPreflightWorkflow",
        approval.model_dump(mode="json"),
        id=f"kaiops-remediation-preflight-{workflow_key}-{int(asyncio.get_running_loop().time() * 1000)}",
        task_queue=settings.remediation_temporal_task_queue,
    )


async def _require_persisted_human_approval(approval: Approval) -> None:
    """Prevent callers from turning an unpersisted request body into approval."""
    session_factory = getattr(app.state, "session_factory", None)
    if not settings.database_enabled or session_factory is None:
        raise HTTPException(status_code=503, detail="Durable approval verification is unavailable.")
    async with session_factory() as session:
        accepted = await IncidentRepository(session).has_accepted_approval_id(
            approval.id,
            approval.incident_id,
            approval.recommendation_id,
            tenant_id=approval.tenant_id or "default",
        )
    if not accepted:
        raise HTTPException(
            status_code=409,
            detail="Execution blocked: the exact approval ID is not a persisted accepted decision for this recommendation.",
        )


async def _require_persisted_approved_runbook(approval: Approval) -> None:
    if not settings.database_enabled:
        raise PolicyViolation("automatic execution requires durable runbook governance")
    runbook_id = str(approval.metadata.get("runbook_id") or "").strip()
    if not runbook_id and approval.metadata.get("confidence_gate_passed"):
        return
    version = int(approval.metadata.get("runbook_version") or 1)
    async with app.state.session_factory() as session:
        governance = await IncidentRepository(session).get_runbook_governance(
            runbook_id, version, tenant_id=approval.tenant_id or "default"
        )
    if not governance or governance.get("status") != "approved":
        raise PolicyViolation("automatic execution blocked: runbook version is not durably approved or is suspended")


@app.post("/dry-run")
async def dry_run_approval(approval: Approval) -> dict[str, Any]:
    """Build and policy-check an action without invoking its execution plugin."""
    action = engine.build_action(approval)
    _require_production_credential_reference(approval, action.action_type)
    allowed = engine.is_action_allowed(action.action_type)
    unsafe_reasons = _unsafe_plan_reasons(approval)
    connector_check = await _preflight_live_connector(action)
    passed = allowed and not unsafe_reasons and connector_check["passed"]
    return {
        "status": "passed" if passed else "blocked",
        "dry_run": True,
        "executed": False,
        "incident_id": str(approval.incident_id),
        "recommendation_id": str(approval.recommendation_id),
        "action_type": action.action_type,
        "target": action.target,
        "checks": {
            "action_allowlisted": allowed,
            "plan_safe": not unsafe_reasons,
            "unsafe_reasons": unsafe_reasons,
            "approval_decision": str(approval.decision.value),
            "idempotency_key": _build_action_idempotency_key(approval, action.action_type),
            "connector": connector_check,
        },
        "message": "Dry run passed; no command was executed." if passed else (
            unsafe_reasons[0] if unsafe_reasons else connector_check.get("message") or f"Action type '{action.action_type}' is not allowlisted."
        ),
    }


async def _preflight_live_connector(action: RemediationAction) -> dict[str, Any]:
    profile = action.parameters.get("connection_profile")
    profile = profile if isinstance(profile, dict) else {}
    executor = str(profile.get("executor_type") or profile.get("connection_type") or "").strip().lower()
    if executor == "azure_container_apps_job":
        required = {
            "subscription_id": profile.get("subscription_id") or os.getenv("AZURE_SUBSCRIPTION_ID"),
            "resource_group": profile.get("resource_group") or os.getenv("AZURE_RESOURCE_GROUP"),
            "job_name": profile.get("job_name") or os.getenv("REMEDIATION_ACA_JOB_NAME"),
            "managed_identity": os.getenv("IDENTITY_ENDPOINT") and os.getenv("IDENTITY_HEADER"),
        }
        missing = [name for name, value in required.items() if not str(value or "").strip()]
        return {
            "passed": not missing,
            "executor": executor,
            "job_name": str(required["job_name"] or ""),
            "message": "Azure Container Apps Job configuration is ready." if not missing else f"Azure job preflight failed: configure {', '.join(missing)}.",
        }
    if executor != "jenkins":
        return {"passed": True, "executor": executor or "local", "message": "No Jenkins connector selected."}

    endpoint = str(profile.get("endpoint_url") or profile.get("endpoint") or "").strip().rstrip("/")
    job_name = str(profile.get("job_name") or "").strip("/")
    username = os.getenv("JENKINS_USERNAME", "").strip()
    token = os.getenv("JENKINS_API_TOKEN", "").strip()
    if not endpoint or not job_name or not username or not token:
        return {
            "passed": False,
            "executor": "jenkins",
            "message": "Jenkins preflight failed: endpoint, job, or runtime credentials are unavailable.",
        }
    job_path = "/job/" + "/job/".join(part for part in job_name.split("/") if part)
    try:
        # Jenkins can take longer than eight seconds to answer its first API
        # request after plugin activity or JVM pressure. Keep connection
        # failure detection tight, but allow a bounded read window so a healthy
        # and authenticated controller is not reported as a failed dry run.
        async with httpx.AsyncClient(auth=(username, token), timeout=httpx.Timeout(25.0, connect=5.0)) as client:
            response = await client.get(f"{endpoint}{job_path}/api/json?tree=name,buildable,inQueue")
            response.raise_for_status()
            payload = response.json()
        buildable = bool(payload.get("buildable", True))
        return {
            "passed": buildable,
            "executor": "jenkins",
            "job_name": job_name,
            "buildable": buildable,
            "in_queue": bool(payload.get("inQueue")),
            "message": "Jenkins job is reachable and buildable." if buildable else "Jenkins preflight failed: the configured job is disabled.",
        }
    except (httpx.HTTPError, ValueError) as exc:
        return {
            "passed": False,
            "executor": "jenkins",
            "job_name": job_name,
            "message": f"Jenkins preflight failed: {type(exc).__name__}.",
        }


def _unsafe_plan_reasons(approval: Approval) -> list[str]:
    """Fail closed when an edited plan contains destructive shell/database actions."""
    plan = approval.metadata.get("execution_plan") if isinstance(approval.metadata.get("execution_plan"), dict) else {}
    values = [approval.modified_action or ""]
    for key in ("commands", "scripts", "queries"):
        item = plan.get(key, [])
        values.extend(str(value) for value in (item if isinstance(item, list) else [item]))
    text = "\n".join(values).lower()
    markers = {
        "recursive filesystem deletion": ("rm -rf", "remove-item -recurse", "rmdir /s"),
        "database destruction": ("drop database", "drop table", "truncate table"),
        "infrastructure destruction": ("terraform destroy", "kubectl delete namespace"),
    }
    return [f"Dry run blocked: {label} requires a separately reviewed, policy-authorized plan." for label, tokens in markers.items() if any(token in text for token in tokens)]


def _plan_is_validation_only(approval: Approval) -> bool:
    """Return true when every executable entry explicitly requests dry-run mode."""
    plan = approval.metadata.get("execution_plan") if isinstance(approval.metadata.get("execution_plan"), dict) else {}
    executable: list[str] = []
    for key in ("commands", "scripts"):
        item = plan.get(key, [])
        executable.extend(str(value).strip() for value in (item if isinstance(item, list) else [item]) if str(value).strip())
    if not executable:
        return False
    return all(re.search(r"--dry-run(?:=|\s+)(?:true|1)\b", value, flags=re.IGNORECASE) for value in executable)


def _require_production_credential_reference(approval: Approval, action_type: str) -> None:
    profile = approval.metadata.get("connection_profile") if isinstance(approval.metadata.get("connection_profile"), dict) else {}
    environment = str(profile.get("environment") or approval.metadata.get("environment") or "").strip().lower()
    if environment not in {"prod", "production"}:
        return
    if str(action_type or "").strip().lower() in {"status", "query", "inspect", "noop"}:
        return
    executor_type = str(profile.get("executor_type") or profile.get("connection_type") or "").strip().lower()
    if executor_type == "azure_container_apps_job" and str(profile.get("identity_type") or "managed_identity").lower() == "managed_identity":
        return
    credential_ref = str(profile.get("credential_ref") or "").strip()
    valid_prefix = credential_ref.startswith(("vault://", "arn:aws:secretsmanager:", "gcp-secret://", "k8s-secret://")) or (
        credential_ref.startswith("https://") and ".vault.azure.net/secrets/" in credential_ref
    )
    if not valid_prefix:
        raise HTTPException(
            status_code=422,
            detail="Production remediation requires a valid enterprise secret-manager reference; secret values are not accepted.",
        )


def _require_live_executor_configuration(action: RemediationAction) -> None:
    """Reject non-executable approvals before they emit a failed closure event."""
    profile = action.parameters.get("connection_profile")
    profile = profile if isinstance(profile, dict) else {}
    executor_type = str(profile.get("executor_type") or profile.get("connection_type") or "").strip().lower()
    normalized_target = str(action.target or "").strip().lower().removeprefix("kaiops-")
    if (
        normalized_target == "remediation-engine"
        and executor_type == "jenkins"
        and not settings.remediation_temporal_enabled
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Execution blocked: remediation-engine cannot synchronously restart itself through Jenkins. "
                "Use an external remediation control-plane worker with durable Jenkins reconciliation."
            ),
        )
    try:
        UUID(str(action.target))
    except (TypeError, ValueError, AttributeError):
        target_is_incident_uuid = False
    else:
        target_is_incident_uuid = True
    if target_is_incident_uuid and executor_type in {"jenkins", "azure_container_apps_job"}:
        raise HTTPException(
            status_code=409,
            detail=(
                "Execution blocked: the live remediation target is an incident UUID. "
                "Attach the approved service/resource target and execution plan before executing."
            ),
        )
    if action.action_type == "script_execution" and executor_type not in {"jenkins", "azure_container_apps_job"}:
        return
    if executor_type == "azure_container_apps_job":
        required = {
            "subscription_id": profile.get("subscription_id") or os.getenv("AZURE_SUBSCRIPTION_ID"),
            "resource_group": profile.get("resource_group") or os.getenv("AZURE_RESOURCE_GROUP"),
            "job_name": profile.get("job_name") or os.getenv("REMEDIATION_ACA_JOB_NAME"),
        }
        missing = [name for name, value in required.items() if not str(value or "").strip()]
        if not missing:
            return
        raise HTTPException(status_code=409, detail=f"Execution blocked: Azure Container Apps Job connector requires {', '.join(missing)}.")
    if executor_type == "jenkins" or action.action_type == "rollback_deployment":
        required = {
            "endpoint_url": profile.get("endpoint_url") or profile.get("endpoint"),
            "job_name": profile.get("job_name"),
            "credential_ref": profile.get("credential_ref") or profile.get("secret_ref"),
        }
        missing = [name for name, value in required.items() if not str(value or "").strip()]
        if not missing:
            return
        raise HTTPException(
            status_code=409,
            detail=(
                "Execution blocked: the Jenkins connector is incomplete. "
                f"Configure {', '.join(missing)} before approving live remediation."
            ),
        )

    raise HTTPException(
        status_code=409,
        detail=(
            f"Execution blocked: no live executor is implemented for action type '{action.action_type}'. "
            "Select a governed Jenkins connector or an approved local script execution plan."
        ),
    )


def _build_action_idempotency_key(approval: Approval, action_type: str) -> str:
    raw = f"{approval.incident_id}:{approval.recommendation_id}:{action_type}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _find_existing_action(app: FastAPI, idempotency_key: str | None) -> RemediationAction | None:
    if not settings.database_enabled or not idempotency_key:
        return None
    async with app.state.session_factory() as session:
        repo = IncidentRepository(session)
        return await repo.find_action_by_idempotency_key(idempotency_key)


async def _persist_action(app: FastAPI, action: RemediationAction) -> None:
    if not settings.database_enabled:
        return
    async with app.state.session_factory() as session:
        repo = IncidentRepository(session)
        await repo.save_action(action)
        await repo.save_action_audit(action)
        await session.commit()


def _rca_and_resolution_confidence(payload: dict[str, Any]) -> tuple[float | None, float | None]:
    recommendation = payload.get("recommendation", {}) if isinstance(payload.get("recommendation"), dict) else {}
    metadata = recommendation.get("metadata", {}) if isinstance(recommendation.get("metadata"), dict) else {}
    rca_analysis = metadata.get("rca_analysis", {}) if isinstance(metadata.get("rca_analysis"), dict) else {}
    context = payload.get("context", {}) if isinstance(payload.get("context"), dict) else {}
    context_metadata = context.get("metadata", {}) if isinstance(context.get("metadata"), dict) else {}
    try:
        rca_confidence = float(
            context.get("confidence")
            or context.get("confidence_score")
            or context_metadata.get("confidence")
            or context_metadata.get("confidence_score")
            or rca_analysis.get("confidence_score")
        )
    except (TypeError, ValueError):
        rca_confidence = None
    try:
        resolution_confidence = float(recommendation.get("confidence"))
    except (TypeError, ValueError):
        resolution_confidence = None
    return rca_confidence, resolution_confidence


def _resolution_requires_approval(payload: dict[str, Any]) -> bool:
    # Arch's auto-completion rule: when both the RCA confidence and the
    # resolution confidence meet the configured threshold, the alert flow
    # continues without manual approval, regardless of the severity-based
    # decision below. Below threshold on either value (or either is missing),
    # the existing approval flow is unchanged.
    rca_confidence, resolution_confidence = _rca_and_resolution_confidence(payload)
    if rca_confidence is not None and resolution_confidence is not None:
        threshold = settings.rca_resolution_auto_complete_threshold
        if rca_confidence >= threshold and resolution_confidence >= threshold:
            return False

    decision = payload.get("decision", {}) if isinstance(payload.get("decision"), dict) else {}
    if "requires_approval" in decision:
        return bool(decision.get("requires_approval"))

    recommendation = payload.get("recommendation", {}) if isinstance(payload.get("recommendation"), dict) else {}
    metadata = recommendation.get("metadata", {}) if isinstance(recommendation.get("metadata"), dict) else {}
    orchestration = metadata.get("orchestration_decision", {}) if isinstance(metadata.get("orchestration_decision"), dict) else {}
    if "requires_approval" in orchestration:
        return bool(orchestration.get("requires_approval"))

    return True


def _build_auto_approval(payload: dict[str, Any]) -> Approval | None:
    recommendation = payload.get("recommendation", {}) if isinstance(payload.get("recommendation"), dict) else {}
    incident_id = recommendation.get("incident_id")
    recommendation_id = recommendation.get("id")
    if incident_id is None or recommendation_id is None:
        return None

    decision = payload.get("decision", {}) if isinstance(payload.get("decision"), dict) else {}
    incident = payload.get("incident", {}) if isinstance(payload.get("incident"), dict) else {}
    recommendation_metadata = recommendation.get("metadata", {}) if isinstance(recommendation.get("metadata"), dict) else {}

    policy_version = str(
        decision.get("policy_version") or recommendation_metadata.get("policy_version") or ""
    ).strip()
    policy_reason = str(
        decision.get("policy_reason") or recommendation_metadata.get("policy_reason") or ""
    ).strip()

    context_confidence, resolution_confidence = _rca_and_resolution_confidence(payload)
    metadata: dict[str, Any] = {
        "auto_approved": True,
        "approval_source": "resolution-events",
        "confidence_gate_passed": True,
        "context_confidence": context_confidence,
        "resolution_confidence": resolution_confidence,
        "auto_execute_threshold": settings.rca_resolution_auto_complete_threshold,
    }
    if policy_version:
        metadata["policy_version"] = policy_version
    if policy_reason:
        metadata["policy_reason"] = policy_reason
    service = _first_non_empty(incident.get("service"), recommendation_metadata.get("service"))
    environment = _first_non_empty(incident.get("environment"), recommendation_metadata.get("environment"))
    remediation_target = _first_non_empty(
        recommendation_metadata.get("remediation_target"),
        recommendation.get("target"),
        recommendation.get("resource"),
        incident.get("deployment"),
        service,
    )
    if service:
        metadata["service"] = service
        metadata["incident_service"] = service
    if environment:
        metadata["environment"] = environment
    supplied_profile = recommendation_metadata.get("connection_profile")
    supplied_profile = supplied_profile if isinstance(supplied_profile, dict) else {}
    default_profile = {
        "application": str(incident.get("application") or recommendation_metadata.get("application") or service or "unknown"),
        "service": str(service or "unknown"),
        "environment": str(environment or "local"),
        "namespace": str(environment or "default"),
        "endpoint_url": "http://jenkins:8080",
        "connection_type": "jenkins",
        "executor_type": "jenkins",
        "job_name": "kaiops-auto-remediation",
        "timeout_seconds": 1200,
        "credential_ref": f"vault://kaiops/{str(environment or 'local').lower()}/jenkins#api-token",
    }
    metadata["connection_profile"] = {
        **default_profile,
        **{key: value for key, value in supplied_profile.items() if value is not None and str(value).strip()},
    }
    if remediation_target:
        metadata["remediation_target"] = remediation_target
        metadata["target"] = remediation_target
    recommended_action = _first_non_empty(recommendation.get("recommended_action"), recommendation.get("action"))
    recommended_commands = recommendation.get("commands") if isinstance(recommendation.get("commands"), list) else []
    if recommended_action:
        metadata["recommended_action"] = recommended_action
    if recommended_commands:
        metadata["recommended_commands"] = [str(item).strip() for item in recommended_commands if str(item).strip()]
    for key in ("runbook_id", "runbook_version", "runbook_status", "runbook_match_score"):
        if recommendation_metadata.get(key) is not None:
            metadata[key] = recommendation_metadata[key]

    return Approval(
        incident_id=incident_id,
        recommendation_id=recommendation_id,
        decision=ApprovalDecision.APPROVED,
        approver="system-auto-approval",
        channel="web",
        comment=str(recommendation.get("recommended_action") or "auto-approved remediation"),
        metadata=metadata,
    )


async def _request_failure_reconsideration(
    *, action: RemediationAction, source_payload: dict[str, Any]
) -> None:
    """Ask resolution intelligence for a fresh, approval-gated plan after execution failure."""
    if action.status != RemediationStatus.FAILED:
        return
    previous = source_payload.get("recommendation", {}) if isinstance(source_payload.get("recommendation"), dict) else {}
    if not previous and isinstance(source_payload.get("approval"), dict):
        approval_metadata = source_payload["approval"].get("metadata", {})
        approval_metadata = approval_metadata if isinstance(approval_metadata, dict) else {}
        previous = {
            "id": source_payload["approval"].get("recommendation_id"),
            "recommended_action": approval_metadata.get("recommended_action"),
            "commands": approval_metadata.get("recommended_commands", []),
            "severity": approval_metadata.get("severity", "warning"),
            "metadata": approval_metadata,
        }
    previous_metadata = previous.get("metadata", {}) if isinstance(previous.get("metadata"), dict) else {}
    attempt = int(previous_metadata.get("execution_reconsideration_attempt") or 0) + 1
    maximum = max(0, int(os.getenv("REMEDIATION_FAILURE_RECONSIDERATION_LIMIT", "2")))
    if attempt > maximum:
        action.metadata["failure_reconsideration"] = {"status": "limit_reached", "attempt": attempt - 1, "limit": maximum}
        await _persist_action(app, action)
        return
    request = {
        "incident_id": str(action.incident_id),
        "action_id": str(action.id),
        "action_type": action.action_type,
        "target": action.target,
        "service": str(action.parameters.get("service") or action.target),
        "environment": str(action.parameters.get("environment") or "prod"),
        "error": str(action.error or action.output or "execution failed"),
        "execution_result": action.parameters.get("execution_result", {}),
        "previous_recommendation": previous,
        "attempt": attempt,
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(f"{settings.resolution_agent_url.rstrip('/')}/reconsider-execution", json=request)
            response.raise_for_status()
            revised_payload = response.json()
        await app.state.producer.publish(RESOLUTION_EVENTS, revised_payload, key=str(action.incident_id))
        action.metadata["failure_reconsideration"] = {"status": "awaiting_approval", "attempt": attempt, "limit": maximum}
    except Exception as exc:
        action.metadata["failure_reconsideration"] = {"status": "request_failed", "attempt": attempt, "error": str(exc)}
    await _persist_action(app, action)


def _enrich_approval_from_payload(approval: Approval, payload: dict[str, Any]) -> Approval:
    recommendation, _, incident, _ = _extract_resolution_context(payload)
    recommendation_metadata = recommendation.get("metadata", {}) if isinstance(recommendation.get("metadata"), dict) else {}

    service = _first_non_empty(approval.metadata.get("service"), incident.get("service"), recommendation_metadata.get("service"))
    environment = _first_non_empty(
        approval.metadata.get("environment"),
        incident.get("environment"),
        recommendation_metadata.get("environment"),
    )
    remediation_target = _first_non_empty(
        approval.metadata.get("remediation_target"),
        approval.metadata.get("target"),
        recommendation_metadata.get("remediation_target"),
        recommendation.get("target"),
        recommendation.get("resource"),
        incident.get("deployment"),
        service,
    )
    recommended_action = _first_non_empty(
        approval.metadata.get("recommended_action"),
        recommendation.get("recommended_action"),
        recommendation.get("action"),
    )
    recommended_commands = recommendation.get("commands") if isinstance(recommendation.get("commands"), list) else []

    if service:
        approval.metadata["service"] = service
        approval.metadata["incident_service"] = service
    if environment:
        approval.metadata["environment"] = environment
    if remediation_target:
        approval.metadata["remediation_target"] = remediation_target
        approval.metadata["target"] = remediation_target
    if recommended_action:
        approval.metadata["recommended_action"] = recommended_action
    if recommended_commands and not isinstance(approval.metadata.get("recommended_commands"), list):
        approval.metadata["recommended_commands"] = [str(item).strip() for item in recommended_commands if str(item).strip()]
    for key in ("runbook_id", "runbook_version", "runbook_status", "runbook_match_score"):
        if approval.metadata.get(key) is None and recommendation_metadata.get(key) is not None:
            approval.metadata[key] = recommendation_metadata[key]

    return approval


def _validate_auto_execution_policy(payload: dict[str, Any]) -> None:
    recommendation = payload.get("recommendation", {}) if isinstance(payload.get("recommendation"), dict) else {}
    metadata = recommendation.get("metadata", {}) if isinstance(recommendation.get("metadata"), dict) else {}
    orchestration = metadata.get("orchestration_decision", {}) if isinstance(metadata.get("orchestration_decision"), dict) else {}
    context_confidence, resolution_confidence = _rca_and_resolution_confidence(payload)
    threshold = float(settings.rca_resolution_auto_complete_threshold)
    if context_confidence is None or resolution_confidence is None:
        raise PolicyViolation("auto execution blocked: context and resolution confidence are both required")
    if context_confidence < threshold or resolution_confidence < threshold:
        raise PolicyViolation(
            f"auto execution blocked: context={context_confidence:.2f}, resolution={resolution_confidence:.2f}, threshold={threshold:.2f}"
        )

    rca_analysis = metadata.get("rca_analysis") if isinstance(metadata.get("rca_analysis"), dict) else {}
    evidence_ids = metadata.get("evidence_ids") or rca_analysis.get("evidence_used")
    if not isinstance(evidence_ids, list) or not evidence_ids:
        raise PolicyViolation("auto execution blocked: missing evidence_ids")

    reasoning = str(
        metadata.get("reasoning")
        or rca_analysis.get("causal_chain")
        or rca_analysis.get("root_cause")
        or recommendation.get("root_cause")
        or ""
    ).strip()
    if not reasoning:
        raise PolicyViolation("auto execution blocked: missing reasoning")

    commands = recommendation.get("commands") if isinstance(recommendation.get("commands"), list) else []
    runbook_id = str(metadata.get("runbook_id") or "").strip()
    if runbook_id:
        try:
            validate_automatic_runbook_use(
                runbook_id=runbook_id,
                runbook_status=str(metadata.get("runbook_status") or ""),
                evidence_match_score=float(metadata.get("runbook_match_score") or 0.0),
                minimum_match_score=threshold,
            )
        except (TypeError, ValueError) as exc:
            raise PolicyViolation(f"auto execution blocked: {exc}") from exc
    elif not any(str(item).strip() for item in commands):
        raise PolicyViolation("auto execution blocked: no approved runbook or concrete resolution command plan")


def _build_policy_blocked_action(payload: dict[str, Any], reason: str) -> RemediationAction | None:
    recommendation = payload.get("recommendation", {}) if isinstance(payload.get("recommendation"), dict) else {}
    incident_id = recommendation.get("incident_id")
    recommendation_id = recommendation.get("id")
    if incident_id is None:
        return None
    return RemediationAction(
        incident_id=incident_id,
        approval_id=None,
        action_type="policy-blocked",
        target=str(incident_id),
        status=RemediationStatus.SKIPPED,
        output="remediation blocked by policy engine",
        error=reason,
        metadata={
            "policy_blocked": True,
            "policy_reason": reason,
            "recommendation_id": recommendation_id,
            "source": "resolution-events",
        },
    )
