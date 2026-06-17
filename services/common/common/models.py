from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class AlertSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    HIGH = "high"
    CRITICAL = "critical"


class IncidentStatus(StrEnum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    AWAITING_APPROVAL = "awaiting_approval"
    REMEDIATING = "remediating"
    VALIDATING = "validating"
    CLOSED = "closed"
    FAILED = "failed"


class ApprovalDecision(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    MODIFIED = "modified"


class RemediationStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class BaseEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=utc_now)
    trace_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Alert(BaseEvent):
    source: str
    name: str
    service: str
    environment: str = "prod"
    severity: AlertSeverity = AlertSeverity.WARNING
    description: str
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    starts_at: datetime = Field(default_factory=utc_now)
    ends_at: datetime | None = None
    fingerprint: str | None = None
    correlation_id: str | None = None
    deduplicated_count: int = 1

    @field_validator("source")
    @classmethod
    def normalize_source(cls, value: str) -> str:
        return value.strip().lower()


class Incident(BaseEvent):
    alert_ids: list[UUID] = Field(default_factory=list)
    service: str
    environment: str = "prod"
    severity: AlertSeverity = AlertSeverity.WARNING
    status: IncidentStatus = IncidentStatus.OPEN
    title: str
    summary: str = ""
    owner_team: str | None = None
    ticket_id: str | None = None
    closed_at: datetime | None = None


class Context(BaseEvent):
    incident_id: UUID
    alert: Alert
    deployment: str | None = None
    related_incidents: list[dict[str, Any]] = Field(default_factory=list)
    runbook: str = ""
    dependency_services: list[str] = Field(default_factory=list)
    recent_changes: list[dict[str, Any]] = Field(default_factory=list)
    cmdb: dict[str, Any] = Field(default_factory=dict)
    cloud: dict[str, Any] = Field(default_factory=dict)
    kubernetes: dict[str, Any] = Field(default_factory=dict)
    observability: dict[str, Any] = Field(default_factory=dict)


class Recommendation(BaseEvent):
    incident_id: UUID
    root_cause: str
    confidence: float = Field(ge=0.0, le=1.0)
    impact: str
    recommended_action: str
    severity: AlertSeverity
    rationale: str
    commands: list[str] = Field(default_factory=list)
    risk: str = "medium"


class Approval(BaseEvent):
    incident_id: UUID
    recommendation_id: UUID
    decision: ApprovalDecision = ApprovalDecision.PENDING
    approver: str | None = None
    channel: str = "web"
    comment: str | None = None
    modified_action: str | None = None


class RemediationAction(BaseEvent):
    incident_id: UUID
    approval_id: UUID | None = None
    action_type: str
    target: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    status: RemediationStatus = RemediationStatus.PENDING
    started_at: datetime | None = None
    completed_at: datetime | None = None
    output: str = ""
    error: str | None = None


class ResolutionReport(BaseEvent):
    incident_id: UUID
    recommendation_id: UUID | None = None
    remediation_action_id: UUID | None = None
    root_cause: str
    impact: str
    action_taken: str
    validation: dict[str, bool] = Field(default_factory=dict)
    alerts_cleared: bool = False
    health_restored: bool = False
    knowledge_base_entry: str = ""
    lessons_learned: list[str] = Field(default_factory=list)
