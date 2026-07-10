from __future__ import annotations

import pytest
from common.models import Approval, ApprovalDecision, RemediationStatus
from remediation_engine.plugins import RemediationEngine


@pytest.mark.asyncio
async def test_remediation_engine_registers_tool_specs() -> None:
    engine = RemediationEngine()

    assert "rollback_deployment" in engine.tool_registry.tools
    assert "restart_pod" in engine.tool_registry.tools
    assert "api_execution" in engine.tool_registry.tools


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

    assert result.status == RemediationStatus.SUCCEEDED
    assert "executed" in result.output


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
