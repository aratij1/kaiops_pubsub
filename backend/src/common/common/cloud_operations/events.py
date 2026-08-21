from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import uuid4


SCHEMA_VERSION = "kaims.cloud-ops.event.v1"


def build_cloud_event(
    *,
    event_type: str,
    tenant_id: str,
    project_id: str,
    service_id: str | None,
    producer: str,
    payload: dict[str, Any],
    correlation_id: str | None = None,
    causation_id: str | None = None,
) -> dict[str, Any]:
    material = f"{event_type}:{tenant_id}:{project_id}:{service_id or ''}:{payload}"
    idempotency_key = sha256(material.encode("utf-8", errors="ignore")).hexdigest()
    return {
        "event_id": str(uuid4()),
        "event_type": event_type,
        "schema_version": SCHEMA_VERSION,
        "tenant_id": tenant_id,
        "project_id": project_id,
        "service_id": service_id,
        "correlation_id": correlation_id,
        "causation_id": causation_id,
        "idempotency_key": idempotency_key,
        "event_time": datetime.now(UTC).isoformat(),
        "producer": producer,
        "trace": {},
        "payload": payload,
    }
