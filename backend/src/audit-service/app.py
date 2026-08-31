from __future__ import annotations

import asyncio
from time import perf_counter
from uuid import UUID

from common.config import get_settings
from common.logging import get_logger
from common.models import MonitoringAuditEvent
from common.rabbitmq import RabbitMQConsumer, consume_forever as consume_rabbitmq_forever
from common.repository import IncidentRepository
from common.service import create_app
from common.topics import (
    APPLICATION_DASHBOARD_CREATED,
    APPLICATION_DISCOVERY_COMPLETED,
    APPLICATION_METRICS_VALIDATED,
    APPLICATION_ONBOARD_REQUESTED,
    APPLICATION_PROMETHEUS_UPDATED,
    APPLICATION_RULES_GENERATED,
    APPLICATION_VALIDATION_COMPLETED,
)
from fastapi import FastAPI

settings = get_settings()
settings.service_name = "audit-service"
logger = get_logger(__name__)
tasks: list[asyncio.Task] = []


def _resolve_identity(payload: dict) -> tuple[UUID | None, str]:
    application_id = payload.get("application_id") or payload.get("id")
    if application_id:
        try:
            return UUID(str(application_id)), str(payload.get("tenant_id") or "default")
        except ValueError:
            return None, str(payload.get("tenant_id") or "default")
    return None, str(payload.get("tenant_id") or "default")


async def startup(app: FastAPI) -> None:
    async def handle_factory(event_type: str):
        async def handle(payload: dict) -> None:
            started = perf_counter()
            application_id, tenant_id = _resolve_identity(payload)
            if application_id is None:
                return
            session_factory = getattr(app.state, "session_factory", None)
            if session_factory is None:
                return
            async with session_factory() as session:
                repo = IncidentRepository(session)
                await repo.save_monitoring_audit(
                    MonitoringAuditEvent(
                        application_id=application_id,
                        tenant_id=tenant_id,
                        event_type=event_type,
                        actor="system",
                        agent="audit-service",
                        decision="recorded",
                        execution_time_ms=(perf_counter() - started) * 1000.0,
                        input=payload,
                        output={"stored": True},
                    )
                )
                await session.commit()
        return handle

    for topic in [
        APPLICATION_ONBOARD_REQUESTED,
        APPLICATION_DISCOVERY_COMPLETED,
        APPLICATION_METRICS_VALIDATED,
        APPLICATION_RULES_GENERATED,
        APPLICATION_PROMETHEUS_UPDATED,
        APPLICATION_VALIDATION_COMPLETED,
        APPLICATION_DASHBOARD_CREATED,
    ]:
        consumer = RabbitMQConsumer(settings, topic)
        tasks.append(asyncio.create_task(consume_rabbitmq_forever(consumer, await handle_factory(topic)), name=f"audit-{topic}"))


async def shutdown(_: FastAPI) -> None:
    for task in tasks:
        task.cancel()


app = create_app(title="KaiOps Audit Service", settings=settings, startup=startup, shutdown=shutdown)