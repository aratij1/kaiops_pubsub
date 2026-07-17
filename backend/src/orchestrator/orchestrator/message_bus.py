from __future__ import annotations

from typing import Any

from common.event_publishers import build_agent_event_contract, build_orchestration_envelope
from common.models import Alert, Incident


def select_publisher(
    *,
    requested_provider: str,
    publishers: dict[str, Any],
    default_publisher: Any,
) -> tuple[Any, str]:
    provider = requested_provider.strip().lower() or "kafka"
    selected = publishers.get(provider)
    if selected is not None:
        return selected, provider
    if provider in {"kafka", "rabbitmq", "azure-service-bus", "servicebus", "azure"}:
        return default_publisher, provider
    fallback = publishers.get("kafka") or publishers.get("rabbitmq") or default_publisher
    return fallback, "kafka"


async def publish_orchestration_event(
    *,
    producer: Any,
    publishers: dict[str, Any],
    topic: str,
    alert: Alert,
    incident: Incident,
    decision: dict[str, Any],
) -> str:
    requested_provider = str(decision.get("message_bus_provider", "kafka"))
    selected_publisher, provider_used = select_publisher(
        requested_provider=requested_provider,
        publishers=publishers,
        default_publisher=producer,
    )
    event_envelope = build_orchestration_envelope(
        alert=alert,
        incident=incident,
        decision=decision,
        transport_provider=provider_used,
        channel=topic,
    )
    flow_id = str(decision.get("flow_id") or incident.id)
    contract_event = build_agent_event_contract(
        flow_id=flow_id,
        incident_id=str(incident.id),
        trace_id=str(incident.trace_id or alert.trace_id or ""),
        correlation_id=str(alert.correlation_id or "") or None,
        agent="orchestrator",
        payload={
            "workflow": decision.get("workflow"),
            "next_action": decision.get("next_action"),
            "transport_provider": provider_used,
            "topic": topic,
        },
        metadata={
            "policy_version": decision.get("policy_version"),
            "execution_mode": decision.get("execution_mode"),
            "risk_tier": decision.get("risk_tier"),
        },
        confidence=float(decision.get("confidence") or 0.0),
        reasoning=str(decision.get("planner_reason") or "deterministic severity routing"),
        evidence_ids=[str(alert.id)],
    )
    await selected_publisher.publish(
        topic,
        {
            "alert": alert,
            "incident": incident,
            "decision": decision,
            "transport": provider_used,
            "event_envelope": event_envelope,
            "event_contract": contract_event,
        },
        key=alert.service,
    )
    return provider_used
