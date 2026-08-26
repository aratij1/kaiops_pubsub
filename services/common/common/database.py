from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Index, JSON, BigInteger, Boolean, DateTime, ForeignKey, Integer, MetaData, String, Text, Uuid, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from common.config import Settings
from common.models import utc_now

metadata = MetaData()


class Base(DeclarativeBase):
    metadata = metadata


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class AlertRecord(Base, TimestampMixin):
    __tablename__ = "alerts"
    __table_args__ = (Index("idx_alerts_created_at", "created_at"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
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
    incident_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    recommendation_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    decision: Mapped[str] = mapped_column(String(32), index=True)
    approver: Mapped[str | None] = mapped_column(String(255))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class ActionRecord(Base, TimestampMixin):
    __tablename__ = "actions"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    incident_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    action_type: Mapped[str] = mapped_column(String(128), index=True)
    target: Mapped[str] = mapped_column(String(255), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class RcaReportRecord(Base, TimestampMixin):
    __tablename__ = "rca_reports"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    incident_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    root_cause: Mapped[str] = mapped_column(String(255))
    impact: Mapped[str] = mapped_column(String(255))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class KnowledgeBaseRecord(Base, TimestampMixin):
    __tablename__ = "knowledge_base"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    service: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    embedding_ref: Mapped[str | None] = mapped_column(String(255))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class AuditLogRecord(Base, TimestampMixin):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("idx_audit_logs_created_at", "created_at"),
        Index("idx_audit_logs_resource_action_created", "resource_type", "action", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    actor: Mapped[str] = mapped_column(String(255), index=True)
    action: Mapped[str] = mapped_column(String(255), index=True)
    resource_type: Mapped[str] = mapped_column(String(128), index=True)
    resource_id: Mapped[str] = mapped_column(String(128), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


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


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(settings.database_url, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def create_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        if engine.dialect.name == "postgresql":
            await connection.execute(text("SELECT pg_advisory_lock(742031991)"))
        elif engine.dialect.name == "mysql":
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
        finally:
            if engine.dialect.name == "postgresql":
                await connection.execute(text("SELECT pg_advisory_unlock(742031991)"))
            elif engine.dialect.name == "mysql":
                await connection.execute(text("SELECT RELEASE_LOCK('kaiops_schema_lock')"))
