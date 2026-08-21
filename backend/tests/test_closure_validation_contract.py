import asyncio
from uuid import uuid4

from closure_service.validation import ClosureValidationAgent, _validation_urls
from common.models import RemediationAction, RemediationStatus


def test_validation_contract_accepts_all_supported_field_names():
    urls, supplied = _validation_urls({
        "validation_commands": ["curl -fsS https://service/health"],
        "validation_queries": ["https://prometheus/api/v1/query?query=up"],
        "queries": ["http://alerts/api/v2/alerts"],
    })
    assert supplied == 3
    assert urls == [
        "https://service/health",
        "https://prometheus/api/v1/query?query=up",
        "http://alerts/api/v2/alerts",
    ]


def test_descriptive_validation_is_not_treated_as_executable():
    urls, supplied = _validation_urls({"validation_commands": ["verify that the service recovered"]})
    assert supplied == 1
    assert urls == []


def test_duplicate_compatibility_fields_are_one_executable_check():
    check = "curl -fsS http://service:8000/healthz"
    urls, supplied = _validation_urls({
        "validation_commands": [check],
        "queries": ["http://service:8000/healthz"],
    })
    assert urls == ["http://service:8000/healthz"]
    assert supplied == 1


def test_diagnostic_completion_closes_without_claiming_corrective_execution():
    action = RemediationAction(
        incident_id=uuid4(),
        action_type="diagnostic_completion",
        target="external-service",
        status=RemediationStatus.SKIPPED,
        output="Diagnostic analysis completed; no corrective operation was executed.",
        parameters={
            "diagnostic_closure": True,
            "root_cause": "External endpoint returned an error",
            "impact": "Synthetic availability signal only",
            "execution_plan": {"plan_kind": "diagnostic", "validation_queries": ["probe result captured"]},
            "diagnostic_details": {"commands": ["kubectl get pods"], "readiness_blocks": ["No corrective operation is present"]},
        },
    )

    report = asyncio.run(ClosureValidationAgent().validate(action))

    assert report.health_restored is False
    assert report.alerts_cleared is False
    assert report.validation["diagnostic_completed"] is True
    assert report.validation["corrective_action_executed"] is False
    assert report.metadata["closure_kind"] == "diagnostic"


def test_signed_executor_success_cannot_replace_independent_recovery_evidence():
    action = RemediationAction(
        incident_id=uuid4(),
        action_type="restart_service",
        target="payments-api",
        status=RemediationStatus.SUCCEEDED,
        parameters={
            "execution_plan": {"validation_commands": ["http://127.0.0.1:1/healthz"]},
            "execution_result": {
                "executed": True,
                "build_result": "SUCCESS",
                "recovery_validated": True,
                "recovery_evidence": {"executed": True, "recovery_validated": True},
            },
        },
    )

    report = asyncio.run(ClosureValidationAgent().validate(action))

    assert report.validation["health_check_1"] is False
    assert report.validation["executor_recovery_validated"] is True
    assert report.health_restored is False
    assert report.alerts_cleared is False


def test_closure_requires_all_operational_checks_and_stability_window():
    action = RemediationAction(
        incident_id=uuid4(),
        action_type="restart_service",
        target="payments-api",
        status=RemediationStatus.SUCCEEDED,
        parameters={
            "execution_plan": {"validation_commands": ["http://service/healthz"]},
            "execution_result": {
                "executed": True,
                "build_result": "SUCCESS",
                "recovery_validated": True,
                "recovery_evidence": {
                    "executed": True,
                    "recovery_validated": True,
                    "triggering_alert_cleared": True,
                    "availability_recovered": True,
                    "error_rate_recovered": True,
                    "latency_within_slo": True,
                    "dependency_health_stable": True,
                    "no_new_critical_alerts": True,
                    "stability_window_completed": True,
                },
            },
        },
    )

    report = asyncio.run(ClosureValidationAgent().validate(action))

    assert report.health_restored is True
    assert report.alerts_cleared is True
    assert report.validation["all_recovery_checks_passed"] is True


def test_replayed_action_produces_the_same_resolution_report_identity():
    action = RemediationAction(
        incident_id=uuid4(),
        action_type="restart_service",
        target="payments-api",
        status=RemediationStatus.SUCCEEDED,
        parameters={
            "execution_plan": {"validation_commands": ["http://127.0.0.1:1/healthz"]},
            "execution_result": {
                "executed": True,
                "build_result": "SUCCESS",
                "recovery_validated": True,
                "recovery_evidence": {"executed": True, "recovery_validated": True},
            },
        },
    )

    first = asyncio.run(ClosureValidationAgent().validate(action))
    replay = asyncio.run(ClosureValidationAgent().validate(action))

    assert first.id == replay.id
