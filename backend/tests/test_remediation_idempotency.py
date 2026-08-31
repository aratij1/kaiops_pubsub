from importlib import util
from pathlib import Path

import pytest
from common.database import ActionRecord
from common.models import Approval, ApprovalDecision, RemediationStatus
from common.repository import IncidentRepository
from sqlalchemy import select


def load_remediation_app_module():
    module_path = Path("backend/src/remediation-engine/app.py")
    spec = util.spec_from_file_location("remediation_engine_app_idempotency", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load remediation-engine app module")
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_action_idempotency_key_is_deterministic_per_action_type() -> None:
    module = load_remediation_app_module()
    approval = Approval(
        incident_id="11111111-1111-1111-1111-111111111111",
        recommendation_id="22222222-2222-2222-2222-222222222222",
        decision=ApprovalDecision.APPROVED,
    )

    key_one = module._build_action_idempotency_key(approval, "rollback_deployment")
    key_two = module._build_action_idempotency_key(approval, "rollback_deployment")
    key_other_action = module._build_action_idempotency_key(approval, "restart_pod")

    assert key_one == key_two
    assert key_one != key_other_action


def test_temporal_duplicate_workflow_exception_is_available() -> None:
    """Keep the durable execution endpoint aligned with the installed SDK."""
    temporal_exceptions = pytest.importorskip("temporalio.exceptions")
    WorkflowAlreadyStartedError = temporal_exceptions.WorkflowAlreadyStartedError

    assert issubclass(WorkflowAlreadyStartedError, Exception)


@pytest.mark.asyncio
async def test_redelivered_approval_message_does_not_re_execute_remediation(sqlite_session_factory) -> None:
    """A RabbitMQ redelivery (e.g. consumer crash between plugin execution and
    ack) resends the same approval payload. Without the idempotency check this
    would run a real remediation plugin (K8s restart, Jenkins rollback, ...)
    twice for one approved action.
    """
    module = load_remediation_app_module()
    module.settings.database_enabled = True
    module.app.state.session_factory = sqlite_session_factory

    class ProducerStub:
        async def publish(self, *_args, **_kwargs):
            return None

    module.app.state.producer = ProducerStub()

    approval = Approval(
        incident_id="11111111-1111-1111-1111-111111111111",
        recommendation_id="22222222-2222-2222-2222-222222222222",
        decision=ApprovalDecision.APPROVED,
        approver="sre@example.com",
        comment="Rollback deployment",
        metadata={
            "service": "api-gateway",
            "connection_profile": {
                "executor_type": "jenkins",
                "endpoint_url": "https://jenkins.example",
                "job_name": "governed-remediation",
                "credential_ref": "vault://jenkins/api-token",
            },
        },
    )

    execute_calls = 0
    async def counting_execute(action):
        nonlocal execute_calls
        execute_calls += 1
        action.status = RemediationStatus.SUCCEEDED
        action.output = "mocked terminal executor success"
        action.parameters["execution_result"] = {
            "executed": True,
            "executor": "jenkins",
            "build_result": "SUCCESS",
        }
        return action

    module.engine.execute = counting_execute

    async with sqlite_session_factory() as session:
        await IncidentRepository(session).save_approval(approval)
        await session.commit()

    first = await module.execute_approval(approval)
    second = await module.execute_approval(approval)

    assert execute_calls == 1
    assert first.idempotency_key is not None
    assert first.idempotency_key == second.idempotency_key
    assert second.id == first.id

    async with sqlite_session_factory() as session:
        rows = (await session.execute(select(ActionRecord))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_execute_rejects_unpersisted_human_approval(sqlite_session_factory) -> None:
    module = load_remediation_app_module()
    module.settings.database_enabled = True
    module.app.state.session_factory = sqlite_session_factory
    approval = Approval(
        incident_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        recommendation_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        decision=ApprovalDecision.APPROVED,
        approver="operator@example.com",
        comment="unpersisted request body",
    )

    with pytest.raises(Exception) as exc_info:
        await module.execute_approval(approval)

    assert getattr(exc_info.value, "status_code", None) == 409
    assert "exact approval ID" in str(getattr(exc_info.value, "detail", ""))


@pytest.mark.asyncio
async def test_execute_rejects_different_id_for_same_approved_recommendation(sqlite_session_factory) -> None:
    module = load_remediation_app_module()
    module.settings.database_enabled = True
    module.app.state.session_factory = sqlite_session_factory
    persisted = Approval(
        incident_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        recommendation_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        decision=ApprovalDecision.APPROVED,
        approver="operator@example.com",
    )
    forged = persisted.model_copy(update={"id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc"})
    async with sqlite_session_factory() as session:
        await IncidentRepository(session).save_approval(persisted)
        await session.commit()

    with pytest.raises(Exception) as exc_info:
        await module.execute_approval(forged)

    assert getattr(exc_info.value, "status_code", None) == 409
