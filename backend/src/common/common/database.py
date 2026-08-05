from __future__ import annotations

from datetime import datetime
from time import perf_counter
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Index, JSON, BigInteger, Boolean, DateTime, ForeignKey, Integer, MetaData, String, Text, Uuid, event, text
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
    __table_args__ = (Index("idx_alerts_created_at", "created_at"),)

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


class ApprovalRecord(Base, TimestampMixin):
    __tablename__ = "approvals"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True, default="default")
    incident_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    recommendation_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    decision: Mapped[str] = mapped_column(String(32), index=True)
    approver: Mapped[str | None] = mapped_column(String(255))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class ApprovalCapacityRecord(Base, TimestampMixin):
    __tablename__ = "approval_capacity"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True, default="default")
    username: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    resource_names: Mapped[list[str]] = mapped_column(JSON, default=list)
    weekly_hours: Mapped[int] = mapped_column(Integer, default=0)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    working_days: Mapped[list[int]] = mapped_column(JSON, default=lambda: [0, 1, 2, 3, 4])
    work_start: Mapped[str] = mapped_column(String(5), default="09:00")
    work_end: Mapped[str] = mapped_column(String(5), default="17:00")
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class ApprovalAssignmentRecord(Base, TimestampMixin):
    __tablename__ = "approval_assignments"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True, default="default")
    incident_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    assignee: Mapped[str] = mapped_column(String(255), index=True)
    service: Mapped[str] = mapped_column(String(128), index=True)
    estimated_hours: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="assigned", index=True)
    assignment_reason: Mapped[str] = mapped_column(Text)


class ActionRecord(Base, TimestampMixin):
    __tablename__ = "actions"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True, default="default")
    incident_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    action_type: Mapped[str] = mapped_column(String(128), index=True)
    target: Mapped[str] = mapped_column(String(255), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class RcaReportRecord(Base, TimestampMixin):
    __tablename__ = "rca_reports"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True, default="default")
    incident_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    root_cause: Mapped[str] = mapped_column(String(255))
    impact: Mapped[str] = mapped_column(String(255))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class KnowledgeBaseRecord(Base, TimestampMixin):
    __tablename__ = "knowledge_base"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True, default="default")
    service: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
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


class OnboardingStateRecord(Base, TimestampMixin):
    __tablename__ = "onboarding_state"

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
    query is attempted; `handle_error` counts real DB failures. No explicit
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
