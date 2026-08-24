from __future__ import annotations

from uuid import uuid4
from datetime import timedelta

import pytest

from common.cloud_operations.connectors import AzurePilotConnector, connector_for
from common.cloud_operations.events import SCHEMA_VERSION, build_cloud_event
from common.cloud_operations.models import CloudConnection, CloudConnectionCreate, CompiledPlan, DiscoveryRequest, ExecutionPolicy, MaintenanceWindow, PlanAction, PlanApprovalRequest, PlanCompileRequest, ProviderType, ServiceOnboardingProfile
from common.models import utc_now
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


def test_compiled_plan_checksum_is_deterministic_and_requires_production_approval() -> None:
    request = PlanCompileRequest(
        tenant_id="tenant-a", project_id="project-a", service_id="checkout-api", environment="prod",
        intent="Restore checkout capacity",
        actions=[PlanAction(action_type="restart_kubernetes_deployment", resource_id="resource-1", rollback_action="restore_previous_replica_set")],
        actor="admin@example.com",
    )
    first = CompiledPlan.from_request(request, risk_level="high")
    second = CompiledPlan.from_request(request, risk_level="high")
    assert first.checksum == second.checksum
    assert first.requires_approval is True


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
        assert all(resource["canonical_resource_id"].startswith("urn:kaims:simulator:") for resource in service_view["resources"])
        root_resource_id = service_view["relationships"][0]["source_resource_id"]
        traversal = await repo.dependency_traversal(
            tenant_id="tenant-a",
            project_id="project-a",
            resource_id=root_resource_id,
            direction="outbound",
        )
        assert root_resource_id in traversal["resource_ids"]
        assert traversal["relationships"]
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

        plan = await repo.compile_plan(
            PlanCompileRequest(
                tenant_id="tenant-a", project_id="project-a", service_id="checkout-api", environment="prod",
                intent="Restore checkout capacity",
                actions=[PlanAction(action_type="restart_kubernetes_deployment", resource_id=str(discovery.resources[0].id), rollback_action="restore_previous_replica_set")],
                actor="admin@example.com",
            )
        )
        duplicate = await repo.compile_plan(
            PlanCompileRequest(
                tenant_id="tenant-a", project_id="project-a", service_id="checkout-api", environment="prod",
                intent="Restore checkout capacity",
                actions=[PlanAction(action_type="restart_kubernetes_deployment", resource_id=str(discovery.resources[0].id), rollback_action="restore_previous_replica_set")],
                actor="admin@example.com",
            )
        )
        simulation = await repo.simulate_plan(plan, actor="admin@example.com")

        assert score.readiness_state == "OPERABLE"
        assert float(score.overall_score) >= 0.82
        assert cockpit["resource_count"] == 3
        assert cockpit["readiness"][0]["service_id"] == "checkout-api"
        assert cockpit["readiness"][0]["dimensions"]["monitoring"] == 1.0
        assert cockpit["readiness"][0]["dimensions"]["logs"] == 1.0
        assert cockpit["readiness"][0]["dimensions"]["traces"] == 0.0
        assert any(gap["dimension"] == "traces" for gap in cockpit["readiness"][0]["gaps"])
        assert len(topology["nodes"]) == 3
        assert len(topology["edges"]) == 2
        assert duplicate.id == plan.id
        assert simulation.verdict == "blocked"
        assert any(gate["gate"] == "human_approval" and not gate["passed"] for gate in simulation.gates)

        with pytest.raises(ValueError, match="checksum"):
            await repo.approve_plan(plan, PlanApprovalRequest(tenant_id="tenant-a", checksum="0" * 64, decision="approved", reason="reviewed", actor="admin@example.com"))
        await repo.approve_plan(plan, PlanApprovalRequest(tenant_id="tenant-a", checksum=plan.checksum, decision="approved", reason="reviewed and safe", actor="admin@example.com"))
        approved_simulation = await repo.simulate_plan(plan, actor="admin@example.com")
        assert approved_simulation.verdict == "passed"
        policy = await repo.upsert_execution_policy(ExecutionPolicy(tenant_id="tenant-a", project_id="project-a", environment="prod", allowed_providers=[ProviderType.SIMULATOR], allowed_actions=["restart_kubernetes_deployment"], maximum_risk="high", require_maintenance_window=True, actor="admin@example.com"))
        assert policy.enabled is True
        now = utc_now()
        blocks = await repo.evaluate_execution_governance(plan, provider="simulator", at=now)
        assert "No active maintenance window exists" in blocks
        await repo.create_maintenance_window(MaintenanceWindow(tenant_id="tenant-a", project_id="project-a", environment="prod", starts_at=now - timedelta(minutes=5), ends_at=now + timedelta(minutes=30), reason="approved change", actor="admin@example.com"))
        assert await repo.evaluate_execution_governance(plan, provider="simulator", at=now) == []
        execution, acquired = await repo.acquire_execution(plan, actor="admin@example.com", provider="simulator")
        duplicate_execution, acquired_again = await repo.acquire_execution(plan, actor="admin@example.com", provider="simulator")
        assert acquired is True
        assert acquired_again is False
        assert duplicate_execution.id == execution.id
        execution.lease_expires_at = now - timedelta(minutes=1)
        assert await repo.recover_expired_leases(tenant_id="tenant-a", at=now) == 1
        assert execution.status == "failed"


@pytest.mark.asyncio
async def test_simulator_execution_adapter_supports_validation_and_rollback() -> None:
    connector = connector_for(ProviderType.SIMULATOR)
    action = {"action_type": "restart_kubernetes_deployment", "resource_id": "resource-1", "rollback_action": "restore_previous_replica_set", "parameters": {}}
    executed = await connector.execute_action(action=action, idempotency_key="plan:1")
    validation = await connector.validate_action(action=action)
    rolled_back = await connector.rollback_action(action=action, idempotency_key="plan:1:rollback")
    assert executed["status"] == "succeeded"
    assert validation["passed"] is True
    assert rolled_back["status"] == "rolled_back"


@pytest.mark.asyncio
async def test_azure_pilot_is_kill_switched_canary_scoped_and_rate_limited() -> None:
    calls: list[str] = []

    async def executor(operation: str, action: dict, idempotency_key: str) -> dict:
        calls.append(operation)
        return {"status": "succeeded", "passed": True, "operation": operation, "idempotency_key": idempotency_key}

    action = {"action_type": "restart_container_app_revision", "resource_id": "azure-canary-1", "rollback_action": "restore_container_app_revision", "parameters": {}}
    disabled = AzurePilotConnector(execution_enabled=True, kill_switch=True, canary_resource_ids={"azure-canary-1"}, executor=executor)
    with pytest.raises(ValueError, match="kill switch"):
        await disabled.execute_action(action=action, idempotency_key="azure:1")

    connector = AzurePilotConnector(execution_enabled=True, kill_switch=False, canary_resource_ids={"azure-canary-1"}, rate_limit_per_minute=2, executor=executor)
    with pytest.raises(ValueError, match="canary"):
        await connector.execute_action(action={**action, "resource_id": "azure-prod-2"}, idempotency_key="azure:outside")
    assert (await connector.execute_action(action=action, idempotency_key="azure:1"))["status"] == "succeeded"
    assert (await connector.rollback_action(action=action, idempotency_key="azure:rollback"))["status"] == "succeeded"
    with pytest.raises(ValueError, match="rate limit"):
        await connector.execute_action(action=action, idempotency_key="azure:2")
    assert calls == ["execute", "rollback"]


@pytest.mark.asyncio
async def test_azure_pilot_connection_requires_identity_reference() -> None:
    connector = AzurePilotConnector()
    connection = CloudConnection(tenant_id="tenant-a", project_id="project-a", connection_name="azure-pilot", provider_type=ProviderType.AZURE, credential_ref="plain-secret", connection_owner="admin@example.com")
    result = await connector.validate_connection(connection)
    assert result.status == "failed"
    assert "managed_identity_or_vault_reference" in result.missing_permissions
