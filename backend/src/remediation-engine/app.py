from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

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
    recommendation = source_payload.get("recommendation", {}) if isinstance(source_payload.get("recommendation"), dict) else {}
    decision = source_payload.get("decision", {}) if isinstance(source_payload.get("decision"), dict) else {}
    recommendation_metadata = recommendation.get("metadata", {}) if isinstance(recommendation.get("metadata"), dict) else {}
    orchestration = recommendation_metadata.get("orchestration_decision", {}) if isinstance(recommendation_metadata.get("orchestration_decision"), dict) else {}

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
                    "service": str(action.target or "unknown"),
                    "environment": "prod",
                    "region": None,
                    "team": None,
                },
                state={
                    "severity": str(recommendation.get("severity") or "warning").lower(),
                    "status": state_status,
                    "owner": None,
                },
                policy={
                    "risk_tier": str(decision.get("risk_tier") or orchestration.get("risk_tier") or "unknown"),
                    "execution_mode": str(decision.get("execution_mode") or orchestration.get("execution_mode") or "unknown"),
                    "requires_approval": decision.get("requires_approval") if "requires_approval" in decision else orchestration.get("requires_approval"),
                    "policy_version": action.parameters.get("policy_version") or decision.get("policy_version") or orchestration.get("policy_version") or recommendation_metadata.get("policy_version"),
                    "policy_reason": action.parameters.get("policy_reason") or decision.get("policy_reason") or orchestration.get("policy_reason") or recommendation_metadata.get("policy_reason"),
                },
                transport={
                    "provider": str(decision.get("message_bus_provider") or orchestration.get("message_bus_provider") or "unknown"),
                    "channel": REMEDIATION_EVENTS,
                    "partition": None,
                    "offset": None,
                    "delivery_tag": None,
                },
                payload={
                    "source": source,
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

    return Approval(
        incident_id=incident_id,
        recommendation_id=recommendation_id,
        decision=ApprovalDecision.APPROVED,
        approver="system-auto-approval",
        channel="web",
        comment=str(recommendation.get("recommended_action") or "auto-approved remediation"),
        metadata=metadata,
    )


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
