from __future__ import annotations

from pydantic import BaseModel

from common.config import get_settings
from common.models import AlertSeverity
from common.service import create_app
from model_router import ModelRouter, ModelTask

settings = get_settings()
settings.service_name = "model-router"
router = ModelRouter()
app = create_app(title="KaiOps Model Router", settings=settings)


class RouteRequest(BaseModel):
    severity: AlertSeverity
    task: ModelTask
    prompt: str
    payload: dict = {}


@app.post("/route")
async def route(request: RouteRequest) -> dict[str, str]:
    return await router.route(
        severity=request.severity,
        task=request.task,
        prompt=request.prompt,
        payload=request.payload,
    )
