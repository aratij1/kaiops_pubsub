import pytest
from closure_service import ClosureValidationAgent
from common.models import Approval, ApprovalDecision, RemediationStatus
from common.resolution_lifecycle import ResolutionState, create_lifecycle
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
    assert completed.status == RemediationStatus.SKIPPED
    assert completed.parameters["execution_result"]["executed"] is False
    assert "No real jenkins executor is configured" in str(completed.error)
    assert "Execution not performed" in completed.output


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

    assert report.health_restored is False
    assert report.alerts_cleared is False
    assert report.validation["remediation_succeeded"] is False
    assert report.validation["alerts_cleared"] is False
    assert report.validation["validation_executable"] is False
    assert report.validation["validation_supplied"] is True


@pytest.mark.asyncio
async def test_diagnostic_completion_does_not_claim_recovery() -> None:
    approval = Approval(
        incident_id="11111111-1111-1111-1111-111111111111",
        recommendation_id="22222222-2222-2222-2222-222222222222",
        decision=ApprovalDecision.APPROVED,
        approver="system",
    )
    action = RemediationEngine().build_action(approval)
    action.action_type = "diagnostic_completion"
    action.status = RemediationStatus.SKIPPED
    action.parameters.update({
        "diagnostic_closure": True,
        "diagnostic_details": {"checks": ["logs"]},
        "resolution_lifecycle": create_lifecycle(
            tenant_id="default",
            incident_id=action.incident_id,
            recommendation_id=approval.recommendation_id,
            plan={"plan_kind": "diagnostic", "execution_ready": False},
            state=ResolutionState.DIAGNOSTIC_ONLY,
        ),
    })

    report = await ClosureValidationAgent().validate(action)

    assert report.health_restored is False
    assert report.alerts_cleared is False
    assert report.validation["diagnostic_completed"] is True


def test_remediation_allowlist_blocks_unknown_action_type() -> None:
    engine = RemediationEngine()

    assert engine.is_action_allowed("rollback_deployment") is True
    assert engine.is_action_allowed("shell_exec") is False
