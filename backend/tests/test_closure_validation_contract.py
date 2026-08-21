import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from closure_service import validation as validation_module
from closure_service.validation import ClosureValidationAgent, _safe_validation_url, _validation_urls
from common.models import RemediationAction, RemediationStatus
from common.orchestration.execution_plan_contract import canonical_plan_fingerprint


def _validators(kinds: list[str]) -> list[dict]:
    return [
        {
            "validator_id": f"validator-{kind}",
            "tenant_id": "tenant-a",
            "connector_id": "fake-observer",
            "target_resource_id": "payments-api",
            "kind": kind,
            "check_reference": f"fake-check:{kind}",
            "expected_condition": f"{kind} passes",
            "evaluation_operator": "eq",
            "threshold": True,
            "observation_window_seconds": 60,
            "minimum_sample_count": 2,
            "timeout_seconds": 10,
            "authoritative_source": "fake-observer",
            "onboarding_registry_reference": f"validator-registry:validator-{kind}",
        }
        for kind in kinds
    ]


def _plan(*, validators: list[dict] | None = None, stability_seconds: int = 60) -> dict:
    kinds = [
        "availability", "alert_clearance", "error_rate", "latency", "dependency_health", "critical_alerts"
    ]
    validators = validators if validators is not None else _validators(kinds)
    plan = {
        "schema_version": "kaims.execution-plan.v2",
        "plan_id": str(uuid4()),
        "tenant_id": "tenant-a",
        "validation_endpoints": [],
        "validators": validators,
        "required_validation_kinds": [item["kind"] for item in validators],
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
    action.parameters["validator_registry_snapshot"] = plan.get("validators", [])
    return action


def test_plan_supplied_endpoint_flags_are_not_a_validator_registry() -> None:
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
    assert supplied == 0
    assert urls == []


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
    assert report.validation["validation_executable"] is True
    assert report.validation["independent_checks_passed"] is False
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
    action = _action(plan=_plan(validators=_validators(endpoint_kinds), stability_seconds=60), completed_seconds_ago=90)
    now = datetime.now(UTC)
    action.parameters["validation_observations"] = [
        {
            "validator_id": f"validator-{kind}",
            "execution_id": str(action.id),
            "plan_fingerprint": action.parameters["execution_plan"]["plan_fingerprint"],
            "connector_id": "fake-observer",
            "target_resource_id": "payments-api",
            "observed_at": (now - timedelta(seconds=offset)).isoformat(),
            "passed": True,
            "result_checksum": f"sha256:{'a' * 64}",
        }
        for kind in endpoint_kinds
        for offset in (65, 0)
    ]

    report = asyncio.run(ClosureValidationAgent().validate(action))

    assert report.validation["approved_plan_fingerprint_preserved"] is True
    assert report.validation["independent_checks_passed"] is True
    assert report.validation["stability_window_completed"] is True
    assert report.validation["all_recovery_checks_passed"] is True
    assert report.health_restored is True
    assert report.alerts_cleared is True
    assert report.metadata["outcome_validation"]["outcome"] == "RECOVERED"
    assert report.metadata["outcome_validation"]["closure_authorized"] is True
    assert report.metadata["outcome_validation"]["rollback"]["disposition"] == "NOT_REQUIRED"
    assert len(report.metadata["independent_validation_observations"]) == len(endpoint_kinds) * 2


def test_incomplete_stability_window_remains_pending() -> None:
    plan = _plan(stability_seconds=60)
    action = _action(plan=plan, completed_seconds_ago=30)
    now = datetime.now(UTC)
    action.parameters["validation_observations"] = [
        {
            "validator_id": validator["validator_id"],
            "execution_id": str(action.id),
            "plan_fingerprint": action.parameters["execution_plan"]["plan_fingerprint"],
            "connector_id": validator["connector_id"],
            "target_resource_id": validator["target_resource_id"],
            "observed_at": (now - timedelta(seconds=offset)).isoformat(),
            "passed": True,
            "result_checksum": f"sha256:{'b' * 64}",
        }
        for validator in plan["validators"]
        for offset in (10, 0)
    ]

    report = asyncio.run(ClosureValidationAgent().validate(action))

    assert report.health_restored is False
    assert report.metadata["stability_window"]["status"] == "pending"
    assert report.metadata["outcome_validation"]["outcome"] == "PENDING_STABILITY"


def test_observations_from_another_execution_cannot_close_incident() -> None:
    plan = _plan(stability_seconds=60)
    action = _action(plan=plan, completed_seconds_ago=90)
    now = datetime.now(UTC)
    action.parameters["validation_observations"] = [
        {
            "validator_id": validator["validator_id"],
            "execution_id": str(uuid4()),
            "plan_fingerprint": plan["plan_fingerprint"],
            "connector_id": validator["connector_id"],
            "target_resource_id": validator["target_resource_id"],
            "observed_at": (now - timedelta(seconds=offset)).isoformat(),
            "passed": True,
            "result_checksum": f"sha256:{'c' * 64}",
        }
        for validator in plan["validators"]
        for offset in (65, 0)
    ]

    report = asyncio.run(ClosureValidationAgent().validate(action))

    assert report.health_restored is False
    assert report.metadata["independent_validation_observations"] == []
    assert report.metadata["outcome_validation"]["closure_authorized"] is False


def test_replayed_action_produces_the_same_resolution_report_identity() -> None:
    action = _action(plan=_plan())

    first = asyncio.run(ClosureValidationAgent().validate(action))
    replay = asyncio.run(ClosureValidationAgent().validate(action))

    assert first.id == replay.id
