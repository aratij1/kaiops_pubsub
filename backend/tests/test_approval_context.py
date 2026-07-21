import importlib.util
import sys
from pathlib import Path

import pytest


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

    request = module.ApprovalRequest(
        incident_id="11111111-1111-1111-1111-111111111111",
        recommendation_id="22222222-2222-2222-2222-222222222222",
        approver="l2.engineer",
        comment="approved",
    )

    await module.approve(request)

    assert ("update_status", "remediating") in calls
    assert ("save_event", "remediating") in calls


@pytest.mark.asyncio
async def test_approval_submission_resolves_missing_recommendation_id(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_approval_app_module()
    incident_id = "11111111-1111-1111-1111-111111111111"
    recommendation_id = "22222222-2222-2222-2222-222222222222"
    calls: list[tuple[str, str]] = []

    class _FakeRepo:
        def __init__(self, session):
            self.session = session

        async def get_latest_recommendation_for_incident(self, requested_incident_id):
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

    request = module.ApprovalRequest(
        incident_id=incident_id,
        approver="l2.engineer",
        comment="approved",
    )

    approval = await module.approve(request)

    assert str(approval.recommendation_id) == recommendation_id
    assert ("get_recommendation", incident_id) in calls
    assert ("save_approval", recommendation_id) in calls
    assert ("update_status", "remediating") in calls
