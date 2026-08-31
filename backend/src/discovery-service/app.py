from __future__ import annotations

import asyncio
from time import perf_counter

from common.config import get_settings
from common.logging import get_logger
from common.models import ApplicationRegistration, MonitoringAuditEvent
from common.monitoring_onboarding import DiscoveryAgent
from common.rabbitmq import RabbitMQConsumer, consume_forever as consume_rabbitmq_forever
from common.repository import IncidentRepository
from common.service import create_app
from common.telemetry import APPLICATION_DISCOVERY_DURATION, ONBOARDING_FAILED, ONBOARDING_SUCCESS
from common.topics import APPLICATION_DISCOVERY_COMPLETED, APPLICATION_ONBOARD_REQUESTED
from fastapi import FastAPI

settings = get_settings()
settings.service_name = "discovery-service"
logger = get_logger(__name__)
agent = DiscoveryAgent()
tasks: list[asyncio.Task] = []


async def _mark_application_failed(app: FastAPI, application: ApplicationRegistration, *, stage: str, error: Exception) -> None:
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
                application.id, status="failed", payload={stage: {"error": str(error), "failed": True}}
            )
            await repo.save_monitoring_audit(
                MonitoringAuditEvent(
                    application_id=application.id,
                    tenant_id=application.tenant_id,
                    event_type=f"{APPLICATION_DISCOVERY_COMPLETED}.failed",
                    actor="system",
                    agent="discovery-agent",
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
        application = ApplicationRegistration.model_validate(payload)
        try:
            result = await agent.run(application)
            session_factory = getattr(app.state, "session_factory", None)
            if session_factory is not None:
                async with session_factory() as session:
                    repo = IncidentRepository(session)
                    await repo.update_application_status(application.id, status=str(result.status), payload={"discovery": result.model_dump(mode="json")})
                    await repo.save_monitoring_audit(
                        MonitoringAuditEvent(
                            application_id=application.id,
                            tenant_id=application.tenant_id,
                            event_type=APPLICATION_DISCOVERY_COMPLETED,
                            actor="system",
                            agent="discovery-agent",
                            decision="discovered",
                            execution_time_ms=(perf_counter() - started) * 1000.0,
                            input=application.model_dump(mode="json"),
                            output=result.model_dump(mode="json"),
                        )
                    )
                    await session.commit()
            await app.state.producer.publish(APPLICATION_DISCOVERY_COMPLETED, result.model_dump(mode="json"), key=str(application.id))
            APPLICATION_DISCOVERY_DURATION.labels(settings.service_name, "prometheus").observe(max(0.0, perf_counter() - started))
            ONBOARDING_SUCCESS.labels(settings.service_name, "discovery").inc()
        except Exception as exc:
            ONBOARDING_FAILED.labels(settings.service_name, "discovery").inc()
            logger.error(
                "discovery stage failed", extra={"application_id": str(application.id), "error": str(exc)}
            )
            await _mark_application_failed(app, application, stage="discovery", error=exc)
            raise

    consumer = RabbitMQConsumer(settings, APPLICATION_ONBOARD_REQUESTED)
    tasks.append(asyncio.create_task(consume_rabbitmq_forever(consumer, handle), name="discovery-consumer"))


async def shutdown(_: FastAPI) -> None:
    for task in tasks:
        task.cancel()


app = create_app(title="KaiOps Discovery Service", settings=settings, startup=startup, shutdown=shutdown)