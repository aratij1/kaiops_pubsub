from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx

from common.models import AlertSeverity


@dataclass(slots=True)
class GenerationRequest:
    severity: AlertSeverity
    task: str
    prompt: str
    payload: dict[str, Any]


class ModelGateway(ABC):
    @abstractmethod
    async def generate(self, request: GenerationRequest) -> dict[str, Any]:
        raise NotImplementedError


class MockProvider(ModelGateway):
    async def generate(self, request: GenerationRequest) -> dict[str, Any]:
        return {
            "model": "mock",
            "content": f"mock:{request.task}:{request.prompt}",
            "usage": {
                "provider": "mock",
                "model": "mock",
                "task": request.task,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "total_cost_usd": 0.0,
                "estimated": False,
            },
        }


class RouterModelGateway(ModelGateway):
    def __init__(self, router: Any) -> None:
        self._router = router

    async def generate(self, request: GenerationRequest) -> dict[str, Any]:
        task_enum = request.task
        model_task = getattr(task_enum, "value", task_enum)
        model_task_obj = None
        if hasattr(self._router, "route"):
            try:
                from model_router import ModelTask

                model_task_obj = ModelTask(model_task)
            except Exception:
                model_task_obj = model_task
            return await self._router.route(
                severity=request.severity,
                task=model_task_obj,
                prompt=request.prompt,
                payload=request.payload,
            )
        raise RuntimeError("Configured model gateway router does not implement route()")


class HttpModelGateway(ModelGateway):
    """Calls the model-router service's POST /route API instead of importing it in-process."""

    def __init__(self, base_url: str, *, timeout_seconds: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    async def generate(self, request: GenerationRequest) -> dict[str, Any]:
        severity_value = getattr(request.severity, "value", request.severity)
        task_value = getattr(request.task, "value", request.task)
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.post(
                f"{self._base_url}/route",
                json={
                    "severity": severity_value,
                    "task": task_value,
                    "prompt": request.prompt,
                    "payload": request.payload,
                },
            )
            response.raise_for_status()
            return response.json()


class OpenAIProvider(MockProvider):
    pass


class AzureOpenAIProvider(MockProvider):
    pass


class OllamaProvider(MockProvider):
    pass


class ClaudeProvider(MockProvider):
    pass
