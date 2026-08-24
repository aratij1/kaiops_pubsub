from uuid import uuid4

import pytest

from common.capability_registry import default_capability_registry
from common.remediation_plan import (
    AutonomyRecommendation,
    RemediationPlan,
    assess_remediation_plan,
)


def plan(**updates):
    values = {
        "incident_id": uuid4(),
        "tenant_id": "tenant-a",
        "root_cause": "A blocked database session is exhausting the pool.",
        "root_cause_confidence": 0.94,
        "supporting_evidence": ["evidence://trace/1"],
        "affected_resources": ["dt://tenant-a/mysql/prod/orders-primary"],
        "blast_radius": "resource",
        "business_impact": "Checkout writes are delayed.",
        "recommended_capability": "database.collect_diagnostics",
        "target_resource_id": "dt://tenant-a/mysql/prod/orders-primary",
        "target_identity_verified": True,
        "connector_id": "mysql",
        "required_parameters": {},
        "preconditions": ["target identity verified"],
        "validation_plan": ["connection saturation re-evaluated"],
        "rollback_capability": None,
        "risk_score": 15,
        "autonomy_recommendation": "RECOMMEND",
    }
    values.update(updates)
    return RemediationPlan.model_validate(values)


def test_registered_capability_plan_is_valid_but_not_automatically_executable():
    assessment = assess_remediation_plan(plan(), default_capability_registry(), environment="production")
    assert assessment.valid is True
    assert assessment.execution_eligible is False


def test_unknown_capability_fails_closed():
    assessment = assess_remediation_plan(
        plan(recommended_capability="database.arbitrary_sql"),
        default_capability_registry(),
        environment="production",
    )
    assert assessment.valid is False
    assert assessment.reason_codes == ["unregistered_capability"]


def test_command_shaped_parameters_are_forbidden():
    with pytest.raises(ValueError, match="executable text"):
        plan(required_parameters={"command": "mysql -e 'DROP DATABASE kaiops'"})


def test_autonomy_requires_registry_trust_even_with_verified_target():
    candidate = plan(
        recommended_capability="kubernetes.restart_workload",
        connector_id="kubernetes",
        rollback_capability="kubernetes.rollback_deployment",
        autonomy_recommendation=AutonomyRecommendation.AUTO_EXECUTE,
    )
    assessment = assess_remediation_plan(candidate, default_capability_registry(), environment="production")
    assert assessment.execution_eligible is False
    assert "capability_not_autonomous" in assessment.reason_codes
    assert "approval_required" in assessment.reason_codes
