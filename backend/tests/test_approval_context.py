import importlib.util
import sys
from pathlib import Path

import pytest
from common.orchestration.execution_plan_contract import canonical_plan_fingerprint


def _approval_plan(incident_id: str) -> dict:
    plan = {
        "tenant_id": "tenant-a",
        "incident_id": incident_id,
        "plan_id": "33333333-3333-3333-3333-333333333333",
        "expiry": "2099-01-01T00:00:00+00:00",
    }
    plan["plan_fingerprint"] = canonical_plan_fingerprint(plan)
    return plan


def _set_pending_plan(module, incident_id: str, recommendation_id: str) -> dict:
    plan = _approval_plan(incident_id)
    module.PENDING_INCIDENTS[incident_id] = {
        "recommendation": {
            "id": recommendation_id,
            "incident_id": incident_id,
            "metadata": {"execution_plan": plan},
        }
    }
    return plan


def load_approval_app_module():
    module_path = Path("backend/src/approval-service/app.py")
    spec = importlib.util.spec_from_file_location("approval_service_app", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_approval_incident_context_resolves_nested_recommendation_id() -> None:
    module = load_approval_app_module()
    recommendation_id = "22222222-2222-2222-2222-222222222222"

    context = module._build_incident_context(
        {"incident_id": "11111111-1111-1111-1111-111111111111"},
        {
            "incident_id": "11111111-1111-1111-1111-111111111111",
            "flow_id": "flow-1",
            "trace_id": "trace-1",
            "status": "pending",
            "payload": {
                "source_payload": {
                    "recommendation": {
                        "id": recommendation_id,
                    }
                }
            },
        },
    )

    assert context["recommendation_id"] == recommendation_id
    assert context["flow_id"] == "flow-1"


def test_approval_request_rejects_placeholder_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    module = load_approval_app_module()

    with pytest.raises(ValueError, match="verified identity"):
        module.ApprovalRequest(
            incident_id="11111111-1111-1111-1111-111111111111",
            recommendation_id="22222222-2222-2222-2222-222222222222",
            tenant_id="default",
            approver="l2.engineer",
        )


@pytest.mark.asyncio
async def test_evidence_request_is_durable_non_execution_decision(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_approval_app_module()
    stored = []

    async def store_stub(approval):
        stored.append(approval)

    monkeypatch.setattr(module, "_store_and_publish", store_stub)
    request = module.ApprovalRequest(
        incident_id="11111111-1111-1111-1111-111111111111",
        recommendation_id="22222222-2222-2222-2222-222222222222",
        tenant_id="tenant-a",
        approver="reviewer@example.com",
        comment="Collect application logs and recent deployment history.",
    )

    approval = await module.request_evidence(request)

    assert approval.decision.value == "evidence_requested"
    assert approval.authorization_scope == "execution"
    assert stored == [approval]


@pytest.mark.asyncio
async def test_evidence_request_requires_reason() -> None:
    module = load_approval_app_module()
    request = module.ApprovalRequest(
        incident_id="11111111-1111-1111-1111-111111111111",
        recommendation_id="22222222-2222-2222-2222-222222222222",
        tenant_id="tenant-a",
        approver="reviewer@example.com",
        comment="",
    )

    with pytest.raises(module.HTTPException) as exc:
        await module.request_evidence(request)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_approval_submission_updates_ticket_projection_status(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_approval_app_module()
    calls: list[tuple[str, str]] = []

    class _FakeRepo:
        def __init__(self, session):
            self.session = session

        async def save_approval(self, approval):
            calls.append(("save_approval", str(approval.incident_id)))

        async def update_incident_approval_status(self, incident_id, *, status, approval=None):
            calls.append(("update_status", status))
            return True

        async def save_incident_event(self, payload):
            calls.append(("save_event", payload["state"]["status"]))

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def commit(self):
            calls.append(("commit", "ok"))

    class _FakeProducer:
        async def publish(self, *args, **kwargs):
            calls.append(("publish", "ok"))

    monkeypatch.setattr(module.settings, "database_enabled", True)
    monkeypatch.setattr(module, "IncidentRepository", _FakeRepo)
    module.app.state.session_factory = lambda: _FakeSession()
    module.app.state.producer = _FakeProducer()
    plan = _set_pending_plan(
        module,
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    )

    request = module.ApprovalRequest(
        incident_id="11111111-1111-1111-1111-111111111111",
        recommendation_id="22222222-2222-2222-2222-222222222222",
        tenant_id="tenant-a",
        plan_id=plan["plan_id"],
        plan_fingerprint=plan["plan_fingerprint"],
        approver="l2.engineer",
        comment="approved",
    )

    await module.approve(request)

    # Approval and execution are separate durable stages. The approval service
    # must not claim remediation has started before remediation-engine accepts it.
    assert ("update_status", "approved") in calls
    assert ("save_event", "approved") in calls


@pytest.mark.asyncio
async def test_approval_submission_resolves_missing_recommendation_id(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_approval_app_module()
    incident_id = "11111111-1111-1111-1111-111111111111"
    recommendation_id = "22222222-2222-2222-2222-222222222222"
    calls: list[tuple[str, str]] = []

    class _FakeRepo:
        def __init__(self, session):
            self.session = session

        async def get_latest_recommendation_for_incident(self, requested_incident_id, *, tenant_id=None):
            calls.append(("get_recommendation", str(requested_incident_id)))
            return {"id": recommendation_id, "incident_id": incident_id}

        async def get_pending_workflow(self, requested_incident_id):
            calls.append(("get_pending", str(requested_incident_id)))
            return None

        async def save_approval(self, approval):
            calls.append(("save_approval", str(approval.recommendation_id)))

        async def update_incident_approval_status(self, incident_id, *, status, approval=None):
            calls.append(("update_status", status))
            return True

        async def save_incident_event(self, payload):
            calls.append(("save_event", payload["state"]["status"]))

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def commit(self):
            calls.append(("commit", "ok"))

    class _FakeProducer:
        async def publish(self, *args, **kwargs):
            calls.append(("publish", "ok"))

    monkeypatch.setattr(module.settings, "database_enabled", True)
    monkeypatch.setattr(module, "IncidentRepository", _FakeRepo)
    module.app.state.session_factory = lambda: _FakeSession()
    module.app.state.producer = _FakeProducer()
    module.PENDING_INCIDENTS.clear()
    plan = _set_pending_plan(module, incident_id, recommendation_id)
    module.PENDING_INCIDENTS[incident_id]["recommendation"].pop("id")

    request = module.ApprovalRequest(
        incident_id=incident_id,
        tenant_id="tenant-a",
        plan_id=plan["plan_id"],
        plan_fingerprint=plan["plan_fingerprint"],
        approver="l2.engineer",
        comment="approved",
    )

    approval = await module.approve(request)

    assert str(approval.recommendation_id) == recommendation_id
    assert ("get_recommendation", incident_id) in calls
    assert ("save_approval", recommendation_id) in calls
    assert ("update_status", "approved") in calls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tenant_id", "plan_id", "fingerprint", "status_code"),
    [
        ("tenant-b", "33333333-3333-3333-3333-333333333333", None, 403),
        ("tenant-a", "44444444-4444-4444-4444-444444444444", None, 409),
        ("tenant-a", "33333333-3333-3333-3333-333333333333", "sha256:" + "f" * 64, 409),
    ],
)
async def test_approval_rejects_cross_tenant_or_changed_plan(
    tenant_id: str,
    plan_id: str,
    fingerprint: str | None,
    status_code: int,
) -> None:
    module = load_approval_app_module()
    incident_id = "11111111-1111-1111-1111-111111111111"
    recommendation_id = "22222222-2222-2222-2222-222222222222"
    plan = _set_pending_plan(module, incident_id, recommendation_id)
    request = module.ApprovalRequest(
        incident_id=incident_id,
        recommendation_id=recommendation_id,
        tenant_id=tenant_id,
        plan_id=plan_id,
        plan_fingerprint=fingerprint or plan["plan_fingerprint"],
        approver="l2.engineer",
    )

    with pytest.raises(module.HTTPException) as exc_info:
        await module._approval_from_request(request, module.ApprovalDecision.APPROVED)

    assert exc_info.value.status_code == status_code


@pytest.mark.asyncio
async def test_approval_rejects_expired_plan() -> None:
    module = load_approval_app_module()
    incident_id = "11111111-1111-1111-1111-111111111111"
    recommendation_id = "22222222-2222-2222-2222-222222222222"
    plan = _set_pending_plan(module, incident_id, recommendation_id)
    plan["expiry"] = "2020-01-01T00:00:00+00:00"
    plan["plan_fingerprint"] = canonical_plan_fingerprint(plan)
    request = module.ApprovalRequest(
        incident_id=incident_id,
        recommendation_id=recommendation_id,
        tenant_id="tenant-a",
        plan_id=plan["plan_id"],
        plan_fingerprint=plan["plan_fingerprint"],
        approver="l2.engineer",
    )

    with pytest.raises(module.HTTPException, match="expired"):
        await module._approval_from_request(request, module.ApprovalDecision.APPROVED)
