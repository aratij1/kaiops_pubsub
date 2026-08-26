from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from common.orchestration.execution_plan_contract import canonical_plan_fingerprint

_APP_PATH = Path(__file__).resolve().parents[1] / "src" / "approval-service" / "app.py"
_SPEC = importlib.util.spec_from_file_location("approval_service_app", _APP_PATH)
assert _SPEC is not None and _SPEC.loader is not None
approval_service_app = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = approval_service_app
_SPEC.loader.exec_module(approval_service_app)


def _set_pending_plan(incident_id, recommendation_id) -> dict:
    approval_service_app.settings.service_internal_token = "internal-test-token"
    plan = {
        "tenant_id": "tenant-a",
        "incident_id": str(incident_id),
        "plan_id": "33333333-3333-3333-3333-333333333333",
        "execution_ready": True,
        "diagnostic_only": False,
        "plan_kind": "remediation",
        "target_resource_id": "k8s:/clusters/prod/namespaces/payments/deployments/api",
        "connector_id": "kubernetes-prod",
        "validators": [{"validator_id": "availability-1"}],
        "rollback_commands": ["governed:rollback-deployment"],
        "rollback_mode": "automatic",
        "policy_decision": {"decision": "allow"},
        "expiry": "2099-01-01T00:00:00+00:00",
    }
    plan["plan_fingerprint"] = canonical_plan_fingerprint(plan)
    approval_service_app.PENDING_INCIDENTS[approval_service_app._pending_key("tenant-a", incident_id)] = {
        "recommendation": {
            "id": str(recommendation_id),
            "incident_id": str(incident_id),
            "metadata": {
                "execution_plan": plan,
                "runbook_status": "approved",
                "connection_profile": {"credential_ref": "vault://tenant-a/prod-remediator"},
                "evidence_quality": {
                    "evidence_coverage": 0.9,
                    "citation_coverage": 0.8,
                    "evidence_fresh": True,
                    "conflict_count": 0,
                },
            },
        }
    }
    return plan


# ---------------------------------------------------------------------------
# _publish_evaluation_feedback / _post_evaluation_feedback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_evaluation_feedback_body_and_url(monkeypatch) -> None:
    captured: dict = {}

    async def fake_post(recommendation_id: str, body: dict) -> None:
        captured["recommendation_id"] = recommendation_id
        captured["body"] = body

    monkeypatch.setattr(approval_service_app, "_post_evaluation_feedback", fake_post)

    approval = approval_service_app.Approval(
        tenant_id="tenant-a",
        incident_id=uuid4(),
        recommendation_id=uuid4(),
        decision=approval_service_app.ApprovalDecision.APPROVED,
        approver="alice",
        channel="web",
        comment="looks good",
    )
    approval_service_app._publish_evaluation_feedback(approval)
    await asyncio.sleep(0)

    assert captured["recommendation_id"] == str(approval.recommendation_id)
    assert captured["body"] == {"decision": "approved", "approver": "alice", "comment": "looks good"}


@pytest.mark.asyncio
async def test_post_evaluation_feedback_swallows_transport_failures(monkeypatch) -> None:
    class RaisingAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            raise RuntimeError("connection refused")

    monkeypatch.setattr(approval_service_app.httpx, "AsyncClient", RaisingAsyncClient)

    # Must not raise.
    await approval_service_app._post_evaluation_feedback(str(uuid4()), {"decision": "approved"})


@pytest.mark.asyncio
async def test_post_evaluation_feedback_posts_to_correct_endpoint(monkeypatch) -> None:
    captured: dict = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json=None):
            captured["url"] = url
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr(approval_service_app.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(approval_service_app.settings, "evaluation_service_url", "http://evaluation-service:8000")

    recommendation_id = str(uuid4())
    await approval_service_app._post_evaluation_feedback(recommendation_id, {"decision": "rejected"})

    assert captured["url"] == f"http://evaluation-service:8000/evaluations/by-recommendation/{recommendation_id}/feedback"
    assert captured["json"] == {"decision": "rejected"}


# ---------------------------------------------------------------------------
# End-to-end: /approve, /reject, /modify all trigger the feedback publish
# ---------------------------------------------------------------------------


class _NoopProducer:
    async def publish(self, *args, **kwargs) -> None:
        return None


@pytest.fixture(autouse=True)
def _stub_producer_and_disable_db(monkeypatch):
    monkeypatch.setattr(approval_service_app.app.state, "producer", _NoopProducer(), raising=False)
    monkeypatch.setattr(approval_service_app.settings, "database_enabled", False)
    approval_service_app.PENDING_INCIDENTS.clear()


@pytest.mark.asyncio
async def test_approve_endpoint_triggers_evaluation_feedback_publish(monkeypatch) -> None:
    captured: dict = {}

    async def fake_post(recommendation_id: str, body: dict) -> None:
        captured["recommendation_id"] = recommendation_id
        captured["body"] = body

    monkeypatch.setattr(approval_service_app, "_post_evaluation_feedback", fake_post)

    incident_id, recommendation_id = uuid4(), uuid4()
    plan = _set_pending_plan(incident_id, recommendation_id)
    request = approval_service_app.ApprovalRequest(
        incident_id=incident_id,
        recommendation_id=recommendation_id,
        tenant_id="tenant-a",
        plan_id=plan["plan_id"],
        plan_fingerprint=plan["plan_fingerprint"],
        approver="alice",
        channel="web",
        comment="looks good",
    )
    approval = await approval_service_app.approve(request)
    await asyncio.sleep(0)

    assert approval.decision == approval_service_app.ApprovalDecision.APPROVED
    assert captured["recommendation_id"] == str(request.recommendation_id)
    assert captured["body"]["decision"] == "approved"


@pytest.mark.asyncio
async def test_reject_endpoint_succeeds_even_when_evaluation_service_unreachable(monkeypatch) -> None:
    class RaisingAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            raise RuntimeError("connection refused")

    monkeypatch.setattr(approval_service_app.httpx, "AsyncClient", RaisingAsyncClient)

    request = approval_service_app.ApprovalRequest(
        incident_id=uuid4(),
        recommendation_id=uuid4(),
        tenant_id="tenant-a",
        approver="bob",
        channel="web",
        comment="reject this",
    )
    approval = await approval_service_app.reject(request)
    await asyncio.sleep(0)

    assert approval.decision == approval_service_app.ApprovalDecision.REJECTED
