from __future__ import annotations

import pytest
from pydantic import ValidationError

from common.orchestration.safe_remediation import (
    BlastRadiusAssessment,
    CapabilitySpec,
    CredentialReference,
    PreflightEvidence,
    SafeRemediationBinding,
)


def _binding(*, credential_resources: list[str] | None = None) -> SafeRemediationBinding:
    target = "k8s:/clusters/prod/namespaces/payments/deployments/api"
    return SafeRemediationBinding(
        capability=CapabilitySpec(
            capability_id="kubernetes:restart_service",
            connector_id="kubernetes",
            operation="restart_service",
            allowed_resource_ids=[target],
            required_permissions=["deployments.patch"],
            mutating=True,
            reversible=True,
            dry_run_supported=True,
        ),
        credential=CredentialReference(
            reference="vault://tenant-a/k8s/prod-remediator",
            tenant_id="tenant-a",
            connector_id="kubernetes",
            resource_ids=credential_resources or [target],
        ),
        blast_radius=BlastRadiusAssessment(
            target_resource_id=target,
            scope="single-service",
            affected_resource_ids=[target],
            affected_services=["api"],
            evidence_ids=["TOPOLOGY-1"],
            verified=True,
        ),
        preflight=PreflightEvidence(
            status="PLANNED",
            capability_id="kubernetes:restart_service",
            target_resource_id=target,
            check_references=["catalog-check:abc"],
            dry_run_required=True,
            credential_reference="vault://tenant-a/k8s/prod-remediator",
        ),
    )


def test_safe_binding_accepts_registered_scoped_operation() -> None:
    binding = _binding()

    assert binding.capability.registered is True
    assert binding.blast_radius.verified is True
    assert binding.preflight.status == "PLANNED"


def test_plaintext_or_environment_credentials_are_rejected() -> None:
    with pytest.raises(ValidationError, match="approved opaque"):
        CredentialReference(
            reference="SUPER_SECRET_TOKEN",
            tenant_id="tenant-a",
            connector_id="kubernetes",
            resource_ids=["resource-a"],
        )


def test_target_outside_credential_scope_fails_closed() -> None:
    with pytest.raises(ValidationError, match="outside the credential scope"):
        _binding(credential_resources=["a-different-resource"])


def test_unknown_dependencies_block_mutating_capability() -> None:
    binding = _binding()
    with pytest.raises(ValidationError, match="unknown dependencies"):
        SafeRemediationBinding(
            capability=binding.capability,
            credential=binding.credential,
            blast_radius=binding.blast_radius.model_copy(update={"unknown_dependencies": True}),
            preflight=binding.preflight,
        )


def test_passed_preflight_requires_dry_run_and_durable_evidence() -> None:
    with pytest.raises(ValidationError, match="durable evidence"):
        PreflightEvidence(
            status="PASSED",
            capability_id="kubernetes:restart_service",
            target_resource_id="resource-a",
            check_references=["catalog-check:abc"],
            dry_run_required=True,
            credential_reference="vault://tenant-a/k8s/prod-remediator",
        )
