from __future__ import annotations

import asyncio
from time import perf_counter

from common.config import get_settings
from common.logging import get_logger
from common.models import ApplicationDiscoveryResult, MonitoringAuditEvent
from common.monitoring_onboarding import ValidationAgent
from common.rabbitmq import RabbitMQConsumer, consume_forever as consume_rabbitmq_forever
from common.repository import IncidentRepository
from common.service import create_app
from common.telemetry import ONBOARDING_FAILED, ONBOARDING_SUCCESS, VALIDATION_DURATION
from common.topics import APPLICATION_DISCOVERY_COMPLETED, APPLICATION_METRICS_VALIDATED
from fastapi import FastAPI

settings = get_settings()
settings.service_name = "metrics-validation-agent"
logger = get_logger(__name__)
agent = ValidationAgent()
tasks: list[asyncio.Task] = []


async def _mark_application_failed(app: FastAPI, discovery: ApplicationDiscoveryResult, *, error: Exception) -> None:
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
                discovery.application_id,
                status="failed",
                payload={"metrics_validation": {"error": str(error), "failed": True}},
            )
            await repo.save_monitoring_audit(
                MonitoringAuditEvent(
                    application_id=discovery.application_id,
                    tenant_id=discovery.tenant_id,
                    event_type=f"{APPLICATION_METRICS_VALIDATED}.failed",
                    actor="system",
                    agent="metrics-validation-agent",
                    decision="failed",
                    output={"error": str(error)},
                )
            )
            await session.commit()
    except Exception:
        logger.exception("failed to record onboarding failure state", extra={"application_id": str(discovery.application_id)})


async def startup(app: FastAPI) -> None:
    async def handle(payload: dict) -> None:
        started = perf_counter()
        discovery = ApplicationDiscoveryResult.model_validate(payload)
        try:
            result = await agent.run(discovery)
            session_factory = getattr(app.state, "session_factory", None)
            if session_factory is not None:
                async with session_factory() as session:
                    repo = IncidentRepository(session)
                    await repo.save_monitoring_profile(result)
                    await repo.update_application_status(discovery.application_id, status=str(result.status), payload={"metrics_validation": result.model_dump(mode="json")})
                    await repo.save_monitoring_audit(
                        MonitoringAuditEvent(
                            application_id=discovery.application_id,
                            tenant_id=discovery.tenant_id,
                            event_type=APPLICATION_METRICS_VALIDATED,
                            actor="system",
                            agent="metrics-validation-agent",
                            decision="validated" if result.metrics_available else "degraded",
                            execution_time_ms=(perf_counter() - started) * 1000.0,
                            input=discovery.model_dump(mode="json"),
                            output=result.model_dump(mode="json"),
                        )
                    )
                    await session.commit()
            await app.state.producer.publish(APPLICATION_METRICS_VALIDATED, result.model_dump(mode="json"), key=str(discovery.application_id))
            VALIDATION_DURATION.labels(settings.service_name, "prometheus").observe(max(0.0, perf_counter() - started))
            ONBOARDING_SUCCESS.labels(settings.service_name, "metrics_validation").inc()
        except Exception as exc:
            ONBOARDING_FAILED.labels(settings.service_name, "metrics_validation").inc()
            logger.error(
                "metrics validation stage failed",
                extra={"application_id": str(discovery.application_id), "error": str(exc)},
            )
            await _mark_application_failed(app, discovery, error=exc)
            raise

    consumer = RabbitMQConsumer(settings, APPLICATION_DISCOVERY_COMPLETED)
    tasks.append(asyncio.create_task(consume_rabbitmq_forever(consumer, handle), name="metrics-validation-consumer"))


async def shutdown(_: FastAPI) -> None:
    for task in tasks:
        task.cancel()


app = create_app(title="KaiOps Metrics Validation Agent", settings=settings, startup=startup, shutdown=shutdown)