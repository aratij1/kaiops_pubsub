from importlib import util
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from common.models import Incident, RemediationAction, RemediationStatus, ResolutionReport


def load_closure_app_module():
    module_path = Path("backend/src/closure-service/app.py")
    spec = util.spec_from_file_location("closure_service_app", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load closure-service app module")
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


INCIDENT_ID = "11111111-1111-1111-1111-111111111111"


def test_manual_closure_contract_forbids_client_supplied_identity() -> None:
    module = load_closure_app_module()

    with pytest.raises(ValidationError):
        module.ManualClosureRequest.model_validate({
            "comment": "Reviewed evidence and accepted the operational risk.",
            "closed_by": "attacker",
            "actor_id": "reviewer@example.com",
            "actor_role": "Administrator",
            "tenant_id": "tenant-a",
            "auth_jti": "jwt-1",
        })


def _existing_incident_payload() -> dict:
    return {
        "id": INCIDENT_ID,
        "service": "robot-shop-payment",
        "environment": "prod",
        "severity": "critical",
        "status": "investigating",
        "title": "robot-shop-payment: RobotShopServiceDown",
        "summary": "Prometheus cannot scrape robot-shop-payment for more than 20s.",
        "owner_team": "platform-ops",
        "ticket_id": "KAN-9999",
        "tenant_id": "default",
        "created_at": "2026-08-12T06:46:15.869698Z",
        "trace_id": "trace-abc",
        "alert_ids": ["8ff12ea1-a6bf-4c83-9fff-8da2d92de061"],
        "metadata": {
            "jira": {"key": "KAN-9999", "url": "https://kaiops-test.atlassian.net/browse/KAN-9999"},
            "incident_candidate": {
                "correlation_key": "2f5c4d0b1a22e52d",
                "jira_key": "KAN-9999",
            },
            "deduplication": {"window_minutes": 60, "occurrence_count": 4},
            "severity_policy": {"final_severity": "critical", "policy_version": "incident-severity-policy-v1"},
            "kaiops_incident_id": INCIDENT_ID,
        },
    }


def test_only_reviewed_successful_unedited_outcome_is_reusable_knowledge() -> None:
    module = load_closure_app_module()
    report = _report(health_restored=True)
    action = RemediationAction(
        tenant_id="tenant-a",
        incident_id=INCIDENT_ID,
        action_type="restart_service",
        target="payment",
        status=RemediationStatus.SUCCEEDED,
        parameters={"outcome_reviewed": True, "outcome_reviewed_by": "sre@example.com"},
    )
    assert module._eligible_for_reusable_knowledge(action, report) is True

    action.parameters["operator_modified"] = True
    assert module._eligible_for_reusable_knowledge(action, report) is False
    action.parameters = {}
    assert module._eligible_for_reusable_knowledge(action, report) is False
    assert module._eligible_for_reusable_knowledge(action, _report(health_restored=False)) is False


def _action() -> RemediationAction:
    return RemediationAction(
        tenant_id="tenant-a",
        incident_id=INCIDENT_ID,
        action_type="rollback_deployment",
        target="robot-shop-payment",
        status=RemediationStatus.SUCCEEDED,
    )


def _report(*, health_restored: bool) -> ResolutionReport:
    return ResolutionReport(
        tenant_id="tenant-a",
        incident_id=INCIDENT_ID,
        root_cause="deployment rollback",
        impact="payment service unavailable",
        action_taken="rolled back deployment",
        alerts_cleared=health_restored,
        health_restored=health_restored,
    )


def _assert_existing_metadata_preserved(final_metadata: dict, existing_metadata: dict) -> None:
    for key, value in existing_metadata.items():
        assert final_metadata[key] == value
    assert final_metadata["resolution_lifecycle"]["schema_version"] == "kaims.resolution-lifecycle.v4"


def test_build_final_incident_payload_preserves_metadata_created_at_and_tenant() -> None:
    module = load_closure_app_module()
    incident_payload = _existing_incident_payload()

    final_payload = module._build_final_incident_payload(
        action=_action(),
        report=_report(health_restored=True),
        incident_payload=incident_payload,
        recommendation={},
        source_contract={},
    )

    _assert_existing_metadata_preserved(final_payload["metadata"], incident_payload["metadata"])
    assert final_payload["metadata"]["incident_candidate"]["correlation_key"] == "2f5c4d0b1a22e52d"
    assert final_payload["metadata"]["jira"]["key"] == "KAN-9999"
    assert final_payload["metadata"]["deduplication"]["occurrence_count"] == 4
    assert final_payload["metadata"]["severity_policy"]["final_severity"] == "critical"
    assert final_payload["created_at"] == incident_payload["created_at"]
    assert final_payload["tenant_id"] == "default"
    assert final_payload["status"] == "closed"


def test_build_final_incident_payload_marks_failed_when_health_not_restored() -> None:
    module = load_closure_app_module()
    incident_payload = _existing_incident_payload()

    final_payload = module._build_final_incident_payload(
        action=_action(),
        report=_report(health_restored=False),
        incident_payload=incident_payload,
        recommendation={},
        source_contract={},
    )

    assert final_payload["status"] == "failed"
    # Metadata must survive a failed closure too, not just a successful one.
    _assert_existing_metadata_preserved(final_payload["metadata"], incident_payload["metadata"])
    assert final_payload["created_at"] == incident_payload["created_at"]


def test_build_final_incident_payload_defaults_metadata_when_no_prior_incident() -> None:
    module = load_closure_app_module()

    final_payload = module._build_final_incident_payload(
        action=_action(),
        report=_report(health_restored=True),
        incident_payload=None,
        recommendation={},
        source_contract={},
    )

    assert final_payload["metadata"]["resolution_lifecycle"]["state"] == "closed"
    assert final_payload["tenant_id"] == "default"
    assert "created_at" not in final_payload


def test_build_final_incident_payload_validates_into_incident_model_without_error() -> None:
    module = load_closure_app_module()
    incident_payload = _existing_incident_payload()

    final_payload = module._build_final_incident_payload(
        action=_action(),
        report=_report(health_restored=True),
        incident_payload=incident_payload,
        recommendation={},
        source_contract={},
    )

    incident = Incident.model_validate(final_payload)

    _assert_existing_metadata_preserved(incident.metadata, incident_payload["metadata"])
    assert incident.created_at.isoformat().replace("+00:00", "Z") == incident_payload["created_at"]
    assert incident.tenant_id == "default"
    assert incident.status.value == "closed"
    assert incident.ticket_id == "KAN-9999"


class _JiraResponse:
    def __init__(self, status_code: int = 200, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = ""

    def json(self) -> dict:
        return self._payload


class _JiraClient:
    calls: list[tuple[str, str, dict | None]] = []
    transitions: list[dict] = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url: str, **kwargs):
        self.calls.append(("GET", url, None))
        return _JiraResponse(payload={"transitions": self.transitions})

    async def post(self, url: str, json: dict | None = None, **kwargs):
        self.calls.append(("POST", url, json))
        return _JiraResponse(status_code=204 if url.endswith("/transitions") else 201)


def _configure_jira(monkeypatch) -> None:
    monkeypatch.setenv("JIRA_URL", "https://jira.example.test")
    monkeypatch.setenv("JIRA_API_EMAIL", "operator@example.test")
    monkeypatch.setenv("JIRA_API_TOKEN", "test-token")
    monkeypatch.setattr(httpx, "AsyncClient", _JiraClient)
    _JiraClient.calls = []
    _JiraClient.transitions = []


@pytest.mark.asyncio
async def test_jira_remains_open_when_recovery_validation_fails(monkeypatch) -> None:
    module = load_closure_app_module()
    _configure_jira(monkeypatch)

    result = await module._sync_closure_to_jira(_existing_incident_payload(), _report(health_restored=False))

    assert result["status"] == "validation_pending"
    assert result["transitioned"] is False
    assert len(_JiraClient.calls) == 1
    assert _JiraClient.calls[0][1].endswith("/comment")
    assert "remains open" in _JiraClient.calls[0][2]["body"]


@pytest.mark.asyncio
async def test_jira_transitions_by_done_status_category_after_validated_recovery(monkeypatch) -> None:
    module = load_closure_app_module()
    _configure_jira(monkeypatch)
    _JiraClient.transitions = [{"id": "91", "name": "Complete workflow", "to": {"statusCategory": {"key": "done"}}}]

    result = await module._sync_closure_to_jira(_existing_incident_payload(), _report(health_restored=True))

    assert result["status"] == "resolved"
    assert result["transitioned"] is True
    assert [call[0] for call in _JiraClient.calls] == ["POST", "GET", "POST"]
    assert _JiraClient.calls[-1][2] == {"transition": {"id": "91"}}


@pytest.mark.asyncio
async def test_manual_closure_comment_is_included_in_jira_details(monkeypatch) -> None:
    module = load_closure_app_module()
    _configure_jira(monkeypatch)
    _JiraClient.transitions = [{"id": "91", "name": "Done"}]
    report = _report(health_restored=True)
    report.metadata = {"closure_kind": "manual", "operator_comment": "Known maintenance completed; service owner confirmed recovery."}

    result = await module._sync_closure_to_jira(_existing_incident_payload(), report)

    assert result["transitioned"] is True
    assert "Operator Closure Comment" in _JiraClient.calls[0][2]["body"]
    assert "service owner confirmed recovery" in _JiraClient.calls[0][2]["body"]
