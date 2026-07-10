from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from common.resilience import CircuitBreaker

ToolHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(slots=True)
class ToolSpec:
    name: str
    handler: ToolHandler
    timeout_seconds: float = 10.0
    breaker: CircuitBreaker = field(default_factory=CircuitBreaker)
    permissions: set[str] = field(default_factory=set)


@dataclass(slots=True)
class ToolRegistry:
    tools: dict[str, ToolSpec] = field(default_factory=dict)

    def register(self, spec: ToolSpec) -> None:
        self.tools[spec.name] = spec

    async def execute(self, name: str, payload: dict[str, Any], *, role: str = "") -> dict[str, Any]:
        spec = self.tools.get(name)
        if spec is None:
            raise KeyError(f"unknown tool: {name}")
        if spec.permissions and role not in spec.permissions:
            raise PermissionError(f"role {role or 'anonymous'} not allowed to execute tool {name}")
        if not spec.breaker.allow():
            raise RuntimeError(f"tool circuit open: {name}")
        try:
            result = await asyncio.wait_for(spec.handler(payload), timeout=spec.timeout_seconds)
        except Exception:
            spec.breaker.record_failure()
            raise
        spec.breaker.record_success()
        return result
