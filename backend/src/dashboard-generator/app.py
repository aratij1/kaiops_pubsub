from __future__ import annotations

import asyncio
from time import perf_counter

from common.config import get_settings
from common.logging import get_logger
from common.models import ApplicationRegistration, MonitoringAuditEvent, MonitoringValidationResult
from common.monitoring_onboarding import application_from_row, build_dashboard
from common.rabbitmq import RabbitMQConsumer, consume_forever as consume_rabbitmq_forever
from common.repository import IncidentRepository
from common.service import create_app
from common.telemetry import DASHBOARD_GENERATION_DURATION, ONBOARDING_SUCCESS
from common.topics import APPLICATION_DASHBOARD_CREATED, APPLICATION_VALIDATION_COMPLETED
from fastapi import FastAPI

settings = get_settings()
settings.service_name = "dashboard-generator"
logger = get_logger(__name__)
tasks: list[asyncio.Task] = []


async def startup(app: FastAPI) -> None:
    async def handle(payload: dict) -> None:
        started = perf_counter()
        validation = MonitoringValidationResult.model_validate(payload)
        session_factory = getattr(app.state, "session_factory", None)
        if session_factory is None:
            raise RuntimeError("session factory unavailable")
        async with session_factory() as session:
            repo = IncidentRepository(session)
            row = await repo.get_application(validation.application_id)
            if row is None:
                logger.warning("dashboard generation skipped; application missing", extra={"application_id": str(validation.application_id)})
                return
            application = application_from_row(row)
            dashboard = build_dashboard(application, validation)
            await repo.save_dashboard_result(dashboard)
            await repo.update_application_status(application.id, status=str(dashboard.status), payload={"dashboard": dashboard.model_dump(mode="json")})
            await repo.save_monitoring_audit(
                MonitoringAuditEvent(
                    application_id=application.id,
                    tenant_id=application.tenant_id,
                    event_type=APPLICATION_DASHBOARD_CREATED,
                    actor="system",
                    agent="dashboard-generator",
                    decision="generated",
                    execution_time_ms=(perf_counter() - started) * 1000.0,
                    input=validation.model_dump(mode="json"),
                    output=dashboard.model_dump(mode="json"),
                )
            )
            await session.commit()
        await app.state.producer.publish(APPLICATION_DASHBOARD_CREATED, dashboard.model_dump(mode="json"), key=str(validation.application_id))
        DASHBOARD_GENERATION_DURATION.labels(settings.service_name, "grafana").observe(max(0.0, perf_counter() - started))
        ONBOARDING_SUCCESS.labels(settings.service_name, "dashboard").inc()

    consumer = RabbitMQConsumer(settings, APPLICATION_VALIDATION_COMPLETED)
    tasks.append(asyncio.create_task(consume_rabbitmq_forever(consumer, handle), name="dashboard-generator-consumer"))


async def shutdown(_: FastAPI) -> None:
    for task in tasks:
        task.cancel()


app = create_app(title="KaiOps Dashboard Generator", settings=settings, startup=startup, shutdown=shutdown)