from __future__ import annotations

import asyncio
from time import perf_counter

from common.config import get_settings
from common.logging import get_logger
from common.models import ApplicationRegistration, MetricsValidationResult, MonitoringAuditEvent
from common.monitoring_onboarding import RuleGenerationAgent, application_from_row
from common.rabbitmq import RabbitMQConsumer, consume_forever as consume_rabbitmq_forever
from common.repository import IncidentRepository
from common.service import create_app
from common.telemetry import ONBOARDING_SUCCESS, RULE_GENERATION_DURATION
from common.topics import APPLICATION_METRICS_VALIDATED, APPLICATION_RULES_GENERATED
from fastapi import FastAPI

settings = get_settings()
settings.service_name = "rule-generation-agent"
logger = get_logger(__name__)
agent = RuleGenerationAgent()
tasks: list[asyncio.Task] = []


async def startup(app: FastAPI) -> None:
    async def handle(payload: dict) -> None:
        started = perf_counter()
        validation = MetricsValidationResult.model_validate(payload)
        session_factory = getattr(app.state, "session_factory", None)
        if session_factory is None:
            raise RuntimeError("session factory unavailable")
        async with session_factory() as session:
            repo = IncidentRepository(session)
            row = await repo.get_application(validation.application_id)
            if row is None:
                logger.warning("rule generation skipped; application missing", extra={"application_id": str(validation.application_id)})
                return
            application = application_from_row(row)
            discovery_payload = ((row.get("payload") or {}).get("discovery") or {}) if isinstance(row.get("payload"), dict) else {}
            from common.models import ApplicationDiscoveryResult

            discovery = ApplicationDiscoveryResult.model_validate(discovery_payload or {
                "application_id": str(validation.application_id),
                "tenant_id": application.tenant_id,
                "name": application.name,
                "environment": application.environment,
                "namespace": application.namespace,
                "technology": application.technology,
                "metrics_endpoint": application.metrics_endpoint,
                "labels": application.labels,
            })
            result = await agent.run(application, discovery, validation)
            await repo.replace_rules(result)
            await repo.update_application_status(application.id, status=str(result.status), payload={"rules_generation": result.model_dump(mode="json")})
            await repo.save_monitoring_audit(
                MonitoringAuditEvent(
                    application_id=application.id,
                    tenant_id=application.tenant_id,
                    event_type=APPLICATION_RULES_GENERATED,
                    actor="system",
                    agent="rule-generation-agent",
                    decision=str(result.governance.get("decision") or "approved"),
                    execution_time_ms=(perf_counter() - started) * 1000.0,
                    input=validation.model_dump(mode="json"),
                    output=result.model_dump(mode="json"),
                )
            )
            await session.commit()
        await app.state.producer.publish(APPLICATION_RULES_GENERATED, result.model_dump(mode="json"), key=str(validation.application_id))
        RULE_GENERATION_DURATION.labels(settings.service_name, "prometheus").observe(max(0.0, perf_counter() - started))
        ONBOARDING_SUCCESS.labels(settings.service_name, "rules_generation").inc()

    consumer = RabbitMQConsumer(settings, APPLICATION_METRICS_VALIDATED)
    tasks.append(asyncio.create_task(consume_rabbitmq_forever(consumer, handle), name="rule-generation-consumer"))


async def shutdown(_: FastAPI) -> None:
    for task in tasks:
        task.cancel()


app = create_app(title="KaiOps Rule Generation Agent", settings=settings, startup=startup, shutdown=shutdown)