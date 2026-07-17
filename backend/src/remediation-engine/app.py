from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any
from uuid import UUID

from common.agent_runtime import PolicyViolation
from common.config import get_settings
from common.event_publishers import build_agent_event_contract, build_event_envelope
from common.kafka import KafkaConsumer, consume_forever as consume_kafka_forever
from common.models import Approval, ApprovalDecision, RemediationAction, RemediationStatus
from common.rabbitmq import RabbitMQConsumer, consume_forever as consume_rabbitmq_forever
from common.repository import IncidentRepository
from common.service import create_app
from common.telemetry import EVENTS_PROCESSED
from common.topics import APPROVAL_EVENTS, REMEDIATION_EVENTS, RESOLUTION_EVENTS
from fastapi import FastAPI
from remediation_engine import RemediationEngine

settings = get_settings()
settings.service_name = "remediation-engine"
engine = RemediationEngine()
tasks: list[asyncio.Task] = []

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
    elif action_status in {"failed", "rejected"}:
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
        action = await execute_approval(approval)
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
        action = await execute_approval(approval)
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


@app.post("/execute", response_model=RemediationAction)
async def execute_approval(approval: Approval) -> RemediationAction:
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
        action = engine.build_action(approval)
        if not engine.is_action_allowed(action.action_type):
            action.status = RemediationStatus.SKIPPED
            action.error = f"Action type '{action.action_type}' is not allowlisted"
            action.output = "remediation blocked by allowlist policy"
        else:
            action = await engine.execute(action)

    await _persist_action(app, action)
    return action


async def _persist_action(app: FastAPI, action: RemediationAction) -> None:
    if not settings.database_enabled:
        return
    async with app.state.session_factory() as session:
        repo = IncidentRepository(session)
        await repo.save_action(action)
        await repo.save_action_audit(action)
        await session.commit()


def _resolution_requires_approval(payload: dict[str, Any]) -> bool:
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

    metadata: dict[str, Any] = {"auto_approved": True, "approval_source": "resolution-events"}
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
    if remediation_target:
        metadata["remediation_target"] = remediation_target
        metadata["target"] = remediation_target
    recommended_action = _first_non_empty(recommendation.get("recommended_action"), recommendation.get("action"))
    recommended_commands = recommendation.get("commands") if isinstance(recommendation.get("commands"), list) else []
    if recommended_action:
        metadata["recommended_action"] = recommended_action
    if recommended_commands:
        metadata["recommended_commands"] = [str(item).strip() for item in recommended_commands if str(item).strip()]

    return Approval(
        incident_id=incident_id,
        recommendation_id=recommendation_id,
        decision=ApprovalDecision.APPROVED,
        approver="system-auto-approval",
        channel="web",
        comment=str(recommendation.get("recommended_action") or "auto-approved remediation"),
        metadata=metadata,
    )


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

    return approval


def _validate_auto_execution_policy(payload: dict[str, Any]) -> None:
    recommendation = payload.get("recommendation", {}) if isinstance(payload.get("recommendation"), dict) else {}
    metadata = recommendation.get("metadata", {}) if isinstance(recommendation.get("metadata"), dict) else {}
    orchestration = metadata.get("orchestration_decision", {}) if isinstance(metadata.get("orchestration_decision"), dict) else {}
    risk_tier = str(
        payload.get("decision", {}).get("risk_tier") if isinstance(payload.get("decision"), dict) else ""
    ).strip().lower() or str(orchestration.get("risk_tier") or "").strip().lower()

    confidence = float(recommendation.get("confidence") or 0.0)
    min_confidence = float(getattr(settings, "auto_execute_min_confidence", 0.8) or 0.8)
    if confidence < min_confidence:
        raise PolicyViolation(f"auto execution blocked: confidence {confidence:.2f} below threshold {min_confidence:.2f}")

    evidence_ids = metadata.get("evidence_ids")
    if not isinstance(evidence_ids, list) or not evidence_ids:
        raise PolicyViolation("auto execution blocked: missing evidence_ids")

    reasoning = str(metadata.get("reasoning") or "").strip()
    if not reasoning:
        raise PolicyViolation("auto execution blocked: missing reasoning")

    if risk_tier == "high" and confidence < 0.95:
        raise PolicyViolation("auto execution blocked: high-risk actions require confidence >= 0.95")


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
