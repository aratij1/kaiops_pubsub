from __future__ import annotations

import pytest
import httpx
from common.models import Approval, ApprovalDecision, RemediationStatus
from remediation_engine.plugins import JenkinsRollbackPlugin, RemediationEngine


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

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/crumbIssuer/api/json"):
            return httpx.Response(404)
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
