import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from closure_service import validation as validation_module
from closure_service.validation import ClosureValidationAgent, _safe_validation_url, _validation_urls
from common.models import RemediationAction, RemediationStatus
from common.orchestration.execution_plan_contract import canonical_plan_fingerprint


def _plan(*, endpoints: list[dict] | None = None, stability_seconds: int = 60) -> dict:
    plan = {
        "schema_version": "kaims.execution-plan.v2",
        "plan_id": str(uuid4()),
        "tenant_id": "tenant-a",
        "validation_endpoints": endpoints or [],
        "required_validation_kinds": [
            "availability",
            "alert_clearance",
            "error_rate",
            "latency",
            "dependency_health",
            "critical_alerts",
        ],
        "stability_window_seconds": stability_seconds,
    }
    plan["plan_fingerprint"] = canonical_plan_fingerprint(plan)
    return plan


def _action(*, plan: dict, completed_seconds_ago: int = 120) -> RemediationAction:
    action = RemediationAction(
        tenant_id="tenant-a",
        incident_id=uuid4(),
        action_type="restart_service",
        target="payments-api",
        status=RemediationStatus.SUCCEEDED,
        completed_at=datetime.now(UTC) - timedelta(seconds=completed_seconds_ago),
        parameters={"execution_plan": plan, "approved_plan_fingerprint": plan["plan_fingerprint"]},
    )
    contract = {
        "schema_version": "kaims.remediation.v3",
        "execution_id": str(action.id),
        "plan_id": str(plan["plan_id"]),
        "plan_fingerprint": plan["plan_fingerprint"],
        "target": {"name": action.target},
        "plan": plan,
    }
    contract["binding_fingerprint"] = canonical_plan_fingerprint(contract)
    action.parameters["execution_contract"] = contract
    return action


def test_validation_contract_accepts_only_governed_structured_endpoints() -> None:
    endpoint = {
        "url": "https://service.example.test/health",
        "kind": "availability",
        "method": "GET",
        "onboarded": True,
        "authoritative": True,
    }
    urls, supplied = _validation_urls({
        "validation_endpoints": [endpoint],
        "validation_commands": ["curl -fsS https://unreviewed.example/health"],
    })
    assert supplied == 1
    assert urls == [endpoint["url"]]


def test_descriptive_or_unreviewed_validation_is_not_executable() -> None:
    urls, supplied = _validation_urls({"validation_commands": ["verify that the service recovered"]})
    assert supplied == 0
    assert urls == []


def test_validation_endpoint_ssrf_guards_block_local_and_metadata_targets() -> None:
    assert _safe_validation_url("http://127.0.0.1:8000/healthz") is False
    assert _safe_validation_url("http://169.254.169.254/latest/meta-data") is False
    assert _safe_validation_url("http://metadata.google.internal/computeMetadata/v1") is False
    assert _safe_validation_url("https://health.example.test/status") is True


def test_diagnostic_completion_records_evidence_without_unauthorized_closure() -> None:
    action = RemediationAction(
        tenant_id="tenant-a",
        incident_id=uuid4(),
        action_type="diagnostic_completion",
        target="external-service",
        status=RemediationStatus.SKIPPED,
        output="Diagnostic analysis completed; no corrective operation was executed.",
        parameters={
            "diagnostic_closure": True,
            "root_cause": "External endpoint returned an error",
            "impact": "Synthetic availability signal only",
            "execution_plan": {"plan_kind": "diagnostic"},
            "diagnostic_details": {"commands": ["kubectl get pods"]},
        },
    )

    report = asyncio.run(ClosureValidationAgent().validate(action))

    assert report.health_restored is False
    assert report.alerts_cleared is False
    assert report.validation["diagnostic_completed"] is True
    assert report.validation["corrective_action_executed"] is False
    assert report.metadata["closure_kind"] == "diagnostic"
    assert report.metadata["incident_terminal"] is False


def test_executor_success_cannot_replace_independent_recovery_evidence() -> None:
    plan = _plan()
    action = _action(plan=plan)
    action.parameters["execution_result"] = {
        "executed": True,
        "build_result": "SUCCESS",
        "recovery_validated": True,
        "recovery_evidence": {"executed": True, "recovery_validated": True},
    }

    report = asyncio.run(ClosureValidationAgent().validate(action))

    assert report.validation["executor_recovery_validated"] is True
    assert report.validation["validation_executable"] is False
    assert report.health_restored is False
    assert report.alerts_cleared is False


def test_closure_requires_exact_plan_all_independent_checks_and_real_stability(monkeypatch) -> None:
    endpoint_kinds = [
        "availability",
        "alert_clearance",
        "error_rate",
        "latency",
        "dependency_health",
        "critical_alerts",
    ]
    endpoints = [
        {
            "url": f"https://health.example.test/{kind}",
            "kind": kind,
            "method": "GET",
            "onboarded": True,
            "authoritative": True,
        }
        for kind in endpoint_kinds
    ]
    action = _action(plan=_plan(endpoints=endpoints, stability_seconds=60), completed_seconds_ago=90)

    class _Response:
        status_code = 200

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url):
            return _Response()

    monkeypatch.setattr(validation_module.httpx, "AsyncClient", _Client)

    report = asyncio.run(ClosureValidationAgent().validate(action))

    assert report.validation["approved_plan_fingerprint_preserved"] is True
    assert report.validation["independent_checks_passed"] is True
    assert report.validation["stability_window_completed"] is True
    assert report.validation["all_recovery_checks_passed"] is True
    assert report.health_restored is True
    assert report.alerts_cleared is True
    assert len(report.metadata["independent_validation_observations"]) == len(endpoint_kinds)


def test_replayed_action_produces_the_same_resolution_report_identity() -> None:
    action = _action(plan=_plan())

    first = asyncio.run(ClosureValidationAgent().validate(action))
    replay = asyncio.run(ClosureValidationAgent().validate(action))

    assert first.id == replay.id
