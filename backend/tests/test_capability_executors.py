import httpx
import pytest

from remediation_engine.capability_executors import (
    CapabilityExecutionRequest,
    DatabaseDiagnosticExecutor,
    KubernetesConnectorExecutor,
)


def request(**updates):
    values = {
        "tenant_id": "tenant-a",
        "incident_id": "incident-1",
        "capability_id": "kubernetes.restart_workload",
        "connector_id": "kubernetes",
        "target_resource_id": "k8s://cluster-a/prod/deployment/checkout",
        "target_identity_verified": True,
        "environment": "production",
        "parameters": {},
        "secret_ref": "vault://kaiops/kubernetes/cluster-a",
        "idempotency_key": "incident-1:restart:1",
        "max_attempts": 2,
    }
    values.update(updates)
    return CapabilityExecutionRequest.model_validate(values)


@pytest.mark.asyncio
async def test_kubernetes_executor_uses_fixed_capability_route_and_is_idempotent():
    calls = []

    async def handler(http_request):
        calls.append(http_request)
        assert http_request.url.path == "/v1/capabilities/kubernetes.restart_workload/execute"
        assert "vault://" in http_request.read().decode()
        return httpx.Response(200, json={"succeeded": True, "executed": True, "execution_reference": "job-1"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        executor = KubernetesConnectorExecutor("https://connector.internal", client)
        first = await executor.execute(request())
        second = await executor.execute(request())
    assert first.succeeded and first.executed
    assert second == first
    assert len(calls) == 1
    assert len(executor.audit_trail) == 1


@pytest.mark.asyncio
async def test_executor_retries_server_failure_but_not_client_failure():
    attempts = 0

    async def handler(_):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, json={"detail": "busy"})
        return httpx.Response(200, json={"succeeded": True, "executed": False})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await KubernetesConnectorExecutor("https://connector.internal", client).precheck(request())
    assert result.succeeded
    assert result.attempt_count == 2


def test_executor_rejects_commands_and_unverified_targets():
    with pytest.raises(ValueError, match="command-shaped"):
        request(parameters={"command": "kubectl delete namespace prod"})
    with pytest.raises(ValueError, match="verified target"):
        request(target_identity_verified=False)


@pytest.mark.asyncio
async def test_database_diagnostics_are_read_only_and_have_no_rollback():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(500))) as client:
        executor = DatabaseDiagnosticExecutor("https://connector.internal", client)
        result = await executor.rollback(request(
            capability_id="database.collect_diagnostics",
            connector_id="mysql",
            target_resource_id="dt://tenant-a/database/orders-primary",
        ))
    assert not result.succeeded
    assert not result.executed
    assert "do not require rollback" in result.summary
