from __future__ import annotations

import asyncio
from time import perf_counter

from common.config import get_settings
from common.logging import get_logger
from common.models import ApplicationRegistration, MonitoringAuditEvent, MonitoringValidationResult, PrometheusUpdateResult
from common.monitoring_onboarding import application_from_row, validate_prometheus_application
from common.rabbitmq import RabbitMQConsumer, consume_forever as consume_rabbitmq_forever
from common.repository import IncidentRepository
from common.service import create_app
from common.telemetry import ONBOARDING_FAILED, ONBOARDING_SUCCESS, VALIDATION_DURATION
from common.topics import APPLICATION_PROMETHEUS_UPDATED, APPLICATION_VALIDATION_COMPLETED
from fastapi import FastAPI

settings = get_settings()
settings.service_name = "validation-agent"
logger = get_logger(__name__)
tasks: list[asyncio.Task] = []


async def _mark_application_failed(app: FastAPI, application: ApplicationRegistration, *, error: Exception) -> None:
    """Best-effort: records the failure so the onboarding stepper can show it
    instead of freezing on the last successful stage. Never raises -- the
    caller re-raises the original error regardless, which is what drives
    consume_forever's existing retry/DLQ handling."""
    try:
        session_factory = getattr(app.state, "session_factory", None)
        if session_factory is None:
            return
        async with session_factory() as session:
            repo = IncidentRepository(session)
            await repo.update_application_status(
                application.id,
                status="failed",
                payload={"validation": {"error": str(error), "failed": True}},
            )
            await repo.save_monitoring_audit(
                MonitoringAuditEvent(
                    application_id=application.id,
                    tenant_id=application.tenant_id,
                    event_type=f"{APPLICATION_VALIDATION_COMPLETED}.failed",
                    actor="system",
                    agent="validation-agent",
                    decision="failed",
                    output={"error": str(error)},
                )
            )
            await session.commit()
    except Exception:
        logger.exception("failed to record onboarding failure state", extra={"application_id": str(application.id)})


async def startup(app: FastAPI) -> None:
    async def handle(payload: dict) -> None:
        started = perf_counter()
        update = PrometheusUpdateResult.model_validate(payload)
        session_factory = getattr(app.state, "session_factory", None)
        if session_factory is None:
            raise RuntimeError("session factory unavailable")
        application: ApplicationRegistration | None = None
        try:
            async with session_factory() as session:
                repo = IncidentRepository(session)
                row = await repo.get_application(update.application_id)
                if row is None:
                    logger.warning("validation skipped; application missing", extra={"application_id": str(update.application_id)})
                    return
                application = application_from_row(row)
                result = await validate_prometheus_application(settings.prometheus_url, application)
                await repo.save_validation_result(result)
                await repo.update_application_status(application.id, status=str(result.status), payload={"validation": result.model_dump(mode="json")})
                await repo.save_monitoring_audit(
                    MonitoringAuditEvent(
                        application_id=application.id,
                        tenant_id=application.tenant_id,
                        event_type=APPLICATION_VALIDATION_COMPLETED,
                        actor="system",
                        agent="validation-agent",
                        decision="validated" if result.target_up else "degraded",
                        execution_time_ms=(perf_counter() - started) * 1000.0,
                        input=update.model_dump(mode="json"),
                        output=result.model_dump(mode="json"),
                    )
                )
                await session.commit()
            await app.state.producer.publish(APPLICATION_VALIDATION_COMPLETED, result.model_dump(mode="json"), key=str(update.application_id))
            VALIDATION_DURATION.labels(settings.service_name, "prometheus").observe(max(0.0, perf_counter() - started))
            ONBOARDING_SUCCESS.labels(settings.service_name, "validation").inc()
        except Exception as exc:
            ONBOARDING_FAILED.labels(settings.service_name, "validation").inc()
            logger.error(
                "validation stage failed",
                extra={"application_id": str(update.application_id), "error": str(exc)},
            )
            if application is not None:
                await _mark_application_failed(app, application, error=exc)
            raise

    consumer = RabbitMQConsumer(settings, APPLICATION_PROMETHEUS_UPDATED)
    tasks.append(asyncio.create_task(consume_rabbitmq_forever(consumer, handle), name="monitoring-validation-consumer"))


async def shutdown(_: FastAPI) -> None:
    for task in tasks:
        task.cancel()


app = create_app(title="KaiOps Monitoring Validation Agent", settings=settings, startup=startup, shutdown=shutdown)