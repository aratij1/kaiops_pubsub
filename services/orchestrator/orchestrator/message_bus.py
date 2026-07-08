from __future__ import annotations

from typing import Any

from common.event_publishers import build_orchestration_envelope
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
    fallback = publishers.get("kafka", default_publisher)
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
    await selected_publisher.publish(
        topic,
        {
            "alert": alert,
            "incident": incident,
            "decision": decision,
            "transport": provider_used,
            "event_envelope": event_envelope,
        },
        key=alert.service,
    )
    return provider_used
