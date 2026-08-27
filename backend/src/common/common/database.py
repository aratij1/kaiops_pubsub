from __future__ import annotations

from datetime import datetime
from time import perf_counter
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Index, JSON, BigInteger, Boolean, DateTime, ForeignKey, Integer, MetaData, Numeric, String, Text, UniqueConstraint, Uuid, event, text
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from common.config import Settings
from common.models import utc_now
from common.resilience import CircuitBreaker, CircuitOpenError
from common.telemetry import MYSQL_QUERY_LATENCY
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

metadata = MetaData()


class Base(DeclarativeBase):
    metadata = metadata


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class ObjectStorageRecord(Base, TimestampMixin):
    __tablename__ = "object_storage_metadata"
    __table_args__ = (
        Index("idx_object_storage_scope_created", "application", "environment", "created_at"),
        Index("idx_object_storage_relation", "incident_id", "alert_id"),
        Index("idx_object_storage_status_created", "processing_status", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True, default="default")
    object_key: Mapped[str] = mapped_column(String(512), unique=True)
    object_uri: Mapped[str] = mapped_column(String(1536))
    object_type: Mapped[str] = mapped_column(String(64), index=True)
    application: Mapped[str | None] = mapped_column(String(255), index=True)
    environment: Mapped[str | None] = mapped_column(String(64), index=True)
    incident_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), index=True)
    alert_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), index=True)
    source: Mapped[str | None] = mapped_column(String(128), index=True)
    occurrence_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    checksum_sha256: Mapped[str] = mapped_column(String(64), index=True)
    retention_policy: Mapped[str] = mapped_column(String(64), default="standard", index=True)
    security_classification: Mapped[str] = mapped_column(String(64), default="internal", index=True)
    processing_status: Mapped[str] = mapped_column(String(32), default="stored", index=True)
    metadata_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class AlertRecord(Base, TimestampMixin):
    __tablename__ = "alerts"
    __table_args__ = (
        Index("idx_alerts_created_at", "created_at"),
        Index("idx_alerts_tenant_updated", "tenant_id", "updated_at"),
        Index("idx_alerts_tenant_created", "tenant_id", "created_at"),
        Index("idx_alerts_tenant_env_created", "tenant_id", "environment", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True, default="default")
    source: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    service: Mapped[str] = mapped_column(String(128), index=True)
    environment: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(32), index=True)
    fingerprint: Mapped[str | None] = mapped_column(String(255), index=True)
    correlation_id: Mapped[str | None] = mapped_column(String(255), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class IncidentRecord(Base, TimestampMixin):
    __tablename__ = "incidents"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True, default="default")
    service: Mapped[str] = mapped_column(String(128), index=True)
    environment: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(255))
    ticket_id: Mapped[str | None] = mapped_column(String(128), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class IncidentCorrelationOwnershipRecord(Base, TimestampMixin):
    __tablename__ = "incident_correlation_ownership"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "project_id", "environment", "service",
            "correlation_key", "correlation_generation",
            name="uq_incident_correlation_generation",
        ),
        Index(
            "idx_incident_correlation_lookup",
            "tenant_id", "project_id", "environment", "service", "correlation_key",
        ),
        Index("idx_incident_correlation_page", "tenant_id", "first_seen_at", "id"),
        Index(
            "idx_incident_correlation_family_generation",
            "tenant_id",
            "correlation_family_id",
            "correlation_generation",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True)
    environment: Mapped[str] = mapped_column(String(64), index=True)
    service: Mapped[str] = mapped_column(String(128), index=True)
    correlation_key: Mapped[str] = mapped_column(String(255))
    correlation_family_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    correlation_generation: Mapped[int] = mapped_column(Integer)
    canonical_incident_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    correlation_window_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    lifecycle_state: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class IncidentOccurrenceRecord(Base):
    __tablename__ = "incident_occurrences"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_incident_occurrence_idempotency"),
        Index("idx_incident_occurrence_canonical_seen", "canonical_incident_id", "observed_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True)
    environment: Mapped[str] = mapped_column(String(64), index=True)
    service: Mapped[str] = mapped_column(String(128), index=True)
    correlation_family_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    correlation_generation: Mapped[int] = mapped_column(Integer)
    canonical_incident_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    occurrence_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255))
    causation_id: Mapped[str | None] = mapped_column(String(255), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class IncidentCorrelationBackfillRecord(Base, TimestampMixin):
    __tablename__ = "incident_correlation_backfill"

    incident_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    backfill_version: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(64), default="incidents")
    status: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str] = mapped_column(String(255))
    project_id: Mapped[str] = mapped_column(String(128), index=True)
    needs_scope_review: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    correlation_family_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), index=True)
    correlation_generation: Mapped[int | None] = mapped_column(Integer)


class ApprovalRecord(Base, TimestampMixin):
    __tablename__ = "approvals"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True, default="default")
    incident_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    recommendation_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    plan_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), index=True, nullable=True)
    plan_fingerprint: Mapped[str | None] = mapped_column(String(71), index=True, nullable=True)
    approval_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approver_role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decision: Mapped[str] = mapped_column(String(32), index=True)
    approver: Mapped[str | None] = mapped_column(String(255))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class ApprovalCapacityRecord(Base, TimestampMixin):
    __tablename__ = "approval_capacity"
    __table_args__ = (UniqueConstraint("tenant_id", "username", name="uq_approval_capacity_tenant_username"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True, default="default")
    username: Mapped[str] = mapped_column(String(255), index=True)
    resource_names: Mapped[list[str]] = mapped_column(JSON, default=list)
    weekly_hours: Mapped[int] = mapped_column(Integer, default=0)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    working_days: Mapped[list[int]] = mapped_column(JSON, default=lambda: [0, 1, 2, 3, 4])
    work_start: Mapped[str] = mapped_column(String(5), default="09:00")
    work_end: Mapped[str] = mapped_column(String(5), default="17:00")
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class ApprovalAssignmentRecord(Base, TimestampMixin):
    __tablename__ = "approval_assignments"
    __table_args__ = (UniqueConstraint("tenant_id", "incident_id", name="uq_approval_assignment_tenant_incident"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True, default="default")
    incident_id: Mapped[str] = mapped_column(String(128), index=True)
    assignee: Mapped[str] = mapped_column(String(255), index=True)
    service: Mapped[str] = mapped_column(String(128), index=True)
    estimated_hours: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="assigned", index=True)
    assignment_reason: Mapped[str] = mapped_column(Text)


class ActionRecord(Base, TimestampMixin):
    __tablename__ = "actions"
    __table_args__ = (Index("idx_actions_tenant_updated", "tenant_id", "updated_at"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True, default="default")
    incident_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    action_type: Mapped[str] = mapped_column(String(128), index=True)
    target: Mapped[str] = mapped_column(String(255), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class ResolutionOutboxRecord(Base, TimestampMixin):
    """Durable handoff between a committed lifecycle change and the broker."""

    __tablename__ = "resolution_outbox"
    __table_args__ = (
        Index("idx_resolution_outbox_pending", "status", "next_attempt_at", "created_at"),
        Index("idx_resolution_outbox_aggregate", "tenant_id", "aggregate_id", "created_at"),
    )

    event_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True, default="default")
    aggregate_id: Mapped[str] = mapped_column(String(128), index=True)
    topic: Mapped[str] = mapped_column(String(255), index=True)
    partition_key: Mapped[str] = mapped_column(String(255))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), index=True, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class DraftPullRequestOutboxRecord(Base, TimestampMixin):
    """Durable, idempotent request to create one review-only pull request."""

    __tablename__ = "draft_pull_request_outbox"
    __table_args__ = (
        Index("idx_draft_pr_outbox_due", "status", "next_attempt_at", "created_at"),
        Index("idx_draft_pr_outbox_tenant_proposal", "tenant_id", "proposal_id"),
    )

    job_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    proposal_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), index=True, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    provider_response: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    last_error: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RcaReportRecord(Base, TimestampMixin):
    __tablename__ = "rca_reports"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True, default="default")
    incident_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    root_cause: Mapped[str] = mapped_column(Text)
    impact: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class ValidationObservationRecord(Base):
    __tablename__ = "validation_observations"
    __table_args__ = (
        Index("idx_validation_observations_incident_time", "tenant_id", "incident_id", "observed_at"),
        Index("idx_validation_observations_validator_time", "tenant_id", "validator_id", "observed_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    incident_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    report_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    remediation_action_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    validator_id: Mapped[str] = mapped_column(String(255), nullable=False)
    connector_id: Mapped[str] = mapped_column(String(255), nullable=False)
    target_resource_id: Mapped[str] = mapped_column(String(768), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    authoritative_source: Mapped[str] = mapped_column(String(255), nullable=False)
    result_checksum: Mapped[str] = mapped_column(String(80), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class KnowledgeBaseRecord(Base, TimestampMixin):
    __tablename__ = "knowledge_base"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True, default="default")
    service: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text().with_variant(LONGTEXT(), "mysql"))
    embedding_ref: Mapped[str | None] = mapped_column(String(255))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ContextKnowledgeRecord(Base, TimestampMixin):
    """Reusable context snapshot for a tenant-scoped alert family."""

    __tablename__ = "context_knowledge"
    __table_args__ = (
        Index(
            "idx_context_knowledge_lookup",
            "tenant_id",
            "service",
            "environment",
            "alert_signature",
            "updated_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True, default="default")
    service: Mapped[str] = mapped_column(String(128), index=True)
    environment: Mapped[str] = mapped_column(String(64), index=True)
    alert_name: Mapped[str] = mapped_column(String(255), index=True)
    alert_signature: Mapped[str] = mapped_column(String(64), index=True)
    source_alert_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), index=True)
    source_incident_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), index=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    reuse_count: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    resolution_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ContextSnapshotRecord(Base):
    """Immutable per-incident context package used for audit and RCA replay."""

    __tablename__ = "context_snapshots"
    __table_args__ = (
        Index("idx_context_snapshots_incident_collected", "tenant_id", "incident_id", "collected_at"),
        Index("idx_context_snapshots_subject_collected", "tenant_id", "subject_fingerprint", "collected_at"),
    )

    snapshot_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True, default="default")
    incident_id: Mapped[str] = mapped_column(String(128), index=True)
    source_incident_id: Mapped[str | None] = mapped_column(String(128), index=True)
    alert_signature: Mapped[str] = mapped_column(String(64), index=True)
    subject_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    context_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    contract_version: Mapped[str] = mapped_column(String(32), default="kaiops.context.v2")
    quality_score: Mapped[float] = mapped_column(Numeric(5, 4), default=0.0)
    reusable: Mapped[bool] = mapped_column(Boolean, default=False)
    source_manifest: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class AuditLogRecord(Base, TimestampMixin):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("idx_audit_logs_resource_action_created", "resource_type", "action", "created_at"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True, default="default")
    actor: Mapped[str] = mapped_column(String(255), index=True)
    action: Mapped[str] = mapped_column(String(255), index=True)
    resource_type: Mapped[str] = mapped_column(String(128), index=True)
    resource_id: Mapped[str] = mapped_column(String(128), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class RunbookVersionRecord(Base):
    """Durable execution eligibility for one immutable runbook version."""

    __tablename__ = "runbook_versions"
    runbook_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True, default="default")
    issue_signature: Mapped[str] = mapped_column(String(64), index=True)
    approval_status: Mapped[str] = mapped_column(String(32), index=True, default="draft")
    owner: Mapped[str] = mapped_column(String(255))
    risk_level: Mapped[str] = mapped_column(String(32))
    required_approval: Mapped[str] = mapped_column(String(32))
    content: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    approved_by: Mapped[str | None] = mapped_column(String(255))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class IncidentEvidenceRecord(Base):
    """Canonical, tenant-isolated evidence snapshot used by both processing modes."""

    __tablename__ = "incident_evidence"
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True, default="default")
    incident_id: Mapped[str] = mapped_column(String(128), index=True)
    issue_signature: Mapped[str] = mapped_column(String(64), index=True)
    service: Mapped[str] = mapped_column(String(255), index=True)
    environment: Mapped[str] = mapped_column(String(64), index=True)
    alert_type: Mapped[str] = mapped_column(String(255))
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class FailurePatternRecord(Base):
    """Latest deterministic analysis for a recurring issue signature."""

    __tablename__ = "failure_patterns"
    pattern_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True, default="default")
    issue_signature: Mapped[str] = mapped_column(String(64), index=True)
    service: Mapped[str] = mapped_column(String(255), index=True)
    environment: Mapped[str] = mapped_column(String(64), index=True)
    analysis: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    confidence: Mapped[float] = mapped_column(Numeric(5, 4))
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class RunbookOutcomeRecord(Base):
    """Immutable execution outcome feeding confidence and suspension decisions."""

    __tablename__ = "runbook_outcomes"
    outcome_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True, default="default")
    incident_id: Mapped[str] = mapped_column(String(128), index=True)
    runbook_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    runbook_version: Mapped[int] = mapped_column(Integer)
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    successful: Mapped[bool] = mapped_column(Boolean)
    validation: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class LearningAuditRecord(Base):
    """Append-only, hash-verifiable learning and governance event."""

    __tablename__ = "learning_audit_log"
    sequence_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), unique=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True, default="default")
    actor: Mapped[str] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(128), index=True)
    resource_type: Mapped[str] = mapped_column(String(64), index=True)
    resource_id: Mapped[str] = mapped_column(String(128), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    payload_sha256: Mapped[str] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class HumanCorrectionRecord(Base, TimestampMixin):
    """Immutable, tenant-scoped feedback on an automated decision."""

    __tablename__ = "human_corrections"
    __table_args__ = (
        Index("idx_human_corrections_entity_created", "tenant_id", "entity_type", "entity_id", "created_at"),
        Index("idx_human_corrections_type_created", "tenant_id", "correction_type", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True, default="default")
    entity_type: Mapped[str] = mapped_column(String(64), index=True)
    entity_id: Mapped[str] = mapped_column(String(255), index=True)
    correction_type: Mapped[str] = mapped_column(String(64), index=True)
    original_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    corrected_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    reason: Mapped[str] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(255), index=True)
    actor_role: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="recorded", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class OnboardingStateRecord(Base, TimestampMixin):
    __tablename__ = "onboarding_state"

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True, default="default", index=True)
    project_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    provider_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_team: Mapped[str | None] = mapped_column(String(255))
    environment: Mapped[str | None] = mapped_column(String(64))
    region: Mapped[str | None] = mapped_column(String(128))
    endpoint_url: Mapped[str | None] = mapped_column(String(512))
    test_status: Mapped[str | None] = mapped_column(String(32), index=True)
    test_message: Mapped[str | None] = mapped_column(String(512))
    project_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    connectivity_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OnboardingControlPlaneRecord(Base, TimestampMixin):
    __tablename__ = "onboarding_control_planes"
    __table_args__ = (
        Index("idx_onboarding_control_plane_tenant_status", "tenant_id", "status"),
    )

    onboarding_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    project_name: Mapped[str] = mapped_column(String(255), index=True)
    current_step: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="DRAFT", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ApplicationRecord(Base, TimestampMixin):
    __tablename__ = "applications"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True, default="default")
    name: Mapped[str] = mapped_column(String(255), index=True)
    owner_team: Mapped[str] = mapped_column(String(255), index=True)
    owner_email: Mapped[str | None] = mapped_column(String(255), index=True)
    environment: Mapped[str] = mapped_column(String(64), index=True)
    namespace: Mapped[str] = mapped_column(String(128), index=True)
    region: Mapped[str] = mapped_column(String(128), index=True)
    technology: Mapped[str] = mapped_column(String(128), index=True)
    monitoring_platform: Mapped[str] = mapped_column(String(64), index=True, default="prometheus")
    metrics_endpoint: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(64), index=True, default="registered")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ApplicationEnvironmentRecord(Base, TimestampMixin):
    __tablename__ = "application_environments"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    application_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True, default="default")
    environment: Mapped[str] = mapped_column(String(64), index=True)
    namespace: Mapped[str] = mapped_column(String(128), index=True)
    region: Mapped[str] = mapped_column(String(128), index=True)
    cluster: Mapped[str | None] = mapped_column(String(128), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ApplicationLabelRecord(Base, TimestampMixin):
    __tablename__ = "application_labels"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    application_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True, default="default")
    label_key: Mapped[str] = mapped_column(String(255), index=True)
    label_value: Mapped[str] = mapped_column(String(255), index=True)


class MonitoringProfileRecord(Base, TimestampMixin):
    __tablename__ = "monitoring_profiles"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    application_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True, default="default")
    platform: Mapped[str] = mapped_column(String(64), index=True)
    exporter: Mapped[str | None] = mapped_column(String(128), index=True)
    technology: Mapped[str | None] = mapped_column(String(128), index=True)
    metrics_available: Mapped[bool] = mapped_column(Boolean, default=False)
    governance_status: Mapped[str | None] = mapped_column(String(64), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class PrometheusConfigRecord(Base, TimestampMixin):
    __tablename__ = "prometheus_configs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    application_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True, default="default")
    config_type: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    file_path: Mapped[str] = mapped_column(String(512))
    content: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class AlertRuleRecord(Base, TimestampMixin):
    __tablename__ = "alert_rules"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    application_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True, default="default")
    name: Mapped[str] = mapped_column(String(255), index=True)
    expression: Mapped[str] = mapped_column(Text)
    duration: Mapped[str] = mapped_column(String(64), default="5m")
    severity: Mapped[str] = mapped_column(String(32), index=True, default="warning")
    labels: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    annotations: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class RecordingRuleRecord(Base, TimestampMixin):
    __tablename__ = "recording_rules"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    application_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True, default="default")
    name: Mapped[str] = mapped_column(String(255), index=True)
    expression: Mapped[str] = mapped_column(Text)
    labels: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class GrafanaDashboardRecord(Base, TimestampMixin):
    __tablename__ = "grafana_dashboards"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    application_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True, default="default")
    dashboard_uid: Mapped[str] = mapped_column(String(255), index=True)
    title: Mapped[str] = mapped_column(String(255), index=True)
    url: Mapped[str | None] = mapped_column(String(512))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class OnboardingHistoryRecord(Base, TimestampMixin):
    __tablename__ = "onboarding_history"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    application_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True, default="default")
    event_type: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(64), index=True)
    actor: Mapped[str] = mapped_column(String(255), index=True)
    agent: Mapped[str] = mapped_column(String(255), index=True)
    decision: Mapped[str] = mapped_column(String(128), index=True)
    execution_time_ms: Mapped[float] = mapped_column(default=0.0)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ValidationHistoryRecord(Base, TimestampMixin):
    __tablename__ = "validation_history"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    application_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True, default="default")
    target_up: Mapped[bool] = mapped_column(Boolean, default=False)
    metrics_available: Mapped[bool] = mapped_column(Boolean, default=False)
    alerts_loaded: Mapped[bool] = mapped_column(Boolean, default=False)
    recording_rules_loaded: Mapped[bool] = mapped_column(Boolean, default=False)
    service_discovery_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    dashboard_ready: Mapped[bool] = mapped_column(Boolean, default=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class PendingWorkflowRecord(Base, TimestampMixin):
    __tablename__ = "pending_workflows"

    incident_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    recommendation_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    flow_id: Mapped[str] = mapped_column(String(128), index=True)
    trace_id: Mapped[str | None] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    completed_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class AgentWorkItemRecord(Base, TimestampMixin):
    __tablename__ = "agent_work_items"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    incident_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    agent_name: Mapped[str] = mapped_column(String(128), index=True)
    trace_id: Mapped[str | None] = mapped_column(String(128), index=True)
    ticket_id: Mapped[str | None] = mapped_column(String(128), index=True)
    work_item: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), index=True)
    sequence: Mapped[int | None] = mapped_column(Integer)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IncidentEventRecord(Base):
    __tablename__ = "incident_events"
    __table_args__ = (
        Index("idx_incident_events_incident_created", "incident_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    incident_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    alert_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), index=True)
    trace_id: Mapped[str | None] = mapped_column(String(128), index=True)
    correlation_id: Mapped[str | None] = mapped_column(String(255), index=True)
    causation_id: Mapped[str | None] = mapped_column(String(255))
    parent_event_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), index=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True, default="default")
    service: Mapped[str] = mapped_column(String(128), index=True)
    environment: Mapped[str] = mapped_column(String(64), index=True)
    region: Mapped[str | None] = mapped_column(String(128))
    team: Mapped[str | None] = mapped_column(String(128))
    severity: Mapped[str | None] = mapped_column(String(32), index=True)
    status: Mapped[str | None] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(128), index=True)
    event_stage: Mapped[str] = mapped_column(String(64), index=True)
    risk_tier: Mapped[str | None] = mapped_column(String(32), index=True)
    execution_mode: Mapped[str | None] = mapped_column(String(32), index=True)
    requires_approval: Mapped[bool | None] = mapped_column(Boolean)
    policy_version: Mapped[str | None] = mapped_column(String(64), index=True)
    policy_reason: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column()
    model_provider: Mapped[str | None] = mapped_column(String(64))
    model_name: Mapped[str | None] = mapped_column(String(128))
    transport_provider: Mapped[str] = mapped_column(String(32), index=True)
    transport_channel: Mapped[str] = mapped_column(String(128), index=True)
    transport_partition: Mapped[int | None] = mapped_column(Integer)
    transport_offset: Mapped[int | None] = mapped_column(BigInteger)
    transport_delivery_tag: Mapped[str | None] = mapped_column(String(128))
    idempotency_key: Mapped[str | None] = mapped_column(String(255), index=True)
    fingerprint: Mapped[str | None] = mapped_column(String(255))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class IncidentProjectionRecord(Base, TimestampMixin):
    __tablename__ = "incident_projections"
    __table_args__ = (Index("idx_incident_projections_tenant_updated", "tenant_id", "updated_at"),)

    incident_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    alert_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), index=True)
    trace_id: Mapped[str | None] = mapped_column(String(128), index=True)
    recommendation_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), index=True)
    flow_id: Mapped[str | None] = mapped_column(String(128), index=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True, default="default")
    service: Mapped[str] = mapped_column(String(128), index=True)
    environment: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str | None] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(64), index=True)
    owner: Mapped[str | None] = mapped_column(String(128), index=True)
    risk_tier: Mapped[str | None] = mapped_column(String(32), index=True)
    execution_mode: Mapped[str | None] = mapped_column(String(32), index=True)
    requires_approval: Mapped[bool | None] = mapped_column(Boolean)
    policy_version: Mapped[str | None] = mapped_column(String(64), index=True)
    policy_reason: Mapped[str | None] = mapped_column(Text)
    transport_provider: Mapped[str | None] = mapped_column(String(32), index=True)
    latest_event_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), index=True)
    latest_event_type: Mapped[str | None] = mapped_column(String(128), index=True)
    latest_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    document_available: Mapped[bool | None] = mapped_column(Boolean)
    projection_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class RoleRecord(Base, TimestampMixin):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(String(255))
    is_system_role: Mapped[bool] = mapped_column(Boolean, default=True)


class UserRecord(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True, default="default")
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    first_name: Mapped[str] = mapped_column(String(80))
    last_name: Mapped[str] = mapped_column(String(80))
    role_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("roles.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class UserSessionRecord(Base, TimestampMixin):
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    jwt_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    login_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expiry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    device: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)


class MonitoringIntegrationRecord(Base, TimestampMixin):
    __tablename__ = "monitoring_integrations"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True, default="default")
    project_name: Mapped[str] = mapped_column(String(255), index=True)
    provider: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True, default="draft")
    active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    auth_type: Mapped[str] = mapped_column(String(64), default="api_key", index=True)
    endpoint_url: Mapped[str | None] = mapped_column(String(512), index=True)
    webhook_path: Mapped[str] = mapped_column(String(255), index=True)
    deployment_mode: Mapped[str] = mapped_column(String(64), default="existing_monitoring")
    config_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    validation_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class MonitoringCredentialRecord(Base, TimestampMixin):
    __tablename__ = "monitoring_credentials"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    integration_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    credential_type: Mapped[str] = mapped_column(String(64), index=True)
    secret_ref: Mapped[str] = mapped_column(String(255), index=True)
    encrypted_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    redacted_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class MonitoringWebhookEndpointRecord(Base, TimestampMixin):
    __tablename__ = "monitoring_webhook_endpoints"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    integration_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    provider: Mapped[str] = mapped_column(String(64), index=True)
    webhook_path: Mapped[str] = mapped_column(String(255), index=True)
    token_hash: Mapped[str | None] = mapped_column(String(255))
    hmac_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    m_tls_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    metadata_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class MonitoringAlertMappingRecord(Base, TimestampMixin):
    __tablename__ = "monitoring_alert_mappings"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    integration_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    provider: Mapped[str] = mapped_column(String(64), index=True)
    provider_field: Mapped[str] = mapped_column(String(128), index=True)
    kaiops_field: Mapped[str] = mapped_column(String(128), index=True)
    transform: Mapped[str | None] = mapped_column(String(128))
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    mapping_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class MonitoringConnectionHealthRecord(Base, TimestampMixin):
    __tablename__ = "monitoring_connection_health"
    __table_args__ = (Index("idx_monitoring_health_updated", "updated_at"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    integration_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    provider: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True, default="unknown")
    connectivity_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    authentication_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    webhook_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    last_received_alert_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_successful_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    rate_limit_remaining: Mapped[int | None] = mapped_column(Integer)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class MonitoringReceivedAlertRecord(Base, TimestampMixin):
    __tablename__ = "monitoring_received_alerts"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    integration_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), index=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True, default="default")
    provider: Mapped[str] = mapped_column(String(64), index=True)
    provider_alert_id: Mapped[str | None] = mapped_column(String(255), index=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(255), index=True)
    signature_valid: Mapped[bool] = mapped_column(Boolean, default=True)
    auth_valid: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(32), default="received", index=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class MonitoringNormalizedAlertRecord(Base, TimestampMixin):
    __tablename__ = "monitoring_normalized_alerts"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    received_alert_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    integration_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), index=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True, default="default")
    provider: Mapped[str] = mapped_column(String(64), index=True)
    application: Mapped[str | None] = mapped_column(String(255), index=True)
    environment: Mapped[str | None] = mapped_column(String(64), index=True)
    severity: Mapped[str | None] = mapped_column(String(32), index=True)
    alert_name: Mapped[str] = mapped_column(String(255), index=True)
    resource: Mapped[str | None] = mapped_column(String(255), index=True)
    labels: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    annotations: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    normalized_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class MonitoringConnectionAuditRecord(Base):
    __tablename__ = "monitoring_connection_audit"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    integration_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), index=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True, default="default")
    actor: Mapped[str] = mapped_column(String(255), index=True, default="system")
    action: Mapped[str] = mapped_column(String(128), index=True)
    provider: Mapped[str | None] = mapped_column(String(64), index=True)
    outcome: Mapped[str] = mapped_column(String(32), index=True, default="success")
    message: Mapped[str | None] = mapped_column(String(512))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class ProviderConnectionRecord(Base, TimestampMixin):
    __tablename__ = "provider_connections"
    __table_args__ = (
        UniqueConstraint("tenant_id", "project_id", "connection_name", name="uq_provider_connections_scope_name"),
        Index("idx_provider_connections_scope_status", "tenant_id", "project_id", "provider_type", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True)
    provider_type: Mapped[str] = mapped_column(String(64), index=True)
    connection_name: Mapped[str] = mapped_column(String(255), index=True)
    credential_ref: Mapped[str] = mapped_column(String(512), default="")
    auth_method: Mapped[str] = mapped_column(String(64), default="credential_ref", index=True)
    allowed_regions: Mapped[list[str]] = mapped_column(JSON, default=list)
    resource_filters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    discovery_scope: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    read_capability: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    write_capability: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    connection_owner: Mapped[str] = mapped_column(String(255), index=True)
    last_health_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_discovery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)


class ConnectionHealthCheckRecord(Base, TimestampMixin):
    __tablename__ = "connection_health_checks"
    __table_args__ = (
        Index("idx_connection_health_scope_created", "tenant_id", "project_id", "connection_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    connection_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True)
    provider_type: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    connectivity_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    authentication_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    requested_permissions: Mapped[list[str]] = mapped_column(JSON, default=list)
    granted_permissions: Mapped[list[str]] = mapped_column(JSON, default=list)
    missing_permissions: Mapped[list[str]] = mapped_column(JSON, default=list)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class DiscoveryRunRecord(Base, TimestampMixin):
    __tablename__ = "discovery_runs"
    __table_args__ = (
        Index("idx_discovery_runs_scope_started", "tenant_id", "project_id", "provider_type", "started_at"),
        Index("idx_discovery_runs_connection_started", "connection_id", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True)
    connection_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    provider_type: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True, default="started")
    requested_by: Mapped[str] = mapped_column(String(255), index=True)
    discovery_scope: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    resource_count: Mapped[int] = mapped_column(Integer, default=0)
    relationship_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)


class DiscoveredResourceRecord(Base, TimestampMixin):
    __tablename__ = "discovered_resources"
    __table_args__ = (
        UniqueConstraint("tenant_id", "project_id", "provider_resource_key", name="uq_discovered_resources_provider_key"),
        Index("idx_discovered_resources_scope_type", "tenant_id", "project_id", "provider", "resource_type"),
        Index("idx_discovered_resources_service_env", "tenant_id", "service_id", "environment"),
        Index("idx_discovered_resources_status", "tenant_id", "project_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True)
    connection_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), index=True)
    connection_binding_status: Mapped[str] = mapped_column(String(32), default="bound", index=True)
    service_id: Mapped[str] = mapped_column(String(128), index=True)
    environment: Mapped[str] = mapped_column(String(64), index=True)
    provider: Mapped[str] = mapped_column(String(64), index=True)
    provider_account_id: Mapped[str] = mapped_column(String(255), index=True)
    region: Mapped[str] = mapped_column(String(128), index=True)
    provider_resource_id: Mapped[str] = mapped_column(String(768))
    provider_resource_key: Mapped[str] = mapped_column(String(64))
    canonical_resource_id: Mapped[str | None] = mapped_column(String(768), index=True)
    resource_type: Mapped[str] = mapped_column(String(128), index=True)
    display_name: Mapped[str] = mapped_column(String(255), index=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    tags: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    owner: Mapped[str | None] = mapped_column(String(255), index=True)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    health: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    cost: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    evidence: Mapped[list[str]] = mapped_column(JSON, default=list)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class ResourceRelationshipRecord(Base, TimestampMixin):
    __tablename__ = "resource_relationships"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "project_id",
            "source_resource_id",
            "target_resource_id",
            "relationship_type",
            name="uq_resource_relationship_edge",
        ),
        Index("idx_resource_relationships_scope_type", "tenant_id", "project_id", "relationship_type"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True)
    connection_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), index=True)
    connection_binding_status: Mapped[str] = mapped_column(String(32), default="bound", index=True)
    source_resource_id: Mapped[str] = mapped_column(String(128), index=True)
    target_resource_id: Mapped[str] = mapped_column(String(128), index=True)
    relationship_type: Mapped[str] = mapped_column(String(128), index=True)
    source: Mapped[str] = mapped_column(String(128), index=True)
    relationship_source: Mapped[str] = mapped_column(String(32), default="discovered", index=True)
    confidence: Mapped[float] = mapped_column(Numeric(5, 4), default=0.0)
    evidence: Mapped[list[str]] = mapped_column(JSON, default=list)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    owner_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class ServiceResourceMappingRecord(Base, TimestampMixin):
    __tablename__ = "service_resource_mappings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "project_id", "service_id", "environment", "resource_id", name="uq_service_resource_mapping"),
        Index("idx_service_resource_mappings_service", "tenant_id", "project_id", "service_id", "environment"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True)
    service_id: Mapped[str] = mapped_column(String(128), index=True)
    environment: Mapped[str] = mapped_column(String(64), index=True)
    resource_id: Mapped[str] = mapped_column(String(128), index=True)
    owner: Mapped[str] = mapped_column(String(255), index=True)
    mapping_source: Mapped[str] = mapped_column(String(64), default="operator", index=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class ServiceReadinessScoreRecord(Base, TimestampMixin):
    __tablename__ = "service_readiness_scores"
    __table_args__ = (
        UniqueConstraint("tenant_id", "project_id", "service_id", "environment", name="uq_service_readiness_scope"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True)
    service_id: Mapped[str] = mapped_column(String(128), index=True)
    environment: Mapped[str] = mapped_column(String(64), index=True)
    readiness_state: Mapped[str] = mapped_column(String(32), default="DRAFT", index=True)
    overall_score: Mapped[float] = mapped_column(Numeric(5, 4), default=0.0)
    scores: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)


class ServiceOnboardingProfileRecord(Base, TimestampMixin):
    __tablename__ = "service_onboarding_profiles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "project_id", "service_id", "environment", name="uq_service_onboarding_scope"),
        Index("idx_service_onboarding_state", "tenant_id", "project_id", "environment", "onboarding_state"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True)
    service_id: Mapped[str] = mapped_column(String(128), index=True)
    environment: Mapped[str] = mapped_column(String(64), index=True)
    template_id: Mapped[str] = mapped_column(String(128), index=True)
    onboarding_state: Mapped[str] = mapped_column(String(32), default="DRAFT", index=True)
    business_criticality: Mapped[str] = mapped_column(String(32), default="medium", index=True)
    owners: Mapped[list[str]] = mapped_column(JSON, default=list)
    support_groups: Mapped[list[str]] = mapped_column(JSON, default=list)
    connection_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    telemetry: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    slos: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    business_kpis: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    change_sources: Mapped[list[str]] = mapped_column(JSON, default=list)
    knowledge_refs: Mapped[list[str]] = mapped_column(JSON, default=list)
    diagnostic_capabilities: Mapped[list[str]] = mapped_column(JSON, default=list)
    remediation_capabilities: Mapped[list[str]] = mapped_column(JSON, default=list)
    validation_rules: Mapped[list[str]] = mapped_column(JSON, default=list)
    escalation_policies: Mapped[list[str]] = mapped_column(JSON, default=list)
    hitl_policy: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    dependencies: Mapped[list[str]] = mapped_column(JSON, default=list)
    metadata_payload: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)


class CloudAuditEventRecord(Base):
    __tablename__ = "cloud_audit_events"
    __table_args__ = (
        Index("idx_cloud_audit_scope_created", "tenant_id", "project_id", "created_at"),
        Index("idx_cloud_audit_resource_action", "resource_type", "resource_id", "action"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True)
    actor: Mapped[str] = mapped_column(String(255), index=True)
    action: Mapped[str] = mapped_column(String(128), index=True)
    resource_type: Mapped[str] = mapped_column(String(128), index=True)
    resource_id: Mapped[str] = mapped_column(String(255), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class CloudCompiledPlanRecord(Base):
    __tablename__ = "cloud_compiled_plans"
    __table_args__ = (Index("idx_cloud_plan_scope", "tenant_id", "project_id", "service_id", "environment"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True)
    service_id: Mapped[str] = mapped_column(String(128), index=True)
    environment: Mapped[str] = mapped_column(String(64), index=True)
    intent: Mapped[str] = mapped_column(String(512))
    actions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    risk_level: Mapped[str] = mapped_column(String(32), index=True)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=True)
    checksum: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="compiled", index=True)
    compiled_by: Mapped[str] = mapped_column(String(255), index=True)
    compiled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class CloudPlanSimulationRecord(Base):
    __tablename__ = "cloud_plan_simulations"
    __table_args__ = (Index("idx_cloud_simulation_plan", "tenant_id", "plan_id", "simulated_at"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    plan_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    verdict: Mapped[str] = mapped_column(String(32), index=True)
    gates: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    simulated_by: Mapped[str] = mapped_column(String(255), index=True)
    simulated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class CloudPlanApprovalRecord(Base):
    __tablename__ = "cloud_plan_approvals"
    __table_args__ = (UniqueConstraint("tenant_id", "plan_id", "checksum", name="uq_cloud_plan_approval_binding"),)
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    plan_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    checksum: Mapped[str] = mapped_column(String(64), index=True)
    decision: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str] = mapped_column(String(1000))
    actor: Mapped[str] = mapped_column(String(255), index=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class CloudPlanExecutionRecord(Base):
    __tablename__ = "cloud_plan_executions"
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key", name="uq_cloud_execution_lease"),)
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    plan_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    checksum: Mapped[str] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), index=True)
    provider: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True, default="leased")
    action_results: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    validation: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(255), index=True)
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class CloudExecutionPolicyRecord(Base, TimestampMixin):
    __tablename__ = "cloud_execution_policies"
    __table_args__ = (UniqueConstraint("tenant_id", "project_id", "environment", name="uq_cloud_execution_policy_scope"),)
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True)
    environment: Mapped[str] = mapped_column(String(64), index=True)
    allowed_providers: Mapped[list[str]] = mapped_column(JSON, default=list)
    allowed_actions: Mapped[list[str]] = mapped_column(JSON, default=list)
    maximum_risk: Mapped[str] = mapped_column(String(32), default="high")
    require_rollback: Mapped[bool] = mapped_column(Boolean, default=True)
    require_maintenance_window: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    actor: Mapped[str] = mapped_column(String(255), index=True)


class CloudMaintenanceWindowRecord(Base):
    __tablename__ = "cloud_maintenance_windows"
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True)
    environment: Mapped[str] = mapped_column(String(64), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    reason: Mapped[str] = mapped_column(String(512))
    actor: Mapped[str] = mapped_column(String(255), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CloudCredentialSessionRecord(Base):
    __tablename__ = "cloud_credential_sessions"
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    execution_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    provider: Mapped[str] = mapped_column(String(64), index=True)
    credential_ref: Mapped[str] = mapped_column(String(512))
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CloudCompensationRecord(Base):
    __tablename__ = "cloud_compensations"
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    execution_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    resource_id: Mapped[str] = mapped_column(String(128), index=True)
    rollback_action: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), index=True)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class JiraTicketLinkRecord(Base, TimestampMixin):
    """Maps an alert fingerprint to the Jira ticket currently open for it —
    the centralized dedup store: Prometheus/log/email ingestion looks this
    up before deciding whether to create a new Jira issue or comment on an
    existing one, so the same underlying problem never produces duplicate
    tickets."""

    __tablename__ = "jira_ticket_links"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    fingerprint: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    jira_issue_key: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    source: Mapped[str] = mapped_column(String(64), index=True)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class EvaluationRecord(Base, TimestampMixin):
    __tablename__ = "evaluation_records"
    __table_args__ = (Index("idx_evaluation_records_incident_created", "incident_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True, default="default")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    artifact_signature: Mapped[str | None] = mapped_column(String(255), index=True)
    incident_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), index=True)
    recommendation_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), index=True)
    agent: Mapped[str] = mapped_column(String(128), index=True, default="unknown")
    model_provider: Mapped[str | None] = mapped_column(String(64), index=True)
    model_name: Mapped[str | None] = mapped_column(String(128), index=True)
    overall_score: Mapped[float | None] = mapped_column()
    quality_label: Mapped[str | None] = mapped_column(String(32), index=True)
    requires_review: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    report_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    feedback_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)


def install_db_circuit_breaker(engine: AsyncEngine, breaker: CircuitBreaker) -> None:
    """Fail fast on new DB work while the database is down, instead of every
    one of ~21 services independently waiting out its own pool/connect
    timeout on every request. `checkout` gates new connection use before a
    query is attempted; `handle_error` counts only connection failures. Query
    errors (bad SQL, constraint errors, or MySQL resource limits) must not
    masquerade as a database outage and block unrelated requests. No explicit
    success signal is wired up: CircuitBreaker.allow() already self-heals
    after `recovery_seconds` and only reopens if the next attempt(s) fail
    again, so a healthy database naturally keeps the breaker closed.
    """
    sync_engine = engine.sync_engine

    @event.listens_for(sync_engine, "checkout")
    def _on_checkout(dbapi_connection, connection_record, connection_proxy) -> None:
        if not breaker.allow():
            raise CircuitOpenError("database circuit breaker open: refusing new connection checkout")

    @event.listens_for(sync_engine, "handle_error")
    def _on_handle_error(exception_context) -> None:
        if exception_context.is_disconnect:
            breaker.record_failure()


def create_engine(settings: Settings) -> AsyncEngine:
    if settings.database_url.startswith("sqlite"):
        # aiosqlite's pool class doesn't accept pool_size/max_overflow kwargs.
        engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    else:
        engine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout=settings.db_pool_timeout_seconds,
            pool_recycle=settings.db_pool_recycle_seconds,
        )
    install_db_circuit_breaker(engine, CircuitBreaker())
    if isinstance(engine, AsyncEngine):
        SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
        @event.listens_for(engine.sync_engine, "before_cursor_execute")
        def _query_start(_connection, _cursor, statement, _parameters, context, _executemany):
            context._kaiops_query_started = perf_counter()
            context._kaiops_query_operation = str(statement or "query").lstrip().split(None, 1)[0].upper()[:16]

        @event.listens_for(engine.sync_engine, "after_cursor_execute")
        def _query_end(_connection, _cursor, _statement, _parameters, context, _executemany):
            started = getattr(context, "_kaiops_query_started", None)
            if started is not None:
                MYSQL_QUERY_LATENCY.labels(settings.db_database, getattr(context, "_kaiops_query_operation", "QUERY")).observe(perf_counter() - started)
    return engine


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def create_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        if engine.dialect.name == "mysql":
            # Serialize schema migrations across concurrently starting services.
            await connection.execute(text("SELECT GET_LOCK('kaiops_schema_lock', 30)"))
        try:
            await connection.run_sync(Base.metadata.create_all)
            if engine.dialect.name == "mysql":
                has_audit_index = await connection.scalar(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM information_schema.statistics
                        WHERE table_schema = DATABASE()
                          AND table_name = 'audit_logs'
                          AND index_name = 'idx_audit_logs_resource_action_created'
                        """
                    )
                )
                if int(has_audit_index or 0) == 0:
                    await connection.execute(
                        text(
                            "CREATE INDEX idx_audit_logs_resource_action_created ON audit_logs (resource_type, action, created_at)"
                        )
                    )

                # create_all() does not add indexes to existing tables. These
                # indexes keep the live event cursor queries off MySQL's
                # filesort path, which otherwise sorts full JSON-bearing rows.
                live_event_indexes = (
                    ("alerts", "idx_alerts_tenant_updated", "tenant_id, updated_at"),
                    ("alerts", "idx_alerts_tenant_created", "tenant_id, created_at"),
                    ("alerts", "idx_alerts_tenant_env_created", "tenant_id, environment, created_at"),
                    ("actions", "idx_actions_tenant_updated", "tenant_id, updated_at"),
                    ("incident_projections", "idx_incident_projections_tenant_updated", "tenant_id, updated_at"),
                    ("monitoring_connection_health", "idx_monitoring_health_updated", "updated_at"),
                )
                for table_name, index_name, columns in live_event_indexes:
                    has_index = await connection.scalar(
                        text(
                            "SELECT COUNT(*) FROM information_schema.statistics "
                            "WHERE table_schema = DATABASE() "
                            "AND table_name = :table_name AND index_name = :index_name"
                        ),
                        {"table_name": table_name, "index_name": index_name},
                    )
                    if int(has_index or 0) == 0:
                        await connection.execute(text(f"CREATE INDEX {index_name} ON {table_name} ({columns})"))

                # Wave 9 added immutable plan binding and evaluation-retention
                # metadata. Existing Docker volumes are upgraded explicitly:
                # SQLAlchemy's create_all() only creates missing tables and
                # never adds columns or indexes to an existing table.
                wave9_columns = (
                    ("approvals", "plan_id", "CHAR(32) NULL"),
                    ("approvals", "plan_fingerprint", "VARCHAR(71) NULL"),
                    ("approvals", "approval_expires_at", "DATETIME NULL"),
                    ("approvals", "approver_role", "VARCHAR(64) NULL"),
                    ("evaluation_records", "tenant_id", "VARCHAR(128) NOT NULL DEFAULT 'default'"),
                    ("evaluation_records", "expires_at", "DATETIME NULL"),
                    ("evaluation_records", "artifact_signature", "VARCHAR(255) NULL"),
                )
                for table_name, column_name, definition in wave9_columns:
                    has_column = await connection.scalar(
                        text(
                            "SELECT COUNT(*) FROM information_schema.columns "
                            "WHERE table_schema = DATABASE() "
                            "AND table_name = :table_name AND column_name = :column_name"
                        ),
                        {"table_name": table_name, "column_name": column_name},
                    )
                    if int(has_column or 0) == 0:
                        await connection.execute(
                            text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")
                        )

                wave9_indexes = (
                    ("approvals", "ix_approvals_plan_id", "plan_id"),
                    ("approvals", "ix_approvals_plan_fingerprint", "plan_fingerprint"),
                    ("evaluation_records", "ix_evaluation_records_tenant_id", "tenant_id"),
                    ("evaluation_records", "ix_evaluation_records_expires_at", "expires_at"),
                    ("evaluation_records", "ix_evaluation_records_artifact_signature", "artifact_signature"),
                )
                for table_name, index_name, columns in wave9_indexes:
                    has_index = await connection.scalar(
                        text(
                            "SELECT COUNT(*) FROM information_schema.statistics "
                            "WHERE table_schema = DATABASE() "
                            "AND table_name = :table_name AND index_name = :index_name"
                        ),
                        {"table_name": table_name, "index_name": index_name},
                    )
                    if int(has_index or 0) == 0:
                        await connection.execute(text(f"CREATE INDEX {index_name} ON {table_name} ({columns})"))

                knowledge_content_type = await connection.scalar(
                    text(
                        "SELECT DATA_TYPE FROM information_schema.columns "
                        "WHERE table_schema = DATABASE() "
                        "AND table_name = 'knowledge_base' AND column_name = 'content'"
                    )
                )
                if str(knowledge_content_type or "").lower() != "longtext":
                    await connection.execute(
                        text("ALTER TABLE knowledge_base MODIFY COLUMN content LONGTEXT NOT NULL")
                    )

                has_onboarding_tenant = await connection.scalar(
                    text(
                        "SELECT COUNT(*) FROM information_schema.columns "
                        "WHERE table_schema = DATABASE() "
                        "AND table_name = 'onboarding_state' AND column_name = 'tenant_id'"
                    )
                )
                if int(has_onboarding_tenant or 0) == 0:
                    await connection.execute(
                        text(
                            "ALTER TABLE onboarding_state "
                            "ADD COLUMN tenant_id VARCHAR(128) NOT NULL DEFAULT 'default' FIRST, "
                            "DROP PRIMARY KEY, "
                            "ADD PRIMARY KEY (tenant_id, project_name, provider_name)"
                        )
                    )

                has_agent_table = await connection.scalar(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM information_schema.tables
                        WHERE table_schema = DATABASE() AND table_name = 'agent_work_items'
                        """
                    )
                )
                if int(has_agent_table or 0) > 0:
                    has_id_column = await connection.scalar(
                        text(
                            """
                            SELECT COUNT(*)
                            FROM information_schema.columns
                            WHERE table_schema = DATABASE()
                              AND table_name = 'agent_work_items'
                              AND column_name = 'id'
                            """
                        )
                    )
                    if int(has_id_column or 0) == 0:
                        await connection.execute(text("ALTER TABLE agent_work_items ADD COLUMN id CHAR(32) NULL FIRST"))

                    await connection.execute(
                        text("UPDATE agent_work_items SET id = REPLACE(UUID(), '-', '') WHERE id IS NULL OR id = ''")
                    )

                    pk_column = await connection.scalar(
                        text(
                            """
                            SELECT COLUMN_NAME
                            FROM information_schema.key_column_usage
                            WHERE table_schema = DATABASE()
                              AND table_name = 'agent_work_items'
                              AND constraint_name = 'PRIMARY'
                            ORDER BY ORDINAL_POSITION
                            LIMIT 1
                            """
                        )
                    )
                    if str(pk_column or "").strip().lower() != "id":
                        await connection.execute(text("ALTER TABLE agent_work_items DROP PRIMARY KEY, ADD PRIMARY KEY (id)"))
                    await connection.execute(text("ALTER TABLE agent_work_items MODIFY COLUMN id CHAR(32) NOT NULL"))

                    has_incident_index = await connection.scalar(
                        text(
                            """
                            SELECT COUNT(*)
                            FROM information_schema.statistics
                            WHERE table_schema = DATABASE()
                              AND table_name = 'agent_work_items'
                              AND index_name = 'idx_agent_work_items_incident'
                            """
                        )
                    )
                    if int(has_incident_index or 0) == 0:
                        await connection.execute(
                            text("CREATE INDEX idx_agent_work_items_incident ON agent_work_items (incident_id)")
                        )

                    has_agent_seq_index = await connection.scalar(
                        text(
                            """
                            SELECT COUNT(*)
                            FROM information_schema.statistics
                            WHERE table_schema = DATABASE()
                              AND table_name = 'agent_work_items'
                              AND index_name = 'idx_agent_work_items_agent_seq'
                            """
                        )
                    )
                    if int(has_agent_seq_index or 0) == 0:
                        await connection.execute(
                            text("CREATE INDEX idx_agent_work_items_agent_seq ON agent_work_items (agent_name, sequence)")
                        )

                has_projection_table = await connection.scalar(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM information_schema.tables
                        WHERE table_schema = DATABASE() AND table_name = 'incident_projections'
                        """
                    )
                )
                if int(has_projection_table or 0) > 0:
                    has_recommendation_column = await connection.scalar(
                        text(
                            """
                            SELECT COUNT(*)
                            FROM information_schema.columns
                            WHERE table_schema = DATABASE()
                              AND table_name = 'incident_projections'
                              AND column_name = 'recommendation_id'
                            """
                        )
                    )
                    if int(has_recommendation_column or 0) == 0:
                        await connection.execute(
                            text("ALTER TABLE incident_projections ADD COLUMN recommendation_id CHAR(32) NULL")
                        )

                    has_flow_column = await connection.scalar(
                        text(
                            """
                            SELECT COUNT(*)
                            FROM information_schema.columns
                            WHERE table_schema = DATABASE()
                              AND table_name = 'incident_projections'
                              AND column_name = 'flow_id'
                            """
                        )
                    )
                    if int(has_flow_column or 0) == 0:
                        await connection.execute(
                            text("ALTER TABLE incident_projections ADD COLUMN flow_id VARCHAR(128) NULL")
                        )

                    has_recommendation_index = await connection.scalar(
                        text(
                            """
                            SELECT COUNT(*)
                            FROM information_schema.statistics
                            WHERE table_schema = DATABASE()
                              AND table_name = 'incident_projections'
                              AND index_name = 'idx_incident_projections_recommendation'
                            """
                        )
                    )
                    if int(has_recommendation_index or 0) == 0:
                        await connection.execute(
                            text("CREATE INDEX idx_incident_projections_recommendation ON incident_projections (recommendation_id)")
                        )

                    has_flow_index = await connection.scalar(
                        text(
                            """
                            SELECT COUNT(*)
                            FROM information_schema.statistics
                            WHERE table_schema = DATABASE()
                              AND table_name = 'incident_projections'
                              AND index_name = 'idx_incident_projections_flow'
                            """
                        )
                    )
                    if int(has_flow_index or 0) == 0:
                        await connection.execute(
                            text("CREATE INDEX idx_incident_projections_flow ON incident_projections (flow_id)")
                        )

                    has_document_available_column = await connection.scalar(
                        text(
                            """
                            SELECT COUNT(*)
                            FROM information_schema.columns
                            WHERE table_schema = DATABASE()
                              AND table_name = 'incident_projections'
                              AND column_name = 'document_available'
                            """
                        )
                    )
                    if int(has_document_available_column or 0) == 0:
                        await connection.execute(
                            text("ALTER TABLE incident_projections ADD COLUMN document_available BOOLEAN NULL")
                        )
        finally:
            if engine.dialect.name == "mysql":
                await connection.execute(text("SELECT RELEASE_LOCK('kaiops_schema_lock')"))
