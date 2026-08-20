from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import json
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

    def __init__(self, base_url: str, *, timeout_seconds: float = 30.0, max_payload_bytes: int = 48_000) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._max_payload_bytes = max(8_000, int(max_payload_bytes))

    @staticmethod
    def _compact_value(value: Any, *, depth: int = 0) -> Any:
        """Bound noisy evidence while retaining the fields needed for grounded reasoning."""
        if depth >= 6:
            return "<nested value omitted>"
        if isinstance(value, str):
            return value if len(value) <= 4_000 else f"{value[:4_000]}\n<trimmed {len(value) - 4_000} chars>"
        if isinstance(value, list):
            items = value[:20]
            compacted = [HttpModelGateway._compact_value(item, depth=depth + 1) for item in items]
            if len(value) > len(items):
                compacted.append({"omitted_items": len(value) - len(items)})
            return compacted
        if isinstance(value, dict):
            return {
                str(key): HttpModelGateway._compact_value(item, depth=depth + 1)
                for key, item in value.items()
                if str(key) not in {"raw", "raw_payload", "projection_payload", "model_calls"}
            }
        return value

    def _compact_payload(self, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        original_bytes = len(json.dumps(payload, default=str, separators=(",", ":")).encode("utf-8"))
        compacted = self._compact_value(payload)
        compacted_bytes = len(json.dumps(compacted, default=str, separators=(",", ":")).encode("utf-8"))
        if compacted_bytes > self._max_payload_bytes and isinstance(compacted, dict):
            # Preserve incident identity and conclusions; progressively omit bulky optional evidence.
            for key in ("log_intelligence", "observability", "discovery_evidence", "evidence", "related_incidents"):
                if compacted_bytes <= self._max_payload_bytes:
                    break
                if key in compacted:
                    compacted[key] = {"omitted": "payload budget exceeded", "source": key}
                    compacted_bytes = len(json.dumps(compacted, default=str, separators=(",", ":")).encode("utf-8"))
        return compacted, {
            "original_bytes": original_bytes,
            "sent_bytes": compacted_bytes,
            "trimmed": compacted_bytes < original_bytes,
            "budget_bytes": self._max_payload_bytes,
        }

    async def generate(self, request: GenerationRequest) -> dict[str, Any]:
        severity_value = getattr(request.severity, "value", request.severity)
        task_value = getattr(request.task, "value", request.task)
        payload, payload_budget = self._compact_payload(request.payload)
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.post(
                f"{self._base_url}/route",
                json={
                    "severity": severity_value,
                    "task": task_value,
                    "prompt": request.prompt,
                    "payload": payload,
                },
            )
            response.raise_for_status()
            result = response.json()
            if isinstance(result, dict):
                usage = result.setdefault("usage", {})
                if isinstance(usage, dict):
                    usage["request_payload"] = payload_budget
            return result


class OpenAIProvider(MockProvider):
    pass


class AzureOpenAIProvider(MockProvider):
    pass


class OllamaProvider(MockProvider):
    pass


class ClaudeProvider(MockProvider):
    pass
