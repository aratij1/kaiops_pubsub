from __future__ import annotations

from uuid import uuid4

import pytest

from common.cloud_operations.connectors import connector_for
from common.cloud_operations.events import SCHEMA_VERSION, build_cloud_event
from common.cloud_operations.models import CloudConnection, CloudConnectionCreate, DiscoveryRequest, ProviderType, ServiceOnboardingProfile
from common.cloud_operations.repository import CloudOperationsRepository


def test_non_simulator_connection_requires_credential_reference() -> None:
    with pytest.raises(ValueError, match="credential_ref"):
        CloudConnectionCreate(
            tenant_id="tenant-a",
            project_id="project-a",
            connection_name="aws-prod",
            provider_type=ProviderType.AWS,
            connection_owner="admin@example.com",
        )


@pytest.mark.asyncio
async def test_simulator_connector_returns_service_topology() -> None:
    connection = CloudConnection(
        tenant_id="tenant-a",
        project_id="project-a",
        connection_name="simulator",
        provider_type=ProviderType.SIMULATOR,
        credential_ref="simulator://local/read-only",
        connection_owner="admin@example.com",
        allowed_regions=["global"],
    )
    request = DiscoveryRequest(
        tenant_id="tenant-a",
        project_id="project-a",
        service_id="checkout-api",
        environment="prod",
    )

    result = await connector_for(ProviderType.SIMULATOR).discover_resources(connection, request)

    assert {resource.resource_type for resource in result.resources} == {"application", "database", "kubernetes_deployment"}
    assert {resource.service_id for resource in result.resources} == {"checkout-api"}
    assert [relationship.relationship_type for relationship in result.relationships] == ["service_to_workload", "workload_to_database"]


def test_cloud_event_envelope_is_versioned_and_tenant_scoped() -> None:
    event = build_cloud_event(
        event_type="cloud.connection.validated",
        tenant_id="tenant-a",
        project_id="project-a",
        service_id=None,
        payload={"connection_id": "connection-1"},
        producer="cloud-operations-test",
    )

    assert event["schema_version"] == SCHEMA_VERSION
    assert event["tenant_id"] == "tenant-a"
    assert event["payload"]["connection_id"] == "connection-1"
    assert event["idempotency_key"]


@pytest.mark.asyncio
async def test_repository_round_trip_discovers_and_maps_resources(sqlite_session_factory) -> None:
    async with sqlite_session_factory() as session:
        repo = CloudOperationsRepository(session)
        connection_row = await repo.create_connection(
            CloudConnectionCreate(
                tenant_id="tenant-a",
                project_id="project-a",
                connection_name="simulator",
                provider_type=ProviderType.SIMULATOR,
                credential_ref="simulator://local/read-only",
                connection_owner="admin@example.com",
                allowed_regions=["global"],
            )
        )
        connection = CloudConnection.model_validate(repo.connection_payload(connection_row))

        validation = await connector_for(ProviderType.SIMULATOR).validate_connection(connection)
        await repo.record_validation(connection_row, validation, actor="admin@example.com")

        request = DiscoveryRequest(
            tenant_id="tenant-a",
            project_id="project-a",
            service_id="checkout-api",
            environment="prod",
            actor="admin@example.com",
        )
        run = await repo.start_discovery(connection_row, request)
        discovery = await connector_for(ProviderType.SIMULATOR).discover_resources(connection, request)
        await repo.complete_discovery(connection_row, run, discovery, request=request)
        await repo.map_service(
            tenant_id="tenant-a",
            project_id="project-a",
            service_id="checkout-api",
            environment="prod",
            resource_ids=[str(resource.id) for resource in discovery.resources],
            owner="admin@example.com",
        )

        service_view = await repo.service_360(tenant_id="tenant-a", project_id="project-a", service_id="checkout-api", environment="prod")
        assert service_view["health"] == {"healthy": 3}
        assert len(service_view["relationships"]) == 2
        await session.commit()

    async with sqlite_session_factory() as session:
        repo = CloudOperationsRepository(session)
        assert await repo.get_connection(connection_id=uuid4(), tenant_id="tenant-a") is None


@pytest.mark.asyncio
async def test_service_onboarding_calculates_readiness_and_cockpit(sqlite_session_factory) -> None:
    async with sqlite_session_factory() as session:
        repo = CloudOperationsRepository(session)
        connection_row = await repo.create_connection(
            CloudConnectionCreate(
                tenant_id="tenant-a",
                project_id="project-a",
                connection_name="simulator",
                provider_type=ProviderType.SIMULATOR,
                credential_ref="simulator://local/read-only",
                connection_owner="admin@example.com",
                allowed_regions=["global"],
            )
        )
        connection = CloudConnection.model_validate(repo.connection_payload(connection_row))
        await repo.record_validation(connection_row, await connector_for(ProviderType.SIMULATOR).validate_connection(connection), actor="admin@example.com")
        request = DiscoveryRequest(tenant_id="tenant-a", project_id="project-a", service_id="checkout-api", environment="prod", actor="admin@example.com")
        run = await repo.start_discovery(connection_row, request)
        discovery = await connector_for(ProviderType.SIMULATOR).discover_resources(connection, request)
        await repo.complete_discovery(connection_row, run, discovery, request=request)

        await repo.upsert_service_onboarding(
            ServiceOnboardingProfile(
                tenant_id="tenant-a",
                project_id="project-a",
                service_id="checkout-api",
                environment="prod",
                template_id="kubernetes_microservice",
                business_criticality="high",
                owners=["checkout-oncall@example.com"],
                support_groups=["checkout-platform"],
                connection_ids=[str(connection_row.id)],
                monitoring_sources=["prometheus"],
                log_sources=["opensearch"],
                metric_sources=["prometheus"],
                slos=[{"name": "availability", "target": "99.9"}],
                knowledge_refs=["checkout-runbook"],
                diagnostic_capabilities=["read_pod_status"],
                remediation_capabilities=["restart_kubernetes_deployment"],
                validation_rules=["http_health_check"],
                escalation_policies=["primary-oncall"],
                hitl_policy={"required_for": ["production"]},
                actor="admin@example.com",
            )
        )
        score = await repo.recalculate_readiness(tenant_id="tenant-a", project_id="project-a", service_id="checkout-api", environment="prod", actor="admin@example.com")
        cockpit = await repo.cockpit(tenant_id="tenant-a", project_id="project-a")
        topology = await repo.topology(tenant_id="tenant-a", project_id="project-a", service_id="checkout-api", environment="prod")

        assert score.readiness_state == "OPERABLE"
        assert float(score.overall_score) >= 0.82
        assert cockpit["resource_count"] == 3
        assert cockpit["readiness"][0]["service_id"] == "checkout-api"
        assert len(topology["nodes"]) == 3
        assert len(topology["edges"]) == 2
