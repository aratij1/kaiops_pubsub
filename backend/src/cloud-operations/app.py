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


def _feature_enabled() -> None:
    if not bool(getattr(settings, "cloud_operations_enabled", False)):
        raise HTTPException(status_code=404, detail="Cloud operations are not enabled")


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
    finally:
        await session.close()


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
        manifest = connector_for(provider).list_capabilities()
    except NotImplementedError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"capabilities": [manifest.model_dump(mode="json")]}


@app.post("/connections/{connection_id}/validate")
async def validate_connection(
    connection_id: UUID,
    payload: dict[str, Any] = Body(default={}),
) -> dict[str, Any]:
    tenant_id = require_tenant_id(payload.get("tenant_id"), source="cloud operations connection validation")
    actor = str(payload.get("actor") or "system").strip() or "system"
    async with _repo() as repo:
        row = await repo.get_connection(connection_id, tenant_id=tenant_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Connection not found")
        connection = CloudConnection.model_validate(repo.connection_payload(row))
        try:
            result = await connector_for(connection.provider_type).validate_connection(connection)
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
        row = await repo.get_connection(connection_id, tenant_id=request.tenant_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Connection not found")
        if row.status != "validated":
            raise HTTPException(status_code=409, detail="Connection must be validated before discovery")
        if not row.read_capability:
            raise HTTPException(status_code=403, detail="Connection does not grant read capability")
        connection = CloudConnection.model_validate(repo.connection_payload(row))
        try:
            connector = connector_for(connection.provider_type)
            run = await repo.start_discovery(row, request)
            result = await connector.discover_resources(connection, request)
            result.run_id = run.id
        except NotImplementedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        await repo.complete_discovery(row, run, result, request=request)
        await _publish(
            "discovery.completed",
            tenant_id=request.tenant_id,
            project_id=request.project_id,
            service_id=request.service_id,
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
