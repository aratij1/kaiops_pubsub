from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from common.tenant_identity import require_tenant_id


class CanonicalEventEnvelopeV1(BaseModel):
    """Replay-safe Phase 9 envelope for new event boundaries.

    Existing nested envelopes remain supported during migration. New producers
    can emit this contract directly; optional entity identifiers are still
    serialized as null so every canonical field is present on the wire.
    """

    model_config = ConfigDict(extra="forbid")

    event_id: UUID = Field(default_factory=uuid4)
    event_type: str
    event_version: Literal["1.0"] = "1.0"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    tenant_id: str
    project_id: str | None = None
    application_id: str | None = None
    environment: str | None = None
    resource_id: str | None = None
    incident_id: str | None = None
    trace_id: str
    correlation_id: str
    causation_id: str | None = None
    source: str
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("event_type", "trace_id", "correlation_id", "source")
    @classmethod
    def required_strings_are_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("canonical event identity fields cannot be blank")
        return value

    @field_validator("tenant_id")
    @classmethod
    def tenant_is_verified(cls, value: str) -> str:
        return require_tenant_id(value, source="canonical event")

    def wire_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=False)


def canonical_event_from_legacy(envelope: dict[str, Any], *, source: str | None = None) -> CanonicalEventEnvelopeV1:
    """Adapt the existing nested v1 envelope without mutating it."""
    identity = envelope.get("identity") if isinstance(envelope.get("identity"), dict) else {}
    scope = envelope.get("scope") if isinstance(envelope.get("scope"), dict) else {}
    transport = envelope.get("transport") if isinstance(envelope.get("transport"), dict) else {}
    metadata = {
        "legacy_schema_version": envelope.get("schema_version") or envelope.get("version"),
        "state": envelope.get("state") if isinstance(envelope.get("state"), dict) else {},
        "policy": envelope.get("policy") if isinstance(envelope.get("policy"), dict) else {},
        "transport": transport,
        "idempotency": envelope.get("idempotency") if isinstance(envelope.get("idempotency"), dict) else {},
    }
    return CanonicalEventEnvelopeV1(
        event_id=envelope.get("event_id") or uuid4(),
        event_type=str(envelope.get("event_type") or "incident.event"),
        timestamp=envelope.get("produced_at") or envelope.get("timestamp") or datetime.now(UTC),
        tenant_id=scope.get("tenant_id"),
        project_id=scope.get("project_id"),
        application_id=scope.get("application_id"),
        environment=scope.get("environment"),
        resource_id=identity.get("resource_id"),
        incident_id=identity.get("incident_id") or envelope.get("incident_id"),
        trace_id=str(identity.get("trace_id") or envelope.get("trace_id") or ""),
        correlation_id=str(identity.get("correlation_id") or envelope.get("correlation_id") or envelope.get("event_id") or ""),
        causation_id=identity.get("causation_id"),
        source=str(source or scope.get("agent") or envelope.get("agent") or transport.get("provider") or "legacy"),
        payload=envelope.get("payload") if isinstance(envelope.get("payload"), dict) else {},
        metadata=metadata,
    )

