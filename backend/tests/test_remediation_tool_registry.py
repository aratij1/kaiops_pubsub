from __future__ import annotations

import pytest
import httpx
from common.models import Approval, ApprovalDecision, RemediationStatus
from remediation_engine.plugins import AzureContainerAppsJobPlugin, JenkinsRollbackPlugin, RemediationEngine


@pytest.mark.asyncio
async def test_remediation_engine_registers_tool_specs() -> None:
    engine = RemediationEngine()

    assert "rollback_deployment" in engine.tool_registry.tools
    assert "restart_pod" in engine.tool_registry.tools
    assert "api_execution" in engine.tool_registry.tools
    assert "jenkins" in engine.tool_registry.tools


@pytest.mark.asyncio
async def test_selected_jenkins_executor_routes_non_rollback_actions_to_jenkins() -> None:
    engine = RemediationEngine()
    approval = Approval(
        incident_id="11111111-1111-1111-1111-111111111111",
        recommendation_id="22222222-2222-2222-2222-222222222222",
        decision=ApprovalDecision.APPROVED,
        approver="sre-user",
        comment="restart pod",
        metadata={"connection_profile": {"executor_type": "jenkins"}},
    )

    result = await engine.execute(engine.build_action(approval))

    assert result.status == RemediationStatus.SKIPPED
    assert result.parameters["execution_result"]["executor"] == "jenkins"


def test_default_jenkins_profile_is_applied_to_alerts_without_connector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REMEDIATION_DEFAULT_EXECUTOR", "jenkins")
    monkeypatch.setenv("REMEDIATION_JENKINS_URL", "http://jenkins:8080")
    monkeypatch.setenv("REMEDIATION_JENKINS_JOB", "kaiops-auto-remediation")
    monkeypatch.setenv("REMEDIATION_JENKINS_CREDENTIAL_REF", "vault://kaiops/local/jenkins#api-token")

    action = RemediationEngine().build_action(
        Approval(
            incident_id="11111111-1111-1111-1111-111111111111",
            recommendation_id="22222222-2222-2222-2222-222222222222",
            decision=ApprovalDecision.APPROVED,
            approver="sre-user",
            comment="restart pod",
        )
    )

    assert action.parameters["connection_profile"]["executor_type"] == "jenkins"
    assert action.parameters["connection_profile"]["endpoint_url"] == "http://jenkins:8080"
    assert action.parameters["connection_profile"]["job_name"] == "kaiops-auto-remediation"
    assert action.parameters["connection_profile"]["credential_ref"].startswith("vault://")


def test_jenkins_script_only_plan_receives_governed_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REMEDIATION_DEFAULT_EXECUTOR", "jenkins")
    monkeypatch.setenv("REMEDIATION_EXECUTION_PLATFORM", "docker-compose")
    action = RemediationEngine().build_action(
        Approval(
            incident_id="11111111-1111-1111-1111-111111111111",
            recommendation_id="22222222-2222-2222-2222-222222222222",
            decision=ApprovalDecision.APPROVED,
            approver="sre-user",
            comment="rollback deployment",
            metadata={
                "service": "api-gateway",
                "environment": "prod",
                "execution_plan": {
                    "commands": [],
                    "scripts": ["scripts/remediation/rollback_deployment.ps1 -Service api-gateway -Namespace prod"],
                    "queries": [],
                },
            },
        )
    )

    assert action.parameters["execution_plan"]["commands"]
    commands = action.parameters["execution_plan"]["commands"]
    assert "--retry 3 --retry-all-errors --retry-delay 1" in commands[0]
    assert commands[0].endswith("/containers/kaiops_azure-api-gateway-1/restart?t=30")
    assert commands[1].endswith("http://api-gateway:8000/healthz")
    assert action.parameters["execution_plan"]["queries"] == ["http://api-gateway:8000/healthz"]


@pytest.mark.asyncio
async def test_remediation_engine_executes_via_tool_registry() -> None:
    engine = RemediationEngine()
    approval = Approval(
        incident_id="11111111-1111-1111-1111-111111111111",
        recommendation_id="22222222-2222-2222-2222-222222222222",
        decision=ApprovalDecision.APPROVED,
        approver="sre-user",
        comment="restart pod",
    )
    action = engine.build_action(approval)

    result = await engine.execute(action)

    assert result.status == RemediationStatus.SKIPPED
    assert result.parameters["execution_result"]["executed"] is False
    assert result.parameters["execution_result"]["executor"] == "kubernetes"
    assert "No real kubernetes executor is configured" in str(result.error)
    assert "simulat" not in result.output.lower()


@pytest.mark.asyncio
async def test_tool_registry_permission_is_enforced() -> None:
    engine = RemediationEngine()
    action = engine.build_action(
        Approval(
            incident_id="11111111-1111-1111-1111-111111111111",
            recommendation_id="22222222-2222-2222-2222-222222222222",
            decision=ApprovalDecision.APPROVED,
            approver="sre-user",
            comment="rollback",
        )
    )

    with pytest.raises(PermissionError):
        await engine.tool_registry.execute(
            action.action_type,
            {"action": action.model_dump(mode="json")},
            role="viewer",
        )


@pytest.mark.asyncio
async def test_jenkins_rollback_requires_a_complete_connector() -> None:
    action = RemediationEngine().build_action(
        Approval(
            incident_id="11111111-1111-1111-1111-111111111111",
            recommendation_id="22222222-2222-2222-2222-222222222222",
            decision=ApprovalDecision.APPROVED,
            approver="sre-user",
            comment="rollback deployment",
            metadata={"connection_profile": {"endpoint_url": "https://jenkins.example.com"}},
        )
    )

    result = await JenkinsRollbackPlugin().execute(action)

    assert result.status == RemediationStatus.SKIPPED
    assert result.parameters["execution_result"]["executor"] == "jenkins"
    assert "No real jenkins executor is configured" in str(result.error)


@pytest.mark.asyncio
async def test_jenkins_rollback_requires_runtime_secret_injection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JENKINS_USERNAME", raising=False)
    monkeypatch.delenv("JENKINS_API_TOKEN", raising=False)
    action = RemediationEngine().build_action(
        Approval(
            incident_id="11111111-1111-1111-1111-111111111111",
            recommendation_id="22222222-2222-2222-2222-222222222222",
            decision=ApprovalDecision.APPROVED,
            approver="sre-user",
            comment="rollback deployment",
            metadata={"connection_profile": {
                "endpoint_url": "https://jenkins.example.com",
                "job_name": "payments/rollback",
                "credential_ref": "vault://kaiops/prod/jenkins",
                "allowed_operations": ["rollback_deployment"],
            }},
        )
    )

    result = await JenkinsRollbackPlugin().execute(action)

    assert result.status == RemediationStatus.SKIPPED
    assert "runtime secret provider" in str(result.error)


@pytest.mark.asyncio
async def test_jenkins_submits_application_resolution_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    submitted: dict[str, str] = {}
    build_polls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal build_polls
        if request.url.path.endswith("/crumbIssuer/api/json"):
            return httpx.Response(404)
        if request.url.path == "/queue/item/7/api/json":
            return httpx.Response(200, json={"cancelled": False, "executable": {"url": "https://jenkins.example/job/payments/7/"}})
        if request.url.path == "/job/payments/7/api/json":
            build_polls += 1
            if build_polls == 1:
                return httpx.Response(200, json={"building": False, "result": None})
            return httpx.Response(200, json={"building": False, "result": "SUCCESS"})
        submitted.update(dict(request.url.params))
        return httpx.Response(201, headers={"location": "https://jenkins.example/queue/item/7"})

    monkeypatch.setenv("JENKINS_USERNAME", "kaiops")
    monkeypatch.setenv("JENKINS_API_TOKEN", "secret")
    async_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: async_client(transport=httpx.MockTransport(handler), **kwargs))
    action = RemediationEngine().build_action(Approval(
        incident_id="11111111-1111-1111-1111-111111111111",
        recommendation_id="22222222-2222-2222-2222-222222222222",
        decision=ApprovalDecision.APPROVED,
        approver="sre-user",
        comment="restart pod",
        metadata={"connection_profile": {"executor_type": "jenkins", "endpoint_url": "https://jenkins.example", "job_name": "kaiops/remediation/payments", "credential_ref": "vault://jenkins"}},
    ))
    action.parameters.update({"application_id": "payments", "namespace": "prod-payments", "resolution_id": "restart-workload", "dry_run": True})

    result = await JenkinsRollbackPlugin().execute(action)

    assert result.status == RemediationStatus.SUCCEEDED
    assert submitted["KAI_OPS_APPLICATION_ID"] == "payments"
    assert submitted["KAI_OPS_NAMESPACE"] == "prod-payments"
    assert submitted["KAI_OPS_RESOLUTION_ID"] == "restart-workload"
    assert submitted["KAI_OPS_DRY_RUN"] == "true"
    assert result.parameters["execution_result"]["build_result"] == "SUCCESS"
    assert build_polls == 2


@pytest.mark.asyncio
async def test_jenkins_does_not_finalize_stale_result_while_building(monkeypatch: pytest.MonkeyPatch) -> None:
    build_polls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal build_polls
        if request.url.path.endswith("/crumbIssuer/api/json"):
            return httpx.Response(404)
        if request.url.path == "/queue/item/8/api/json":
            return httpx.Response(200, json={"cancelled": False, "executable": {"url": "/job/payments/8/"}})
        if request.url.path == "/job/payments/8/api/json":
            build_polls += 1
            if build_polls == 1:
                return httpx.Response(200, json={"building": True, "result": "FAILURE"})
            return httpx.Response(200, json={"building": False, "result": "SUCCESS"})
        return httpx.Response(201, headers={"location": "/queue/item/8/"})

    monkeypatch.setenv("JENKINS_USERNAME", "kaiops")
    monkeypatch.setenv("JENKINS_API_TOKEN", "secret")
    monkeypatch.setenv("REMEDIATION_JENKINS_POLL_SECONDS", "0.01")
    async_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: async_client(transport=httpx.MockTransport(handler), **kwargs))
    action = RemediationEngine().build_action(Approval(
        incident_id="11111111-1111-1111-1111-111111111111",
        recommendation_id="22222222-2222-2222-2222-222222222222",
        decision=ApprovalDecision.APPROVED,
        approver="sre-user",
        metadata={"connection_profile": {"executor_type": "jenkins", "endpoint_url": "https://jenkins.example", "job_name": "payments", "credential_ref": "vault://jenkins"}},
    ))

    result = await JenkinsRollbackPlugin().execute(action)

    assert result.status == RemediationStatus.SUCCEEDED
    assert result.parameters["execution_result"]["queue_url"] == "https://jenkins.example/queue/item/8/"
    assert result.parameters["execution_result"]["build_url"] == "https://jenkins.example/job/payments/8/"
    assert build_polls == 2


@pytest.mark.asyncio
async def test_jenkins_waits_until_queue_exposes_executable_url(monkeypatch: pytest.MonkeyPatch) -> None:
    queue_polls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal queue_polls
        if request.url.path.endswith("/crumbIssuer/api/json"):
            return httpx.Response(404)
        if request.url.path == "/queue/item/9/api/json":
            queue_polls += 1
            executable = {} if queue_polls == 1 else {"url": "/job/payments/9/"}
            return httpx.Response(200, json={"cancelled": False, "executable": executable})
        if request.url.path == "/job/payments/9/api/json":
            return httpx.Response(200, json={"building": False, "result": "SUCCESS"})
        if request.url.path == "/api/json":
            raise AssertionError("queue polling must not fall back to the Jenkins controller URL")
        return httpx.Response(201, headers={"location": "/queue/item/9/"})

    monkeypatch.setenv("JENKINS_USERNAME", "kaiops")
    monkeypatch.setenv("JENKINS_API_TOKEN", "secret")
    monkeypatch.setenv("REMEDIATION_JENKINS_POLL_SECONDS", "0.01")
    async_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: async_client(transport=httpx.MockTransport(handler), **kwargs))
    action = RemediationEngine().build_action(Approval(
        incident_id="11111111-1111-1111-1111-111111111111",
        recommendation_id="22222222-2222-2222-2222-222222222222",
        decision=ApprovalDecision.APPROVED,
        metadata={"connection_profile": {"endpoint_url": "https://jenkins.example", "job_name": "payments", "credential_ref": "vault://jenkins"}},
    ))

    result = await JenkinsRollbackPlugin().execute(action)

    assert result.status == RemediationStatus.SUCCEEDED
    assert queue_polls == 2
    assert result.parameters["execution_result"]["build_url"] == "https://jenkins.example/job/payments/9/"


def test_jenkins_registry_timeout_exceeds_connector_maximum() -> None:
    engine = RemediationEngine()
    assert engine.tool_registry.tools["jenkins"].timeout_seconds > 900


def test_jenkins_rewrites_advertised_browser_origin_to_connector_origin() -> None:
    assert JenkinsRollbackPlugin._connector_url(
        "http://jenkins:8080",
        "http://localhost:8082/job/kaiops-auto-remediation/27/",
    ) == "http://jenkins:8080/job/kaiops-auto-remediation/27/"


@pytest.mark.asyncio
async def test_azure_container_apps_job_uses_managed_identity_and_waits_for_terminal_status(monkeypatch: pytest.MonkeyPatch) -> None:
    polls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal polls
        if request.url.host == "identity.local":
            assert request.headers["X-IDENTITY-HEADER"] == "identity-secret"
            return httpx.Response(200, json={"access_token": "managed-token"})
        assert request.headers["Authorization"] == "Bearer managed-token"
        if request.method == "POST":
            return httpx.Response(200, json={"name": "execution-42"})
        polls += 1
        status = "Running" if polls == 1 else "Succeeded"
        return httpx.Response(200, json={"properties": {"status": status}})

    monkeypatch.setenv("IDENTITY_ENDPOINT", "http://identity.local/token")
    monkeypatch.setenv("IDENTITY_HEADER", "identity-secret")
    monkeypatch.setenv("REMEDIATION_ACA_POLL_SECONDS", "0.01")
    async_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: async_client(transport=httpx.MockTransport(handler), **kwargs))
    action = RemediationEngine().build_action(Approval(
        incident_id="11111111-1111-1111-1111-111111111111",
        recommendation_id="22222222-2222-2222-2222-222222222222",
        decision=ApprovalDecision.APPROVED,
        approver="sre-user",
        metadata={
            "service": "payments",
            "connection_profile": {
                "executor_type": "azure_container_apps_job",
                "subscription_id": "sub-1",
                "resource_group": "rg-1",
                "job_name": "kaiops-remediation",
            },
        },
    ))

    result = await AzureContainerAppsJobPlugin().execute(action)

    assert result.status == RemediationStatus.SUCCEEDED
    assert result.parameters["execution_result"]["executor"] == "azure_container_apps_job"
    assert result.parameters["execution_result"]["execution_id"] == "execution-42"
    assert polls == 2
