from __future__ import annotations

from contextlib import asynccontextmanager
from time import perf_counter
from uuid import UUID

from common.config import get_settings
from common.logging import get_logger
from common.models import ApplicationRegistration, ApplicationStatus, MonitoringAuditEvent
from common.monitoring_onboarding import application_from_row
from common.repository import IncidentRepository
from common.service import create_app
from common.telemetry import APPLICATIONS_ONBOARDED, ONBOARDING_FAILED, ONBOARDING_SUCCESS
from common.topics import APPLICATION_ONBOARD_REQUESTED
from fastapi import Body, FastAPI, HTTPException

settings = get_settings()
settings.service_name = "application-onboarding"
logger = get_logger(__name__)


async def startup(_: FastAPI) -> None:
    return None


async def shutdown(_: FastAPI) -> None:
    return None


app = create_app(title="KaiOps Application Onboarding Service", settings=settings, startup=startup, shutdown=shutdown)


@asynccontextmanager
async def _repo() -> IncidentRepository:
    session_factory = getattr(app.state, "session_factory", None)
    if session_factory is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    session = session_factory()
    try:
        yield IncidentRepository(session)
        await session.commit()
    finally:
        await session.close()


async def _write_audit(repo: IncidentRepository, application: ApplicationRegistration, *, event_type: str, decision: str, actor: str, started: float, output: dict) -> None:
    await repo.save_monitoring_audit(
        MonitoringAuditEvent(
            application_id=application.id,
            tenant_id=application.tenant_id,
            event_type=event_type,
            actor=actor,
            agent="onboarding-agent",
            decision=decision,
            execution_time_ms=(perf_counter() - started) * 1000.0,
            input=application.model_dump(mode="json"),
            output=output,
        )
    )


@app.post("/applications")
async def create_application(payload: dict = Body(...)) -> dict:
    started = perf_counter()
    application = ApplicationRegistration.model_validate(payload)
    application.status = ApplicationStatus.REGISTERED
    async with _repo() as repo:
        await repo.save_application(application)
        await repo.save_monitoring_audit(
            MonitoringAuditEvent(
                application_id=application.id,
                tenant_id=application.tenant_id,
                event_type=APPLICATION_ONBOARD_REQUESTED,
                actor="user",
                agent="onboarding-agent",
                decision="published",
                execution_time_ms=(perf_counter() - started) * 1000.0,
                input=application.model_dump(mode="json"),
                output={"status": "registered"},
            )
        )
        try:
            await app.state.producer.publish(APPLICATION_ONBOARD_REQUESTED, application.model_dump(mode="json"), key=str(application.id))
            APPLICATIONS_ONBOARDED.labels(application.tenant_id, application.environment, "registered").inc()
            ONBOARDING_SUCCESS.labels(settings.service_name, "register").inc()
        except Exception:
            logger.exception("failed to publish onboarding request", extra={"application_id": str(application.id)})
            ONBOARDING_FAILED.labels(settings.service_name, "register").inc()
            raise HTTPException(status_code=502, detail="Failed to publish onboarding request")
        return {"application": application.model_dump(mode="json"), "status": "queued"}


@app.get("/applications")
async def list_applications() -> dict:
    async with _repo() as repo:
        return {"rows": await repo.list_applications()}


@app.get("/applications/{application_id}")
async def get_application(application_id: str) -> dict:
    async with _repo() as repo:
        row = await repo.get_application(UUID(application_id))
        if row is None:
            raise HTTPException(status_code=404, detail="Application not found")
        return row


@app.put("/applications/{application_id}")
async def update_application(application_id: str, payload: dict = Body(...)) -> dict:
    started = perf_counter()
    normalized = dict(payload)
    normalized["id"] = application_id
    application = ApplicationRegistration.model_validate(normalized)
    async with _repo() as repo:
        existing = await repo.get_application(application.id)
        existing_payload = existing.get("payload") if isinstance(existing, dict) else {}
        workflow_keys = ("discovery", "metrics_validation", "rules_generation", "prometheus_update", "validation", "dashboard")
        workflow_payload = {
            key: existing_payload[key]
            for key in workflow_keys
            if isinstance(existing_payload, dict) and key in existing_payload
        }
        await repo.save_application(application)
        if workflow_payload:
            await repo.update_application_status(application.id, status=str(application.status), payload=workflow_payload)
        await _write_audit(repo, application, event_type="application.updated", decision="updated", actor="user", started=started, output={"status": application.status})
        ONBOARDING_SUCCESS.labels(settings.service_name, "update").inc()
        return {"application": application.model_dump(mode="json")}


@app.delete("/applications/{application_id}")
async def delete_application(application_id: str) -> dict:
    started = perf_counter()
    application_uuid = UUID(application_id)
    async with _repo() as repo:
        row = await repo.get_application(application_uuid)
        deleted = await repo.delete_application(application_uuid)
        if deleted and row:
            application = application_from_row(row)
            await _write_audit(repo, application, event_type="application.deleted", decision="deleted", actor="user", started=started, output={"deleted": deleted})
        return {"deleted": deleted}


@app.get("/applications/{application_id}/history")
async def application_history(application_id: str) -> dict:
    async with _repo() as repo:
        return {"rows": await repo.list_application_history(UUID(application_id))}


@app.get("/applications/{application_id}/validations")
async def application_validations(application_id: str) -> dict:
    async with _repo() as repo:
        return {"rows": await repo.list_application_validations(UUID(application_id))}


@app.get("/applications/{application_id}/dashboards")
async def application_dashboards(application_id: str) -> dict:
    async with _repo() as repo:
        return {"rows": await repo.list_application_dashboards(UUID(application_id))}
