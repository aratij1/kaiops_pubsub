from __future__ import annotations

import pytest

from common.capability_registry import ApprovalLevel, default_capability_registry
from common.orchestration.safe_remediation import BlastRadiusScope


def test_default_registry_contains_governed_capabilities() -> None:
    registry = default_capability_registry()
    capability = registry.get("kubernetes.restart_workload")
    assert capability.risk_level == "medium"
    assert capability.required_approval_level == ApprovalLevel.HITL_APPROVER
    assert capability.validation
    assert capability.rollback_capability == "kubernetes.rollback_deployment"


def test_unregistered_capability_fails_closed() -> None:
    with pytest.raises(KeyError, match="unregistered capability"):
        default_capability_registry().get("shell.execute_arbitrary_command")


def test_registry_blocks_connector_blast_radius_and_parameter_mismatch() -> None:
    decision = default_capability_registry().evaluate(
        "kubernetes.scale_workload",
        connector_id="ssh-linux",
        environment="production",
        blast_radius=BlastRadiusScope.ENVIRONMENT,
        parameters={},
    )
    assert decision.allowed is False
    assert decision.reason_codes == [
        "unsupported_connector", "blast_radius_exceeds_limit", "required_parameters_missing"
    ]


def test_registry_binds_definition_to_existing_safe_remediation_contract() -> None:
    registry = default_capability_registry()
    spec = registry.bind(
        "kubernetes.restart_workload",
        connector_id="kubernetes",
        allowed_resource_ids=["k8s://cluster-a/namespaces/payments/deployments/api"],
    )
    assert spec.registered is True
    assert spec.operation == "restart_workload"
    assert spec.required_permissions == ["deployments.patch"]


def test_read_only_diagnostics_can_pass_registry_without_hitl() -> None:
    decision = default_capability_registry().evaluate(
        "database.collect_diagnostics",
        connector_id="mysql",
        environment="production",
        blast_radius=BlastRadiusScope.RESOURCE,
        parameters={},
    )
    assert decision.allowed is True
    assert decision.required_approval_level == ApprovalLevel.NONE

