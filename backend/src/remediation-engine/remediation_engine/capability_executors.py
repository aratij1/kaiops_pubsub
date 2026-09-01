from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, ClassVar, Literal
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from common.capability_registry import CapabilityRegistry, default_capability_registry


ExecutionPhase = Literal["dry_run", "precheck", "execute", "validate", "rollback"]


class CapabilityExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    incident_id: str
    capability_id: str
    connector_id: str
    target_resource_id: str
    target_identity_verified: bool
    environment: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    secret_ref: str
    idempotency_key: str
    timeout_seconds: float = Field(default=30.0, gt=0, le=900)
    max_attempts: int = Field(default=1, ge=1, le=3)

    @field_validator(
        "tenant_id", "incident_id", "capability_id", "connector_id",
        "target_resource_id", "environment", "secret_ref", "idempotency_key",
    )
    @classmethod
    def required_text(cls, value: str) -> str:
        value = str(value or "").strip()
        if not value:
            raise ValueError("capability execution identity cannot be empty")
        return value

    @model_validator(mode="after")
    def enforce_governed_input(self) -> "CapabilityExecutionRequest":
        if not self.target_identity_verified:
            raise ValueError("connector execution requires a Digital Twin verified target")
        if not self.target_resource_id.startswith(("dt://", "urn:", "arn:", "k8s://", "/subscriptions/")):
            raise ValueError("target_resource_id is not a stable resource identity")
        if not self.secret_ref.startswith((
            "env://", "vault://", "managed-identity://", "k8s-secret://",
            "gcp-secret://", "arn:aws:secretsmanager:", "https://",
        )):
            raise ValueError("secret_ref must be an opaque provider reference")
        forbidden = {"command", "commands", "script", "scripts", "shell", "sql", "query"}
        if any(str(key).lower() in forbidden for key in self.parameters):
            raise ValueError("arbitrary command-shaped capability parameters are forbidden")
        return self


class CapabilityExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phase: ExecutionPhase
    capability_id: str
    connector_id: str
    target_resource_id: str
    idempotency_key: str
    succeeded: bool
    executed: bool
    attempt_count: int
    status_code: int | None = None
    execution_reference: str | None = None
    summary: str
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


@dataclass
class GovernedConnectorExecutor:
    """Calls a deterministic connector control plane; it never invokes a shell."""

    connector_endpoint: str
    client: httpx.AsyncClient
    registry: CapabilityRegistry = field(default_factory=default_capability_registry)
    failure_threshold: int = 3
    _failures: int = 0
    _open: bool = False
    _results: dict[tuple[str, ExecutionPhase], CapabilityExecutionResult] = field(default_factory=dict)
    audit_trail: list[dict[str, Any]] = field(default_factory=list)

    supported_capabilities: ClassVar[frozenset[str]] = frozenset()
    connector_kind: ClassVar[str] = "connector"

    async def dry_run(self, request: CapabilityExecutionRequest) -> CapabilityExecutionResult:
        return await self._invoke("dry_run", request)

    async def precheck(self, request: CapabilityExecutionRequest) -> CapabilityExecutionResult:
        return await self._invoke("precheck", request)

    async def execute(self, request: CapabilityExecutionRequest) -> CapabilityExecutionResult:
        return await self._invoke("execute", request)

    async def validate(self, request: CapabilityExecutionRequest) -> CapabilityExecutionResult:
        return await self._invoke("validate", request)

    async def rollback(self, request: CapabilityExecutionRequest) -> CapabilityExecutionResult:
        capability = self.registry.get(request.capability_id)
        if not capability.rollback_capability:
            return self._local_failure("rollback", request, "registered capability has no rollback")
        return await self._invoke("rollback", request)

    def _authorize(self, request: CapabilityExecutionRequest) -> None:
        if request.capability_id not in self.supported_capabilities:
            raise ValueError(f"{self.connector_kind} executor does not support {request.capability_id}")
        capability = self.registry.get(request.capability_id)
        if request.connector_id not in capability.supported_connectors:
            raise ValueError("connector does not match the registered capability")
        environment = {"prod": "production", "dev": "development"}.get(request.environment, request.environment)
        if environment not in capability.allowed_environments:
            raise ValueError("capability is not allowed in the requested environment")

    async def _invoke(self, phase: ExecutionPhase, request: CapabilityExecutionRequest) -> CapabilityExecutionResult:
        self._authorize(request)
        cache_key = (request.idempotency_key, phase)
        if cache_key in self._results:
            return self._results[cache_key]
        if self._open:
            return self._local_failure(phase, request, "connector circuit breaker is open")
        endpoint = (
            f"{self.connector_endpoint.rstrip('/')}/v1/capabilities/"
            f"{quote(request.capability_id, safe='')}/{phase}"
        )
        payload = {
            "tenant_id": request.tenant_id,
            "incident_id": request.incident_id,
            "connector_id": request.connector_id,
            "target_resource_id": request.target_resource_id,
            "parameters": request.parameters,
            "secret_ref": request.secret_ref,
            "idempotency_key": request.idempotency_key,
        }
        last_summary = "connector request failed"
        status_code: int | None = None
        for attempt in range(1, request.max_attempts + 1):
            try:
                response = await self.client.post(endpoint, json=payload, timeout=request.timeout_seconds)
                status_code = response.status_code
                body = response.json() if response.content else {}
                if response.is_success and bool(body.get("succeeded")):
                    result = CapabilityExecutionResult(
                        phase=phase,
                        capability_id=request.capability_id,
                        connector_id=request.connector_id,
                        target_resource_id=request.target_resource_id,
                        idempotency_key=request.idempotency_key,
                        succeeded=True,
                        executed=phase in {"execute", "rollback"} and bool(body.get("executed")),
                        attempt_count=attempt,
                        status_code=status_code,
                        execution_reference=str(body.get("execution_reference") or "") or None,
                        summary=str(body.get("summary") or f"{phase} succeeded"),
                    )
                    self._failures = 0
                    self._results[cache_key] = result
                    self._audit(result)
                    return result
                last_summary = str(body.get("detail") or body.get("summary") or f"connector returned HTTP {status_code}")
                if status_code < 500:
                    break
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_summary = f"{type(exc).__name__}: connector unavailable"
            if attempt < request.max_attempts:
                await asyncio.sleep(min(0.25 * (2 ** (attempt - 1)), 1.0))
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._open = True
        result = CapabilityExecutionResult(
            phase=phase,
            capability_id=request.capability_id,
            connector_id=request.connector_id,
            target_resource_id=request.target_resource_id,
            idempotency_key=request.idempotency_key,
            succeeded=False,
            executed=False,
            attempt_count=attempt,
            status_code=status_code,
            summary=last_summary,
        )
        self._results[cache_key] = result
        self._audit(result)
        return result

    def _local_failure(
        self, phase: ExecutionPhase, request: CapabilityExecutionRequest, summary: str,
    ) -> CapabilityExecutionResult:
        result = CapabilityExecutionResult(
            phase=phase, capability_id=request.capability_id, connector_id=request.connector_id,
            target_resource_id=request.target_resource_id, idempotency_key=request.idempotency_key,
            succeeded=False, executed=False, attempt_count=0, summary=summary,
        )
        self._audit(result)
        return result

    def _audit(self, result: CapabilityExecutionResult) -> None:
        self.audit_trail.append(result.model_dump(mode="json"))


class KubernetesConnectorExecutor(GovernedConnectorExecutor):
    connector_kind = "kubernetes"
    supported_capabilities = frozenset({
        "kubernetes.restart_workload", "kubernetes.rollback_deployment", "kubernetes.scale_workload",
    })


class AnsibleConnectorExecutor(GovernedConnectorExecutor):
    connector_kind = "ansible"
    supported_capabilities = frozenset({"linux.restart_service", "windows.restart_service"})


class JenkinsConnectorExecutor(GovernedConnectorExecutor):
    connector_kind = "jenkins"
    supported_capabilities = frozenset({"jenkins.rollback_deployment"})


class TerraformConnectorExecutor(GovernedConnectorExecutor):
    connector_kind = "terraform"
    supported_capabilities = frozenset({"terraform.rollback"})


class DatabaseDiagnosticExecutor(GovernedConnectorExecutor):
    connector_kind = "database"
    supported_capabilities = frozenset({"database.collect_diagnostics"})

    async def rollback(self, request: CapabilityExecutionRequest) -> CapabilityExecutionResult:
        return self._local_failure("rollback", request, "read-only diagnostics do not require rollback")


class ApiConnectorExecutor(GovernedConnectorExecutor):
    connector_kind = "api"
    supported_capabilities = frozenset({"application.invoke_recovery_endpoint"})
