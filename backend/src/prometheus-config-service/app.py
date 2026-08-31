from __future__ import annotations

import asyncio
from time import perf_counter

from common.config import get_settings
from common.logging import get_logger
from common.models import ApplicationRegistration, MonitoringAuditEvent, PrometheusUpdateResult, RulesGeneratedResult
from common.monitoring_onboarding import application_from_row, reload_prometheus, write_prometheus_artifacts
from common.rabbitmq import RabbitMQConsumer, consume_forever as consume_rabbitmq_forever
from common.repository import IncidentRepository
from common.service import create_app
from common.telemetry import ONBOARDING_FAILED, ONBOARDING_SUCCESS
from common.topics import APPLICATION_PROMETHEUS_UPDATED, APPLICATION_RULES_GENERATED
from fastapi import FastAPI

settings = get_settings()
settings.service_name = "prometheus-config-service"
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
                payload={"prometheus_update": {"error": str(error), "failed": True}},
            )
            await repo.save_monitoring_audit(
                MonitoringAuditEvent(
                    application_id=application.id,
                    tenant_id=application.tenant_id,
                    event_type=f"{APPLICATION_PROMETHEUS_UPDATED}.failed",
                    actor="system",
                    agent="prometheus-config-service",
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
        result = RulesGeneratedResult.model_validate(payload)
        session_factory = getattr(app.state, "session_factory", None)
        if session_factory is None:
            raise RuntimeError("session factory unavailable")
        application: ApplicationRegistration | None = None
        try:
            async with session_factory() as session:
                repo = IncidentRepository(session)
                row = await repo.get_application(result.application_id)
                if row is None:
                    logger.warning("prometheus update skipped; application missing", extra={"application_id": str(result.application_id)})
                    return
                application = application_from_row(row)
                files, contents = write_prometheus_artifacts(application, result)
                provider_response = await reload_prometheus(settings.prometheus_url)
                provider_response.update(contents)
                update = PrometheusUpdateResult(
                    application_id=application.id,
                    tenant_id=application.tenant_id,
                    files=files,
                    reload_ok=bool(provider_response.get("reload_ok", False)),
                    provider_response=provider_response,
                )
                await repo.save_prometheus_update(update)
                await repo.update_application_status(application.id, status=str(update.status), payload={"prometheus_update": update.model_dump(mode="json")})
                await repo.save_monitoring_audit(
                    MonitoringAuditEvent(
                        application_id=application.id,
                        tenant_id=application.tenant_id,
                        event_type=APPLICATION_PROMETHEUS_UPDATED,
                        actor="system",
                        agent="prometheus-config-service",
                        decision="reloaded" if update.reload_ok else "reload_failed",
                        execution_time_ms=(perf_counter() - started) * 1000.0,
                        input=result.model_dump(mode="json"),
                        output=update.model_dump(mode="json"),
                    )
                )
                await session.commit()
            await app.state.producer.publish(APPLICATION_PROMETHEUS_UPDATED, update.model_dump(mode="json"), key=str(result.application_id))
            ONBOARDING_SUCCESS.labels(settings.service_name, "prometheus_update").inc()
        except Exception as exc:
            ONBOARDING_FAILED.labels(settings.service_name, "prometheus_update").inc()
            logger.error(
                "prometheus update stage failed",
                extra={"application_id": str(result.application_id), "error": str(exc)},
            )
            if application is not None:
                await _mark_application_failed(app, application, error=exc)
            raise

    consumer = RabbitMQConsumer(settings, APPLICATION_RULES_GENERATED)
    tasks.append(asyncio.create_task(consume_rabbitmq_forever(consumer, handle), name="prometheus-config-consumer"))


async def shutdown(_: FastAPI) -> None:
    for task in tasks:
        task.cancel()


app = create_app(title="KaiOps Prometheus Configuration Service", settings=settings, startup=startup, shutdown=shutdown)