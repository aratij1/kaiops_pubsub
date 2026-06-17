from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

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
        if not self.healthy or not self.breaker.allow():
            self.breaker.record_failure()
            raise RuntimeError(f"{self.name} unavailable")
        self.breaker.record_success()
        return f"[{self.name}] {prompt}: {payload.get('summary', payload.get('service', 'incident'))}"


@dataclass
class ModelRouter:
    providers: dict[str, ModelProvider] = field(
        default_factory=lambda: {
            "gpt-5": ModelProvider("gpt-5"),
            "gpt-4o": ModelProvider("gpt-4o"),
            "claude": ModelProvider("claude"),
            "gemini": ModelProvider("gemini"),
            "local-llama": ModelProvider("local-llama"),
        }
    )
    failover_chain: dict[str, list[str]] = field(
        default_factory=lambda: {
            "gpt-5": ["gpt-4o", "claude", "local-llama"],
            "claude": ["gpt-5", "gpt-4o", "local-llama"],
            "gemini": ["gpt-4o", "local-llama"],
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
