import pytest
from pydantic import ValidationError

from common.onboarding_control_plane import (
    ConnectorSelection,
    EnvironmentDefinition,
    OnboardingControlPlane,
    ProjectDefinition,
    ReadinessSignal,
    calculate_operational_readiness,
    production_auto_execute_allowed,
)


def project():
    return ProjectDefinition(
        name="checkout", business_owner="commerce", technical_owner="platform",
        criticality="critical", support_timezone="Asia/Calcutta",
    )


def control(readiness=None):
    return OnboardingControlPlane(
        tenant_id="tenant-a", project=project(),
        environments=[EnvironmentDefinition(name="production", production=True, criticality="critical")],
        completed_steps=list(range(1, 13)), current_step=12, readiness=readiness,
    )


def ready_signals():
    names = [
        "Monitoring Ready", "Telemetry Ready", "Topology Ready", "Change Intelligence Ready",
        "Knowledge Ready", "RCA Ready", "Remediation Ready", "Validation Ready",
    ]
    return [ReadinessSignal(dimension=name, ready=True, score=100, evidence_ids=[f"evidence:{index}"]) for index, name in enumerate(names)]


def test_readiness_is_derived_from_evidence_and_mandatory_gates():
    readiness = calculate_operational_readiness(ready_signals())
    assert readiness.overall_score == 100
    assert readiness.production_autonomy_allowed is True
    assert production_auto_execute_allowed(control(readiness), {"kubernetes.restart_workload": "AUTO_EXECUTE"}) is True


def test_missing_validation_blocks_production_autonomy():
    signals = ready_signals()
    signals[-1] = ReadinessSignal(
        dimension="Validation Ready", ready=False, score=40,
        gaps=["No production recovery validator is registered."],
    )
    readiness = calculate_operational_readiness(signals)
    assert readiness.production_autonomy_allowed is False
    assert production_auto_execute_allowed(control(readiness), {"kubernetes.restart_workload": "AUTO_EXECUTE"}) is False
    assert "No production recovery validator is registered." in readiness.blocking_gaps


def test_ready_signal_cannot_be_fabricated_without_evidence():
    with pytest.raises(ValidationError, match="observed evidence"):
        ReadinessSignal(dimension="Monitoring Ready", ready=True, score=100)


def test_steps_must_be_sequential_for_resume_integrity():
    with pytest.raises(ValidationError, match="sequentially"):
        OnboardingControlPlane(
            tenant_id="tenant-a", project=project(), completed_steps=[1, 3], current_step=4,
        )


def test_connector_rejects_raw_credentials_and_accepts_secret_reference():
    with pytest.raises(ValidationError, match="opaque secret_ref"):
        ConnectorSelection(connector_id="kubernetes", profile_id="prod", secret_ref="my-password")
    selected = ConnectorSelection(
        connector_id="kubernetes", profile_id="prod",
        secret_ref="vault://kaiops/kubernetes/prod", status="Pending",
    )
    assert selected.secret_ref.startswith("vault://")
