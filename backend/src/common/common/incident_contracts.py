from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from common.models import EvidenceReference, utc_now


class TicketSeverity(StrEnum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class TicketStatus(StrEnum):
    NEW = "new"
    TRIAGED = "triaged"
    INVESTIGATING = "investigating"
    AWAITING_APPROVAL = "awaiting_approval"
    REMEDIATING = "remediating"
    VALIDATING = "validating"
    RESOLVED = "resolved"
    CLOSED = "closed"


class AuditMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    actor: str = "system"
    decision_id: str = Field(default_factory=lambda: str(uuid4()))
    rules_fired: list[str] = Field(default_factory=list)
    rationale: str
    ai_used: bool = False
    model_provider: str | None = None
    model_name: str | None = None
    trace_id: str | None = None

    @model_validator(mode="after")
    def require_ai_identity(self) -> AuditMetadata:
        if self.ai_used and (not self.model_provider or not self.model_name):
            raise ValueError("AI decisions require model_provider and model_name")
        return self


class CanonicalTicket(BaseModel):
    """Versioned, source-neutral ticket. Payload content is already redacted."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    ticket_id: str
    source: str
    source_reference: str
    title: str = Field(min_length=1, max_length=512)
    description: str = Field(max_length=65536)
    category: str
    subcategory: str
    severity: TicketSeverity
    priority: int = Field(ge=1, le=100)
    status: TicketStatus = TicketStatus.NEW
    affected_service: str
    environment: str
    customer_impact: str
    business_impact: str
    correlation_id: str
    duplicate_of: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[EvidenceReference] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    assigned_team: str | None = None
    assigned_engineer: str | None = None
    audit_metadata: AuditMetadata
    related_ticket_ids: list[str] = Field(default_factory=list)
    noise: bool = False
    false_positive: bool = False
    sla_deadline: datetime | None = None
    escalation_required: bool = False

    @field_validator("source", "environment")
    @classmethod
    def normalize_tokens(cls, value: str) -> str:
        return value.strip().lower()

    @model_validator(mode="after")
    def require_explainability(self) -> CanonicalTicket:
        if not self.audit_metadata.rationale.strip():
            raise ValueError("ticket decisions require a rationale")
        if self.audit_metadata.ai_used and not self.evidence:
            raise ValueError("AI ticket decisions require supporting evidence")
        return self


class CanonicalAlert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    alert_id: str
    source: str
    source_reference: str
    idempotency_key: str
    title: str
    description: str
    affected_service: str
    environment: str
    observed_severity: str
    correlation_id: str
    observed_at: datetime = Field(default_factory=utc_now)
    evidence: list[EvidenceReference] = Field(default_factory=list)
    labels: dict[str, str] = Field(default_factory=dict)
    redaction_applied: bool = True


class ContextPackage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    incident_id: str
    affected_services: list[str]
    related_incidents: list[dict[str, Any]] = Field(default_factory=list)
    relevant_logs: list[EvidenceReference] = Field(default_factory=list)
    metric_anomalies: list[EvidenceReference] = Field(default_factory=list)
    recent_changes: list[EvidenceReference] = Field(default_factory=list)
    deployments: list[EvidenceReference] = Field(default_factory=list)
    dependencies: list[EvidenceReference] = Field(default_factory=list)
    runbooks: list[EvidenceReference] = Field(default_factory=list)
    knowledge_documents: list[EvidenceReference] = Field(default_factory=list)
    source_code_evidence: list[EvidenceReference] = Field(default_factory=list)
    evidence_source: list[str] = Field(default_factory=list)
    evidence_timestamp: datetime = Field(default_factory=utc_now)
    relevance_score: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    missing_context: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)


class EventEnvelopeV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: str
    schema_version: Literal["1.0"] = "1.0"
    correlation_id: str
    causation_id: str | None = None
    incident_id: str
    source: str
    timestamp: datetime = Field(default_factory=utc_now)
    payload: dict[str, Any]
    trace_metadata: dict[str, str] = Field(default_factory=dict)

