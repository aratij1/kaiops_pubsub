from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import httpx
from common.config import Settings, get_settings
from common.models import AlertSeverity
from common.resilience import CircuitBreaker


class ModelTask(StrEnum):
    RCA = "rca"
    IMPACT = "impact"
    FIX = "fix"
    SUMMARIZATION = "summarization"
    GENERAL = "general"


@dataclass
class ModelProvider:
    name: str
    breaker: CircuitBreaker = field(default_factory=CircuitBreaker)
    healthy: bool = True

    async def generate(self, prompt: str, payload: dict[str, Any]) -> str:
        raise NotImplementedError

    def _ensure_available(self) -> None:
        if not self.healthy or not self.breaker.allow():
            self.breaker.record_failure()
            raise RuntimeError(f"{self.name} unavailable")


@dataclass
class UnconfiguredModelProvider(ModelProvider):
    reason: str = "provider is not configured"

    async def generate(self, prompt: str, payload: dict[str, Any]) -> str:
        self.breaker.record_failure()
        raise RuntimeError(f"{self.name} unavailable: {self.reason}")


@dataclass
class OpenAIModelProvider(ModelProvider):
    model: str = "gpt-4o"
    api_key: str | None = None
    base_url: str = "https://api.openai.com/v1"
    timeout_seconds: float = 45.0

    async def generate(self, prompt: str, payload: dict[str, Any]) -> str:
        self._ensure_available()
        if not self.api_key:
            self.breaker.record_failure()
            raise RuntimeError(f"{self.name} unavailable: OPENAI_API_KEY is not configured")

        request_payload = {
            "model": self.model,
            "input": [
                {
                    "role": "system",
                    "content": (
                        "You are an enterprise SRE incident-resolution model. "
                        "Use only the provided incident payload and return concise, actionable operational analysis."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps({"task": prompt, "payload": payload}, default=str),
                },
            ],
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url.rstrip('/')}/responses",
                    headers=headers,
                    json=request_payload,
                )
                response.raise_for_status()
                data = response.json()
        except Exception:
            self.breaker.record_failure()
            raise

        self.breaker.record_success()
        content = data.get("output_text")
        if content:
            return str(content)
        return self._extract_response_text(data)

    def _extract_response_text(self, data: dict[str, Any]) -> str:
        output = data.get("output", [])
        for item in output:
            for content in item.get("content", []):
                text = content.get("text")
                if text:
                    return str(text)
        raise RuntimeError(f"{self.name} returned no text")


@dataclass
class OllamaModelProvider(ModelProvider):
    endpoint: str = "http://ollama:11434"
    model: str = "llama3.1"
    timeout_seconds: float = 45.0

    async def generate(self, prompt: str, payload: dict[str, Any]) -> str:
        self._ensure_available()
        request_payload = {
            "model": self.model,
            "prompt": json.dumps({"task": prompt, "payload": payload}, default=str),
            "stream": False,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(f"{self.endpoint.rstrip('/')}/api/generate", json=request_payload)
                response.raise_for_status()
                data = response.json()
        except Exception:
            self.breaker.record_failure()
            raise

        self.breaker.record_success()
        content = data.get("response")
        if not content:
            raise RuntimeError(f"{self.name} returned no text")
        return str(content)


@dataclass
class ModelRouter:
    providers: dict[str, ModelProvider] = field(default_factory=lambda: build_default_providers(get_settings()))
    failover_chain: dict[str, list[str]] = field(
        default_factory=lambda: {
            "gpt-5": ["gpt-4o", "local-llama", "claude"],
            "claude": ["gpt-5", "gpt-4o", "local-llama"],
            "gemini": ["gpt-4o", "gpt-5", "local-llama"],
            "local-llama": ["gpt-4o"],
            "gpt-4o": ["gpt-5", "local-llama"],
        }
    )

    def select_model(self, *, severity: AlertSeverity, task: ModelTask) -> str:
        if severity == AlertSeverity.CRITICAL:
            return "gpt-5"
        if task == ModelTask.RCA:
            return "claude"
        if task == ModelTask.SUMMARIZATION:
            return "gemini"
        return "local-llama"

    async def route(
        self,
        *,
        severity: AlertSeverity,
        task: ModelTask,
        prompt: str,
        payload: dict[str, Any],
    ) -> dict[str, str]:
        primary = self.select_model(severity=severity, task=task)
        candidates = [primary, *self.failover_chain.get(primary, [])]
        errors: list[str] = []
        for name in candidates:
            try:
                content = await self.providers[name].generate(prompt, payload)
                return {"model": name, "content": content}
            except Exception as exc:
                errors.append(f"{name}: {exc}")
        raise RuntimeError("; ".join(errors))


def build_default_providers(settings: Settings) -> dict[str, ModelProvider]:
    return {
        "gpt-5": OpenAIModelProvider(
            name="gpt-5",
            model=settings.openai_gpt5_model,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            timeout_seconds=settings.llm_request_timeout_seconds,
        ),
        "gpt-4o": OpenAIModelProvider(
            name="gpt-4o",
            model=settings.openai_gpt4o_model,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            timeout_seconds=settings.llm_request_timeout_seconds,
        ),
        "claude": UnconfiguredModelProvider(
            name="claude",
            reason="set ANTHROPIC_API_KEY and add a Claude provider implementation",
        ),
        "gemini": UnconfiguredModelProvider(
            name="gemini",
            reason="set GEMINI_API_KEY and add a Gemini provider implementation",
        ),
        "local-llama": OllamaModelProvider(
            name="local-llama",
            endpoint=settings.local_llm_endpoint,
            timeout_seconds=settings.llm_request_timeout_seconds,
        ),
    }
