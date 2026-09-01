from __future__ import annotations

from common.config import get_settings
from common.capability_registry import default_capability_registry
from common.service import create_app
from connector_hub.contracts import ConnectorOperationUnavailable
from connector_hub.registry import default_connector_registry
from fastapi import HTTPException

settings = get_settings()
settings.service_name = "connector-hub"
app = create_app(title="KaiMS Connector Hub", settings=settings)
registry = default_connector_registry()
capability_registry = default_capability_registry()


@app.get("/connectors")
async def list_connectors() -> dict:
    return {"connectors": [row.model_dump(mode="json") for row in registry.list_metadata()]}


@app.get("/connectors/{connector_id}")
async def get_connector(connector_id: str) -> dict:
    try:
        return registry.get(connector_id).metadata.model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/connectors/{connector_id}/capabilities")
async def get_capabilities(connector_id: str) -> dict:
    try:
        plugin = registry.get(connector_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"connector_id": connector_id, "capabilities": plugin.get_capabilities()}


@app.get("/capabilities")
async def list_registered_capabilities() -> dict:
    return {"capabilities": [row.model_dump(mode="json") for row in capability_registry.list()]}


@app.get("/capabilities/{capability_id}")
async def get_registered_capability(capability_id: str) -> dict:
    try:
        return capability_registry.get(capability_id).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.exception_handler(ConnectorOperationUnavailable)
async def unavailable_operation(_request, exc: ConnectorOperationUnavailable):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=501, content={"detail": str(exc), "code": "connector_operation_unavailable"})
