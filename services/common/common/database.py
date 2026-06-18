from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, DateTime, MetaData, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
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

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
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

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    service: Mapped[str] = mapped_column(String(128), index=True)
    environment: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(255))
    ticket_id: Mapped[str | None] = mapped_column(String(128), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class ApprovalRecord(Base, TimestampMixin):
    __tablename__ = "approvals"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    incident_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), index=True)
    recommendation_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), index=True)
    decision: Mapped[str] = mapped_column(String(32), index=True)
    approver: Mapped[str | None] = mapped_column(String(255))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class ActionRecord(Base, TimestampMixin):
    __tablename__ = "actions"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    incident_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), index=True)
    action_type: Mapped[str] = mapped_column(String(128), index=True)
    target: Mapped[str] = mapped_column(String(255), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class RcaReportRecord(Base, TimestampMixin):
    __tablename__ = "rca_reports"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    incident_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), index=True)
    root_cause: Mapped[str] = mapped_column(String(255))
    impact: Mapped[str] = mapped_column(String(255))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class KnowledgeBaseRecord(Base, TimestampMixin):
    __tablename__ = "knowledge_base"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    service: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    embedding_ref: Mapped[str | None] = mapped_column(String(255))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class AuditLogRecord(Base, TimestampMixin):
    __tablename__ = "audit_logs"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    actor: Mapped[str] = mapped_column(String(255), index=True)
    action: Mapped[str] = mapped_column(String(255), index=True)
    resource_type: Mapped[str] = mapped_column(String(128), index=True)
    resource_id: Mapped[str] = mapped_column(String(128), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(settings.database_url, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def create_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        if engine.dialect.name == "postgresql":
            await connection.execute(text("SELECT pg_advisory_lock(742031991)"))
        try:
            await connection.run_sync(Base.metadata.create_all)
        finally:
            if engine.dialect.name == "postgresql":
                await connection.execute(text("SELECT pg_advisory_unlock(742031991)"))
