from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from common.cloud_operations.connectors import connector_for
from common.cloud_operations.events import build_cloud_event
from common.cloud_operations.models import (
    CloudConnection,
    CloudConnectionCreate,
    DiscoveryRequest,
    ProviderType,
    PlanCompileRequest,
    PlanApprovalRequest,
    ExecutionPolicy,
    MaintenanceWindow,
    ServiceOnboardingProfile,
    ServiceResourceMappingCreate,
)
from common.cloud_operations.repository import CloudOperationsRepository
from common.config import get_settings
from common.service import create_app
from common.tenant_identity import require_tenant_id
from common.topics import CLOUD_OPERATIONS_EVENTS
from fastapi import Body, FastAPI, HTTPException, Query

settings = get_settings()
settings.service_name = "cloud-operations"


async def startup(_: FastAPI) -> None:
    return None


async def shutdown(_: FastAPI) -> None:
    return None


app = create_app(title="KaiMS Cloud Operations Service", settings=settings, startup=startup, shutdown=shutdown)

SERVICE_ONBOARDING_TEMPLATES = [
    {
        "id": "kubernetes_microservice",
        "label": "Kubernetes microservice",
        "resource_types": ["application", "kubernetes_deployment", "pod", "container", "service"],
        "recommended_telemetry": ["metrics", "logs", "traces", "events"],
        "recommended_controls": ["SLO", "runbook", "diagnostic action", "rollback validation"],
    },
    {
        "id": "vm_legacy_application",
        "label": "VM or legacy application",
        "resource_types": ["application", "vm", "node", "load_balancer", "database"],
        "recommended_telemetry": ["host metrics", "application logs", "synthetic checks"],
        "recommended_controls": ["SOP", "restart validation", "escalation policy"],
    },
    {
        "id": "database_service",
        "label": "Database service",
        "resource_types": ["database", "database_instance", "storage_volume"],
        "recommended_telemetry": ["replication lag", "query latency", "storage", "backups"],
        "recommended_controls": ["backup validation", "failover runbook", "data safety policy"],
    },
    {
        "id": "data_pipeline",
        "label": "Data pipeline",
        "resource_types": ["scheduled_job", "data_pipeline", "queue", "object_store"],
        "recommended_telemetry": ["freshness", "volume", "quality checks", "job events"],
        "recommended_controls": ["replay policy", "data validation", "business SLA"],
    },
    {
        "id": "middleware_messaging",
        "label": "Middleware or messaging",
        "resource_types": ["queue", "topic", "broker", "cache"],
        "recommended_telemetry": ["lag", "throughput", "dead letters", "consumer health"],
        "recommended_controls": ["drain policy", "retry policy", "rollback guard"],
    },
]


def _feature_enabled() -> None:
    if not bool(getattr(settings, "cloud_operations_enabled", False)):
        raise HTTPException(status_code=404, detail="Cloud operations are not enabled")


def _provider_execution_enabled(provider: ProviderType) -> bool:
    return bool(getattr(settings, f"cloud_execution_{provider.value}_enabled", False))


def _connector(provider: ProviderType):
    if provider == ProviderType.AZURE:
        return connector_for(
            provider,
            execution_enabled=settings.cloud_execution_azure_enabled,
            kill_switch=settings.cloud_azure_kill_switch_engaged,
            canary_resource_ids={item.strip() for item in settings.cloud_azure_canary_resource_ids.split(",") if item.strip()},
            rate_limit_per_minute=settings.cloud_azure_rate_limit_per_minute,
        )
    return connector_for(provider)


@asynccontextmanager
async def _repo():
    _feature_enabled()
    session_factory = getattr(app.state, "session_factory", None)
    if session_factory is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    session = session_factory()
    try:
        yield CloudOperationsRepository(session)
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def _record_project_binding_rejection(
    *, row: Any, requested_project: str, actor: str, action: str
) -> None:
    """Commit security evidence independently from the rejected work transaction."""
    session_factory = getattr(app.state, "session_factory", None)
    if session_factory is None:
        return
    session = session_factory()
    try:
        repo = CloudOperationsRepository(session)
        await repo.audit(
            tenant_id=row.tenant_id,
            project_id=row.project_id,
            actor=actor,
            action="connection.project_binding_rejected",
            resource_type="provider_connection",
            resource_id=str(row.id),
            payload={
                "operation": action,
                "authoritative_project_id": row.project_id,
                "requested_project_id": requested_project,
            },
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def _bound_connection(
    repo: CloudOperationsRepository,
    connection_id: UUID,
    *,
    tenant_id: str,
    requested_project: str | None,
    actor: str,
    action: str,
) -> Any:
    """Resolve the connection's immutable tenant/project scope and reject relocation."""
    row = await repo.get_connection(connection_id, tenant_id=tenant_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    candidate = str(requested_project or "").strip()
    if candidate and candidate != row.project_id:
        await _record_project_binding_rejection(
            row=row, requested_project=candidate, actor=actor, action=action
        )
        raise HTTPException(
            status_code=409,
            detail="Requested project does not match the connection's authoritative project",
        )
    return row


def _validate_discovery_scope(row: Any, result: Any) -> None:
    resource_ids: set[str] = set()
    for resource in result.resources:
        if (
            resource.tenant_id != row.tenant_id
            or resource.project_id != row.project_id
            or resource.connection_id != row.id
        ):
            raise HTTPException(status_code=409, detail="Discovery returned an out-of-scope resource")
        resource_ids.add(str(resource.id))
    for relationship in result.relationships:
        if (
            relationship.tenant_id != row.tenant_id
            or relationship.project_id != row.project_id
            or relationship.connection_id != row.id
            or relationship.source_resource_id not in resource_ids
            or relationship.target_resource_id not in resource_ids
        ):
            raise HTTPException(status_code=409, detail="Discovery returned an out-of-scope relationship")


async def _publish(event_type: str, *, tenant_id: str, project_id: str, service_id: str | None, payload: dict[str, Any]) -> None:
    producer = getattr(app.state, "producer", None)
    if producer is None:
        return
    event = build_cloud_event(
        event_type=event_type,
        tenant_id=tenant_id,
        project_id=project_id,
        service_id=service_id,
        producer=settings.service_name,
        payload=payload,
    )
    await producer.publish(CLOUD_OPERATIONS_EVENTS, event, key=event["idempotency_key"])


@app.post("/connections")
async def create_connection(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    request = CloudConnectionCreate.model_validate(payload)
    async with _repo() as repo:
        row = await repo.create_connection(request)
        response = repo.connection_payload(row)
        await _publish(
            "connection.created",
            tenant_id=request.tenant_id,
            project_id=request.project_id,
            service_id=None,
            payload={"connection_id": str(row.id), "provider_type": request.provider_type.value},
        )
        return {"connection": response}


@app.get("/connections")
async def list_connections(
    tenant_id: str = Query(min_length=1, max_length=128),
    project_id: str | None = Query(default=None, max_length=128),
) -> dict[str, Any]:
    tenant_id = require_tenant_id(tenant_id, source="cloud operations connection list")
    async with _repo() as repo:
        rows = await repo.list_connections(tenant_id=tenant_id, project_id=project_id)
        return {"rows": [repo.connection_payload(row) for row in rows], "count": len(rows)}


@app.get("/capabilities")
async def list_capabilities(provider: ProviderType = ProviderType.SIMULATOR) -> dict[str, Any]:
    _feature_enabled()
    try:
        manifest = _connector(provider).list_capabilities()
    except NotImplementedError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"capabilities": [manifest.model_dump(mode="json")]}


@app.get("/onboarding/templates")
async def onboarding_templates() -> dict[str, Any]:
    _feature_enabled()
    return {"templates": SERVICE_ONBOARDING_TEMPLATES}


@app.post("/connections/{connection_id}/validate")
async def validate_connection(
    connection_id: UUID,
    payload: dict[str, Any] = Body(default={}),
) -> dict[str, Any]:
    tenant_id = require_tenant_id(payload.get("tenant_id"), source="cloud operations connection validation")
    actor = str(payload.get("actor") or "system").strip() or "system"
    async with _repo() as repo:
        row = await _bound_connection(
            repo, connection_id, tenant_id=tenant_id,
            requested_project=payload.get("project_id"), actor=actor, action="validate",
        )
        connection = CloudConnection.model_validate(repo.connection_payload(row))
        try:
            result = await _connector(connection.provider_type).validate_connection(connection)
        except NotImplementedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        await repo.record_validation(row, result, actor=actor)
        await _publish(
            f"connection.{result.status}",
            tenant_id=row.tenant_id,
            project_id=row.project_id,
            service_id=None,
            payload={"connection_id": str(row.id), **result.model_dump(mode="json")},
        )
        return {"connection": repo.connection_payload(row), "validation": result.model_dump(mode="json")}


@app.post("/connections/{connection_id}/discover")
async def discover_resources(
    connection_id: UUID,
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    request = DiscoveryRequest.model_validate(payload)
    async with _repo() as repo:
        row = await _bound_connection(
            repo, connection_id, tenant_id=request.tenant_id,
            requested_project=request.project_id, actor=request.actor, action="discover",
        )
        if row.status != "validated":
            raise HTTPException(status_code=409, detail="Connection must be validated before discovery")
        if not row.read_capability:
            raise HTTPException(status_code=403, detail="Connection does not grant read capability")
        connection = CloudConnection.model_validate(repo.connection_payload(row))
        authoritative_request = request.model_copy(update={"project_id": row.project_id})
        try:
            connector = _connector(connection.provider_type)
            result = await connector.discover_resources(connection, authoritative_request)
        except NotImplementedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        _validate_discovery_scope(row, result)
        run = await repo.start_discovery(row, authoritative_request)
        result.run_id = run.id
        await repo.complete_discovery(row, run, result, request=authoritative_request)
        await _publish(
            "discovery.completed",
            tenant_id=row.tenant_id,
            project_id=row.project_id,
            service_id=authoritative_request.service_id,
            payload={
                "connection_id": str(row.id),
                "run_id": str(run.id),
                "resource_count": len(result.resources),
                "relationship_count": len(result.relationships),
            },
        )
        return {
            "run_id": str(run.id),
            "status": result.status.value,
            "resources": [item.model_dump(mode="json") for item in result.resources],
            "relationships": [item.model_dump(mode="json") for item in result.relationships],
            "message": result.message,
        }


@app.get("/resources")
async def list_resources(
    tenant_id: str = Query(min_length=1, max_length=128),
    project_id: str | None = Query(default=None, max_length=128),
    service_id: str | None = Query(default=None, max_length=128),
    environment: str | None = Query(default=None, max_length=64),
) -> dict[str, Any]:
    tenant_id = require_tenant_id(tenant_id, source="cloud operations resource list")
    async with _repo() as repo:
        rows = await repo.list_resources(
            tenant_id=tenant_id,
            project_id=project_id,
            service_id=service_id,
            environment=environment,
        )
        return {"rows": [repo.resource_payload(row) for row in rows], "count": len(rows)}


@app.get("/cockpit")
async def operations_cockpit(
    tenant_id: str = Query(min_length=1, max_length=128),
    project_id: str | None = Query(default=None, max_length=128),
    environment: str | None = Query(default=None, max_length=64),
) -> dict[str, Any]:
    tenant_id = require_tenant_id(tenant_id, source="cloud operations cockpit")
    async with _repo() as repo:
        return await repo.cockpit(tenant_id=tenant_id, project_id=project_id, environment=environment)


@app.post("/services/{service_id}/map")
async def map_service_resources(service_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    request = ServiceResourceMappingCreate.model_validate({**payload, "service_id": service_id})
    async with _repo() as repo:
        rows = await repo.map_service(
            tenant_id=request.tenant_id,
            project_id=request.project_id,
            service_id=request.service_id,
            environment=request.environment,
            resource_ids=request.resource_ids,
            owner=request.owner,
        )
        await _publish(
            "topology.changed",
            tenant_id=request.tenant_id,
            project_id=request.project_id,
            service_id=request.service_id,
            payload={"mapped_resource_count": len(rows), "environment": request.environment},
        )
        return {"rows": [{"id": str(row.id), "resource_id": row.resource_id, "status": row.status} for row in rows]}


@app.get("/services/{service_id}/360")
async def service_360(
    service_id: str,
    tenant_id: str = Query(min_length=1, max_length=128),
    project_id: str = Query(min_length=1, max_length=128),
    environment: str | None = Query(default=None, max_length=64),
) -> dict[str, Any]:
    tenant_id = require_tenant_id(tenant_id, source="cloud operations service 360")
    async with _repo() as repo:
        return await repo.service_360(
            tenant_id=tenant_id,
            project_id=project_id,
            service_id=service_id,
            environment=environment,
        )


@app.get("/services/{service_id}/topology")
async def service_topology(
    service_id: str,
    tenant_id: str = Query(min_length=1, max_length=128),
    project_id: str = Query(min_length=1, max_length=128),
    environment: str | None = Query(default=None, max_length=64),
) -> dict[str, Any]:
    tenant_id = require_tenant_id(tenant_id, source="cloud operations topology")
    async with _repo() as repo:
        return await repo.topology(tenant_id=tenant_id, project_id=project_id, service_id=service_id, environment=environment)


@app.put("/services/{service_id}/onboarding")
async def upsert_service_onboarding(service_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    profile = ServiceOnboardingProfile.model_validate({**payload, "service_id": service_id})
    async with _repo() as repo:
        row = await repo.upsert_service_onboarding(profile)
        score = await repo.recalculate_readiness(
            tenant_id=profile.tenant_id,
            project_id=profile.project_id,
            service_id=profile.service_id,
            environment=profile.environment,
            actor=profile.actor,
        )
        await _publish(
            "service.readiness.changed",
            tenant_id=profile.tenant_id,
            project_id=profile.project_id,
            service_id=profile.service_id,
            payload={"environment": profile.environment, "readiness_state": score.readiness_state, "overall_score": float(score.overall_score or 0.0)},
        )
        return {"profile": repo.onboarding_payload(row), "readiness": {"state": score.readiness_state, "overall_score": float(score.overall_score or 0.0), "scores": score.scores or {}}}


@app.post("/services/{service_id}/readiness/recalculate")
async def recalculate_service_readiness(service_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    tenant_id = require_tenant_id(payload.get("tenant_id"), source="cloud operations readiness")
    project_id = str(payload.get("project_id") or "").strip()
    environment = str(payload.get("environment") or "prod").strip()
    actor = str(payload.get("actor") or "system").strip() or "system"
    if not project_id:
        raise HTTPException(status_code=422, detail="project_id is required")
    async with _repo() as repo:
        score = await repo.recalculate_readiness(
            tenant_id=tenant_id,
            project_id=project_id,
            service_id=service_id,
            environment=environment,
            actor=actor,
        )
        await _publish(
            "service.readiness.changed",
            tenant_id=tenant_id,
            project_id=project_id,
            service_id=service_id,
            payload={"environment": environment, "readiness_state": score.readiness_state, "overall_score": float(score.overall_score or 0.0)},
        )
        return {"state": score.readiness_state, "overall_score": float(score.overall_score or 0.0), "scores": score.scores or {}}


@app.post("/plans/compile")
async def compile_plan(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    request = PlanCompileRequest.model_validate(payload)
    async with _repo() as repo:
        try:
            row = await repo.compile_plan(request)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        await _publish(
            "plan.compiled", tenant_id=request.tenant_id, project_id=request.project_id,
            service_id=request.service_id, payload={"plan_id": str(row.id), "checksum": row.checksum},
        )
        return {"plan": repo.plan_payload(row)}


@app.get("/plans/{plan_id}")
async def get_plan(plan_id: UUID, tenant_id: str = Query(min_length=1, max_length=128)) -> dict[str, Any]:
    tenant_id = require_tenant_id(tenant_id, source="cloud plan lookup")
    async with _repo() as repo:
        row = await repo.get_plan(plan_id, tenant_id=tenant_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Compiled plan not found")
        return {"plan": repo.plan_payload(row)}


@app.post("/plans/{plan_id}/simulate")
async def simulate_plan(plan_id: UUID, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    tenant_id = require_tenant_id(payload.get("tenant_id"), source="cloud plan simulation")
    actor = str(payload.get("actor") or "system").strip() or "system"
    async with _repo() as repo:
        plan = await repo.get_plan(plan_id, tenant_id=tenant_id)
        if plan is None:
            raise HTTPException(status_code=404, detail="Compiled plan not found")
        row = await repo.simulate_plan(plan, actor=actor)
        await _publish(
            "plan.simulated", tenant_id=tenant_id, project_id=plan.project_id,
            service_id=plan.service_id, payload={"plan_id": str(plan.id), "simulation_id": str(row.id), "verdict": row.verdict},
        )
        return {"simulation": repo.simulation_payload(row)}


@app.post("/plans/{plan_id}/approval")
async def approve_plan(plan_id: UUID, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    request = PlanApprovalRequest.model_validate(payload)
    async with _repo() as repo:
        plan = await repo.get_plan(plan_id, tenant_id=request.tenant_id)
        if plan is None:
            raise HTTPException(status_code=404, detail="Compiled plan not found")
        try:
            approval = await repo.approve_plan(plan, request)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"approval": {"id": str(approval.id), "plan_id": str(plan.id), "checksum": approval.checksum, "decision": approval.decision, "reason": approval.reason, "actor": approval.actor}}


@app.post("/plans/{plan_id}/execute")
async def execute_plan(plan_id: UUID, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    tenant_id = require_tenant_id(payload.get("tenant_id"), source="cloud plan execution")
    actor = str(payload.get("actor") or "system").strip() or "system"
    async with _repo() as repo:
        plan = await repo.get_plan(plan_id, tenant_id=tenant_id)
        if plan is None:
            raise HTTPException(status_code=404, detail="Compiled plan not found")
        resources = await repo.list_resources(tenant_id=tenant_id, project_id=plan.project_id, service_id=plan.service_id, environment=plan.environment)
        providers = {row.provider for row in resources if str(row.id) in {str(action.get("resource_id")) for action in plan.actions}}
        if len(providers) != 1:
            raise HTTPException(status_code=409, detail="Execution requires all targets to use one enabled provider adapter")
        provider = ProviderType(next(iter(providers)))
        if not _provider_execution_enabled(provider):
            raise HTTPException(status_code=409, detail=f"Provider execution adapter {provider.value} is disabled")
        await repo.recover_expired_leases(tenant_id=tenant_id)
        governance_blocks = await repo.evaluate_execution_governance(plan, provider=provider.value)
        if governance_blocks:
            raise HTTPException(status_code=409, detail={"message": "Execution blocked by policy", "reasons": governance_blocks})
        try:
            execution, acquired = await repo.acquire_execution(plan, actor=actor, provider=provider.value)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not acquired:
            return {"execution": repo.execution_payload(execution), "reused": True}
        results: list[dict[str, Any]] = []
        credential_session = None
        try:
            credential_session = await repo.broker_credential_session(plan, execution, provider=provider.value, ttl_minutes=settings.cloud_credential_session_minutes)
            connector = _connector(provider)
            for index, action in enumerate(plan.actions):
                results.append(await connector.execute_action(action=action, idempotency_key=f"{execution.idempotency_key}:{index}"))
            checks = [await connector.validate_action(action=action) for action in plan.actions]
            validation = {"passed": all(bool(check.get("passed")) for check in checks), "checks": checks}
            status = "succeeded" if validation["passed"] else "validation_failed"
            await repo.finalize_execution(execution, status=status, action_results=results, validation=validation)
        except (NotImplementedError, ValueError) as exc:
            await repo.finalize_execution(execution, status="failed", action_results=results, validation={}, error=str(exc))
        finally:
            if credential_session is not None:
                await repo.revoke_credential_session(credential_session)
        return {"execution": repo.execution_payload(execution), "reused": False}


@app.post("/executions/{execution_id}/rollback")
async def rollback_execution(execution_id: UUID, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    tenant_id = require_tenant_id(payload.get("tenant_id"), source="cloud execution rollback")
    actor = str(payload.get("actor") or "system").strip() or "system"
    async with _repo() as repo:
        execution = await repo.get_execution(execution_id, tenant_id=tenant_id)
        if execution is None:
            raise HTTPException(status_code=404, detail="Execution not found")
        if execution.status == "rolled_back":
            return {"execution": repo.execution_payload(execution), "reused": True}
        plan = await repo.get_plan(execution.plan_id, tenant_id=tenant_id)
        if plan is None or execution.checksum != plan.checksum:
            raise HTTPException(status_code=409, detail="Rollback blocked: execution is not bound to the current immutable plan")
        results: list[dict[str, Any]] = []
        try:
            connector = _connector(ProviderType(execution.provider))
            for index, action in enumerate(reversed(plan.actions)):
                result = await connector.rollback_action(action=action, idempotency_key=f"{execution.idempotency_key}:rollback:{index}")
                results.append(result)
                await repo.record_compensation(execution, sequence=index, action=action, status=str(result.get("status") or "unknown"), evidence=result)
            checks = [await connector.validate_action(action=action) for action in plan.actions]
            validation = {"passed": all(bool(check.get("passed")) for check in checks), "checks": checks, "rollback": True}
            status = "rolled_back" if validation["passed"] else "rollback_failed"
            execution.actor = actor
            await repo.finalize_execution(execution, status=status, action_results=results, validation=validation)
        except (NotImplementedError, ValueError) as exc:
            execution.actor = actor
            await repo.finalize_execution(execution, status="rollback_failed", action_results=results, validation={}, error=str(exc))
        return {"execution": repo.execution_payload(execution), "reused": False}


@app.put("/governance/policy")
async def upsert_execution_policy(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    policy = ExecutionPolicy.model_validate(payload)
    async with _repo() as repo:
        row = await repo.upsert_execution_policy(policy)
        return {"policy": {"id": str(row.id), "tenant_id": row.tenant_id, "project_id": row.project_id, "environment": row.environment, "allowed_providers": row.allowed_providers, "allowed_actions": row.allowed_actions, "maximum_risk": row.maximum_risk, "require_rollback": row.require_rollback, "require_maintenance_window": row.require_maintenance_window, "enabled": row.enabled}}


@app.post("/governance/maintenance-windows")
async def create_maintenance_window(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    window = MaintenanceWindow.model_validate(payload)
    async with _repo() as repo:
        row = await repo.create_maintenance_window(window)
        return {"window": {"id": str(row.id), "starts_at": row.starts_at.isoformat(), "ends_at": row.ends_at.isoformat(), "reason": row.reason}}


@app.post("/governance/leases/recover")
async def recover_execution_leases(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    tenant_id = require_tenant_id(payload.get("tenant_id"), source="cloud lease recovery")
    async with _repo() as repo:
        return {"recovered": await repo.recover_expired_leases(tenant_id=tenant_id)}


@app.get("/providers/status")
async def provider_status() -> dict[str, Any]:
    _feature_enabled()
    rows = []
    for provider in (ProviderType.SIMULATOR, ProviderType.AZURE, ProviderType.AWS, ProviderType.GCP):
        enabled = _provider_execution_enabled(provider)
        try:
            manifest = _connector(provider).list_capabilities()
            rows.append({"provider": provider.value, "registered": True, "execution_enabled": enabled, "health_status": manifest.health_status, "connector_version": manifest.connector_version, "write_operations": manifest.supported_write_operations, "kill_switch_engaged": settings.cloud_azure_kill_switch_engaged if provider == ProviderType.AZURE else False, "canary_target_count": len({item.strip() for item in settings.cloud_azure_canary_resource_ids.split(',') if item.strip()}) if provider == ProviderType.AZURE else 0})
        except NotImplementedError:
            rows.append({"provider": provider.value, "registered": False, "execution_enabled": enabled, "health_status": "unavailable", "write_operations": []})
    return {"providers": rows}
