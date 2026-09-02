from __future__ import annotations

from typing import Any

import httpx
from ai_workbench_common.models import Context

from common.config import Settings
from common.models import Alert, AlertSeverity, Incident, Recommendation


class AiLayerClient:
    """Endpoint-only client for the AI layer.

    Application services use this client instead of importing AI agents directly.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._timeout = httpx.Timeout(float(settings.ai_layer_request_timeout_seconds), connect=10.0)

    def _headers(self) -> dict[str, str]:
        token = str(getattr(self._settings, "ai_layer_auth_token", "") or "").strip()
        return {"Authorization": f"Bearer {token}"} if token else {}

    @staticmethod
    def _join(base_url: str, path: str) -> str:
        return f"{str(base_url).rstrip('/')}/{path.lstrip('/')}"

    async def collect_context(
        self,
        *,
        alert: Alert,
        incident: Incident,
        decision: dict[str, Any] | None = None,
    ) -> Context:
        payload = {
            "alert": alert.model_dump(mode="json"),
            "incident": incident.model_dump(mode="json"),
            "decision": decision or {},
        }
        async with httpx.AsyncClient(timeout=self._timeout, headers=self._headers()) as client:
            response = await client.post(self._join(self._settings.context_agent_url, "/collect"), json=payload)
            response.raise_for_status()
            return Context.model_validate(response.json())

    async def resolve(self, *, context: Context) -> Recommendation:
        async with httpx.AsyncClient(timeout=self._timeout, headers=self._headers()) as client:
            response = await client.post(
                self._join(self._settings.resolution_agent_url, "/resolve"),
                json=context.model_dump(mode="json"),
            )
            response.raise_for_status()
            return Recommendation.model_validate(response.json())

    async def bootstrap_resolution_catalog(
        self,
        *,
        incident: Incident,
        context: Context,
        recommendation: Recommendation,
    ) -> dict[str, Any]:
        """Start governed evidence/runbook development for a new incident."""
        payload = {
            "incident": incident.model_dump(mode="json"),
            "context": context.model_dump(mode="json"),
            "recommendation": recommendation.model_dump(mode="json"),
        }
        async with httpx.AsyncClient(timeout=self._timeout, headers=self._headers()) as client:
            response = await client.post(
                self._join(self._settings.knowledge_development_url, "/incidents/bootstrap"),
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, dict) else {}

    async def route_model(
        self,
        *,
        severity: AlertSeverity | str,
        task: str,
        prompt: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        severity_value = severity.value if isinstance(severity, AlertSeverity) else str(severity)
        request_payload = {
            "severity": severity_value,
            "task": str(task),
            "prompt": str(prompt or ""),
            "payload": payload or {},
        }
        async with httpx.AsyncClient(timeout=self._timeout, headers=self._headers()) as client:
            response = await client.post(self._join(self._settings.model_router_url, "/route"), json=request_payload)
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, dict) else {}
