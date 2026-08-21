from __future__ import annotations

from typing import Protocol
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


class SimulatorConnector:
    def list_capabilities(self) -> CapabilityManifest:
        return CapabilityManifest(
            provider=ProviderType.SIMULATOR,
            connector_version="simulator-v1",
            resource_types=["application", "api", "kubernetes_deployment", "database", "queue"],
            supported_read_operations=["validate_connection", "discover_resources", "get_health", "get_metrics"],
            supported_write_operations=[],
            required_permission_scopes=["simulator.read"],
            risk_classification="low",
            dry_run_support=True,
            rollback_support=False,
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


def connector_for(provider: ProviderType) -> CloudConnector:
    if provider == ProviderType.SIMULATOR:
        return SimulatorConnector()
    raise NotImplementedError(f"{provider.value} connector is registered but not enabled for live use")
