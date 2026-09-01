from __future__ import annotations

from contextlib import asynccontextmanager
from time import perf_counter
from uuid import UUID

from common.config import get_settings
from common.logging import get_logger
from common.models import ApplicationRegistration, ApplicationStatus, MonitoringAuditEvent
from common.monitoring_onboarding import application_from_row
from common.onboarding_control_plane import (
    ConnectorSelection,
    EnvironmentDefinition,
    OnboardingControlPlane,
    OnboardingStatus,
    OnboardingStep,
    ProjectDefinition,
    ReadinessSignal,
    calculate_operational_readiness,
    production_auto_execute_allowed,
)
from common.repository import IncidentRepository
from common.service import create_app
from common.telemetry import APPLICATIONS_ONBOARDED, ONBOARDING_FAILED, ONBOARDING_SUCCESS
from common.topics import APPLICATION_ONBOARD_REQUESTED
from fastapi import Body, FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

settings = get_settings()
settings.service_name = "application-onboarding"
logger = get_logger(__name__)


async def startup(_: FastAPI) -> None:
    return None


async def shutdown(_: FastAPI) -> None:
    return None


app = create_app(title="KaiOps Application Onboarding Service", settings=settings, startup=startup, shutdown=shutdown)


class CreateControlPlaneRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str
    project: ProjectDefinition
    environments: list[EnvironmentDefinition] = Field(default_factory=list)


class SaveStepRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    data: dict
    complete: bool = True


class ReadinessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    signals: list[ReadinessSignal]


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


def _validate_step_payload(step: OnboardingStep, data: dict) -> dict:
    normalized = dict(data)
    if step == OnboardingStep.ENVIRONMENTS:
        normalized["environments"] = [
            item.model_dump(mode="json")
            for item in [EnvironmentDefinition.model_validate(value) for value in data.get("environments", [])]
        ]
        if not normalized["environments"]:
            raise ValueError("at least one environment is required")
    if step in {
        OnboardingStep.OBSERVABILITY, OnboardingStep.INCIDENT_SOURCES,
        OnboardingStep.CHANGE_SOURCES, OnboardingStep.RESOLUTION_CONNECTIONS,
    }:
        normalized["connectors"] = [
            item.model_dump(mode="json")
            for item in [ConnectorSelection.model_validate(value) for value in data.get("connectors", [])]
        ]
    if step == OnboardingStep.AUTOMATION_POLICY:
        modes = data.get("capability_modes")
        if not isinstance(modes, dict):
            raise ValueError("automation policy requires capability_modes")
        from common.remediation_plan import AutonomyRecommendation
        normalized["capability_modes"] = {
            str(capability_id): AutonomyRecommendation(mode).value
            for capability_id, mode in modes.items()
        }
    return normalized


@app.post("/onboarding/projects", response_model=OnboardingControlPlane)
async def create_onboarding_control_plane(payload: CreateControlPlaneRequest) -> OnboardingControlPlane:
    control = OnboardingControlPlane(
        tenant_id=payload.tenant_id,
        project=payload.project,
        environments=payload.environments,
        completed_steps=[OnboardingStep.PROJECT],
        current_step=OnboardingStep.ENVIRONMENTS,
    )
    async with _repo() as repo:
        await repo.save_onboarding_control_plane(control.model_dump(mode="json"))
    return control


@app.get("/onboarding/projects/{onboarding_id}", response_model=OnboardingControlPlane)
async def get_onboarding_control_plane(
    onboarding_id: UUID,
    x_tenant_id: str = Header(alias="X-Tenant-Id"),
) -> OnboardingControlPlane:
    async with _repo() as repo:
        payload = await repo.get_onboarding_control_plane(onboarding_id, x_tenant_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Onboarding project not found")
    return OnboardingControlPlane.model_validate(payload)


@app.put("/onboarding/projects/{onboarding_id}/steps/{step}", response_model=OnboardingControlPlane)
async def save_onboarding_step(
    onboarding_id: UUID,
    step: OnboardingStep,
    request: SaveStepRequest,
    x_tenant_id: str = Header(alias="X-Tenant-Id"),
) -> OnboardingControlPlane:
    async with _repo() as repo:
        stored = await repo.get_onboarding_control_plane(onboarding_id, x_tenant_id)
        if stored is None:
            raise HTTPException(status_code=404, detail="Onboarding project not found")
        control = OnboardingControlPlane.model_validate(stored)
        if request.expected_version != control.version:
            raise HTTPException(status_code=409, detail="Onboarding draft version conflict")
        if int(step) > int(control.current_step):
            raise HTTPException(status_code=409, detail="Onboarding steps must be completed sequentially")
        try:
            data = _validate_step_payload(step, request.data)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        steps = {**control.steps, str(int(step)): data}
        completed = list(control.completed_steps)
        if request.complete and step not in completed:
            completed.append(step)
        completed = sorted(set(completed), key=int)
        current = OnboardingStep(min(12, max([int(value) for value in completed], default=0) + 1))
        environments = control.environments
        if step == OnboardingStep.ENVIRONMENTS:
            environments = [EnvironmentDefinition.model_validate(value) for value in data["environments"]]
        control = control.model_copy(update={
            "steps": steps, "completed_steps": completed, "current_step": current,
            "environments": environments, "version": control.version + 1,
        })
        await repo.save_onboarding_control_plane(control.model_dump(mode="json"))
    return control


@app.post("/onboarding/projects/{onboarding_id}/readiness", response_model=OnboardingControlPlane)
async def evaluate_onboarding_readiness(
    onboarding_id: UUID,
    request: ReadinessRequest,
    x_tenant_id: str = Header(alias="X-Tenant-Id"),
) -> OnboardingControlPlane:
    async with _repo() as repo:
        stored = await repo.get_onboarding_control_plane(onboarding_id, x_tenant_id)
        if stored is None:
            raise HTTPException(status_code=404, detail="Onboarding project not found")
        control = OnboardingControlPlane.model_validate(stored)
        if request.expected_version != control.version:
            raise HTTPException(status_code=409, detail="Onboarding draft version conflict")
        readiness = calculate_operational_readiness(request.signals)
        policy = control.steps.get(str(int(OnboardingStep.AUTOMATION_POLICY)), {})
        modes = policy.get("capability_modes") if isinstance(policy.get("capability_modes"), dict) else {}
        autonomy_allowed = production_auto_execute_allowed(
            control.model_copy(update={"readiness": readiness}), modes,
        )
        status = OnboardingStatus.READY if len(control.completed_steps) == 12 and autonomy_allowed else OnboardingStatus.BLOCKED
        control = control.model_copy(update={
            "readiness": readiness, "status": status, "version": control.version + 1,
        })
        await repo.save_onboarding_control_plane(control.model_dump(mode="json"))
    return control


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
