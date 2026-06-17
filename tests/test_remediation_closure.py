import pytest
from closure_service import ClosureValidationAgent
from common.models import Approval, ApprovalDecision, RemediationStatus
from remediation_engine import RemediationEngine


@pytest.mark.asyncio
async def test_remediation_engine_executes_rollback_strategy() -> None:
    approval = Approval(
        incident_id="11111111-1111-1111-1111-111111111111",
        recommendation_id="22222222-2222-2222-2222-222222222222",
        decision=ApprovalDecision.APPROVED,
        approver="sre@example.com",
        comment="Rollback deployment",
    )
    engine = RemediationEngine()

    action = engine.build_action(approval)
    completed = await engine.execute(action)

    assert action.action_type == "rollback_deployment"
    assert completed.status == RemediationStatus.SUCCEEDED
    assert "jenkins rollback" in completed.output


@pytest.mark.asyncio
async def test_closure_validation_generates_report() -> None:
    approval = Approval(
        incident_id="11111111-1111-1111-1111-111111111111",
        recommendation_id="22222222-2222-2222-2222-222222222222",
        decision=ApprovalDecision.APPROVED,
        approver="sre@example.com",
        comment="Rollback deployment",
    )
    action = await RemediationEngine().execute(RemediationEngine().build_action(approval))

    report = await ClosureValidationAgent().validate(action)

    assert report.health_restored is True
    assert report.alerts_cleared is True
    assert all(report.validation.values())
