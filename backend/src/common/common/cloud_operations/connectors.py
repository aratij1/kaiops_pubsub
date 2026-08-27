from __future__ import annotations

from typing import Any, Awaitable, Callable, Protocol
from collections import deque
from time import monotonic
from uuid import uuid5, NAMESPACE_URL

from common.cloud_operations.models import (
    CapabilityManifest,
    CloudConnection,
    ConnectionValidationResult,
    DiscoveredResource,
    DiscoveryRequest,
    DiscoveryResult,
    DiscoveryStatus,
    ProviderType,
    ResourceRelationship,
)


class CloudConnector(Protocol):
    def list_capabilities(self) -> CapabilityManifest: ...

    async def validate_connection(self, connection: CloudConnection) -> ConnectionValidationResult: ...

    async def discover_resources(self, connection: CloudConnection, request: DiscoveryRequest) -> DiscoveryResult: ...
    async def execute_action(self, *, action: dict[str, Any], idempotency_key: str) -> dict[str, Any]: ...
    async def rollback_action(self, *, action: dict[str, Any], idempotency_key: str) -> dict[str, Any]: ...
    async def validate_action(self, *, action: dict[str, Any]) -> dict[str, Any]: ...


class SimulatorConnector:
    def list_capabilities(self) -> CapabilityManifest:
        return CapabilityManifest(
            provider=ProviderType.SIMULATOR,
            connector_version="simulator-v1",
            resource_types=["application", "api", "kubernetes_deployment", "database", "queue"],
            supported_read_operations=["validate_connection", "discover_resources", "get_health", "get_metrics"],
            supported_write_operations=["restart_kubernetes_deployment"],
            required_permission_scopes=["simulator.read"],
            risk_classification="low",
            dry_run_support=True,
            rollback_support=True,
            validation_support=True,
            health_status="healthy",
        )

    async def validate_connection(self, connection: CloudConnection) -> ConnectionValidationResult:
        requested = ["simulator.read"]
        granted = ["simulator.read"] if connection.read_capability else []
        missing = sorted(set(requested) - set(granted))
        ok = not missing and connection.status != "disabled"
        return ConnectionValidationResult(
            status="validated" if ok else "failed",
            connectivity_ok=ok,
            authentication_ok=ok,
            requested_permissions=requested,
            granted_permissions=granted,
            missing_permissions=missing,
            read_only=not connection.write_capability,
            message="Simulator connection is read-only and ready." if ok else "Simulator read permission is missing.",
        )

    async def discover_resources(self, connection: CloudConnection, request: DiscoveryRequest) -> DiscoveryResult:
        account = f"{connection.provider_type}:{connection.project_id}"
        region = (connection.allowed_regions or ["global"])[0]

        def rid(kind: str, name: str) -> str:
            return f"simulator://{request.project_id}/{request.environment}/{request.service_id}/{kind}/{name}"

        resources = [
            DiscoveredResource(
                id=uuid5(NAMESPACE_URL, rid("application", request.service_id)),
                tenant_id=request.tenant_id,
                project_id=request.project_id,
                connection_id=connection.id,
                service_id=request.service_id,
                environment=request.environment,
                provider=ProviderType.SIMULATOR,
                provider_account_id=account,
                region=region,
                provider_resource_id=rid("application", request.service_id),
                resource_type="application",
                display_name=request.service_id,
                owner=connection.connection_owner,
                health={"status": "healthy", "source": "simulator"},
                cost={"monthly_estimate": 128.0, "currency": "USD"},
                tags={"managed_by": "kaims", "simulated": True},
            ),
            DiscoveredResource(
                id=uuid5(NAMESPACE_URL, rid("kubernetes_deployment", f"{request.service_id}-api")),
                tenant_id=request.tenant_id,
                project_id=request.project_id,
                connection_id=connection.id,
                service_id=request.service_id,
                environment=request.environment,
                provider=ProviderType.SIMULATOR,
                provider_account_id=account,
                region=region,
                provider_resource_id=rid("kubernetes_deployment", f"{request.service_id}-api"),
                resource_type="kubernetes_deployment",
                display_name=f"{request.service_id}-api",
                owner=connection.connection_owner,
                health={"status": "healthy", "ready_replicas": 3, "desired_replicas": 3},
                tags={"tier": "api"},
            ),
            DiscoveredResource(
                id=uuid5(NAMESPACE_URL, rid("database", f"{request.service_id}-mysql")),
                tenant_id=request.tenant_id,
                project_id=request.project_id,
                connection_id=connection.id,
                service_id=request.service_id,
                environment=request.environment,
                provider=ProviderType.SIMULATOR,
                provider_account_id=account,
                region=region,
                provider_resource_id=rid("database", f"{request.service_id}-mysql"),
                resource_type="database",
                display_name=f"{request.service_id}-mysql",
                owner=connection.connection_owner,
                health={"status": "healthy", "replication_lag_seconds": 0},
                tags={"tier": "data"},
            ),
        ]
        relationships = [
            ResourceRelationship(
                tenant_id=request.tenant_id,
                project_id=request.project_id,
                connection_id=connection.id,
                source_resource_id=str(resources[0].id),
                target_resource_id=str(resources[1].id),
                relationship_type="service_to_workload",
                source="simulator.discovery",
                confidence=0.98,
                owner_confirmed=False,
            ),
            ResourceRelationship(
                tenant_id=request.tenant_id,
                project_id=request.project_id,
                connection_id=connection.id,
                source_resource_id=str(resources[1].id),
                target_resource_id=str(resources[2].id),
                relationship_type="workload_to_database",
                source="simulator.discovery",
                confidence=0.92,
                owner_confirmed=False,
            ),
        ]
        return DiscoveryResult(
            run_id=uuid5(NAMESPACE_URL, f"discovery:{request.tenant_id}:{request.project_id}:{request.service_id}:{connection.id}"),
            status=DiscoveryStatus.COMPLETED,
            resources=resources,
            relationships=relationships,
            message=f"Discovered {len(resources)} simulator resource(s).",
        )

    async def execute_action(self, *, action: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        if str(action.get("action_type") or "") not in self.list_capabilities().supported_write_operations:
            raise ValueError("Simulator action is not in the connector capability manifest")
        return {"status": "succeeded", "resource_id": action["resource_id"], "action_type": action["action_type"], "idempotency_key": idempotency_key, "simulated": True}

    async def rollback_action(self, *, action: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        if not str(action.get("rollback_action") or "").strip():
            raise ValueError("Approved plan action has no rollback action")
        return {"status": "rolled_back", "resource_id": action["resource_id"], "rollback_action": action["rollback_action"], "idempotency_key": idempotency_key, "simulated": True}

    async def validate_action(self, *, action: dict[str, Any]) -> dict[str, Any]:
        return {"passed": True, "resource_id": action["resource_id"], "checks": ["resource_reachable", "desired_state_observed"], "simulated": True}


AzureExecutor = Callable[[str, dict[str, Any], str], Awaitable[dict[str, Any]]]


class AzurePilotConnector:
    """Canary-only Azure adapter. Live mutation requires an injected managed executor."""

    def __init__(self, *, execution_enabled: bool = False, kill_switch: bool = True, canary_resource_ids: set[str] | None = None, rate_limit_per_minute: int = 2, executor: AzureExecutor | None = None) -> None:
        self.execution_enabled = execution_enabled
        self.kill_switch = kill_switch
        self.canary_resource_ids = canary_resource_ids or set()
        self.rate_limit_per_minute = rate_limit_per_minute
        self.executor = executor
        self._attempts: deque[float] = deque()

    def list_capabilities(self) -> CapabilityManifest:
        return CapabilityManifest(
            provider=ProviderType.AZURE, connector_version="azure-pilot-v1",
            resource_types=["azure_container_app", "azure_container_app_revision"],
            supported_read_operations=["validate_connection", "get_revision_health"],
            supported_write_operations=["restart_container_app_revision"],
            required_permission_scopes=["Microsoft.App/containerApps/read", "Microsoft.App/containerApps/revisions/read", "Microsoft.App/containerApps/revisions/restart/action"],
            risk_classification="high", dry_run_support=True, rollback_support=True, validation_support=True,
            health_status="disabled" if not self.execution_enabled or self.kill_switch else "canary",
        )

    async def validate_connection(self, connection: CloudConnection) -> ConnectionValidationResult:
        reference_ok = connection.credential_ref.startswith(("managed-identity://", "vault://"))
        missing = [] if reference_ok else ["managed_identity_or_vault_reference"]
        return ConnectionValidationResult(
            status="validated" if reference_ok and connection.read_capability else "failed",
            connectivity_ok=reference_ok, authentication_ok=reference_ok,
            requested_permissions=self.list_capabilities().required_permission_scopes,
            granted_permissions=self.list_capabilities().required_permission_scopes if reference_ok else [],
            missing_permissions=missing, read_only=not connection.write_capability,
            message="Azure pilot identity reference passed structural validation; live permission proof is still required." if reference_ok else "Azure pilot requires a managed-identity or vault credential reference.",
        )

    async def discover_resources(self, connection: CloudConnection, request: DiscoveryRequest) -> DiscoveryResult:
        raise NotImplementedError("Azure pilot discovery requires the certified external executor")

    def _authorize(self, action: dict[str, Any]) -> None:
        if not self.execution_enabled:
            raise ValueError("Azure pilot execution flag is disabled")
        if self.kill_switch:
            raise ValueError("Azure pilot kill switch is engaged")
        if str(action.get("resource_id") or "") not in self.canary_resource_ids:
            raise ValueError("Azure target is outside the certified canary scope")
        if str(action.get("action_type") or "") not in self.list_capabilities().supported_write_operations:
            raise ValueError("Azure action is outside the certified capability manifest")
        now = monotonic()
        while self._attempts and now - self._attempts[0] >= 60:
            self._attempts.popleft()
        if len(self._attempts) >= self.rate_limit_per_minute:
            raise ValueError("Azure pilot rate limit exceeded")
        if self.executor is None:
            raise ValueError("Azure managed executor is not configured")
        self._attempts.append(now)

    async def execute_action(self, *, action: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        self._authorize(action)
        return await self.executor("execute", action, idempotency_key)  # type: ignore[misc]

    async def rollback_action(self, *, action: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        self._authorize(action)
        if str(action.get("rollback_action") or "") != "restore_container_app_revision":
            raise ValueError("Azure rollback is outside the certified capability manifest")
        return await self.executor("rollback", action, idempotency_key)  # type: ignore[misc]

    async def validate_action(self, *, action: dict[str, Any]) -> dict[str, Any]:
        if self.executor is None:
            raise ValueError("Azure managed executor is not configured")
        return await self.executor("validate", action, "validation")


def connector_for(provider: ProviderType, **options: Any) -> CloudConnector:
    if provider == ProviderType.SIMULATOR:
        return SimulatorConnector()
    if provider == ProviderType.AZURE:
        return AzurePilotConnector(**options)
    raise NotImplementedError(f"{provider.value} connector is registered but not enabled for live use")
