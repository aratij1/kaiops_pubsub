from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from common.tenant_identity import require_tenant_id


class BlastRadiusScope(StrEnum):
    RESOURCE = "resource"
    SINGLE_SERVICE = "single-service"
    MULTI_SERVICE = "multi-service"
    ENVIRONMENT = "environment"
    UNKNOWN = "unknown"


class PreflightStatus(StrEnum):
    PLANNED = "PLANNED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class CapabilitySpec(BaseModel):
    """Registered operation identity. It describes permission, never executable model text."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["kaims.remediation-capability.v1"] = "kaims.remediation-capability.v1"
    capability_id: str
    connector_id: str
    operation: str
    allowed_resource_ids: list[str]
    required_permissions: list[str]
    mutating: bool
    reversible: bool
    dry_run_supported: bool
    validation_required: bool = True
    registered: bool = True

    @field_validator("capability_id", "connector_id", "operation")
    @classmethod
    def require_identity(cls, value: str) -> str:
        value = str(value or "").strip()
        if not value:
            raise ValueError("capability identity is required")
        return value


class CredentialReference(BaseModel):
    """Opaque broker reference; secret values and bearer tokens are forbidden."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["kaims.credential-reference.v1"] = "kaims.credential-reference.v1"
    reference: str
    tenant_id: str
    connector_id: str
    resource_ids: list[str]
    short_lived: bool = True

    @field_validator("tenant_id")
    @classmethod
    def require_tenant(cls, value: str) -> str:
        return require_tenant_id(value, source="credential reference")

    @field_validator("reference")
    @classmethod
    def require_opaque_reference(cls, value: str) -> str:
        value = str(value or "").strip()
        valid = value.startswith(("vault://", "managed-identity://", "k8s-secret://", "gcp-secret://", "arn:aws:secretsmanager:"))
        valid = valid or (value.startswith("https://") and ".vault.azure.net/secrets/" in value)
        if not valid:
            raise ValueError("credential must be an approved opaque secret or managed-identity reference")
        return value


class BlastRadiusAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["kaims.blast-radius.v1"] = "kaims.blast-radius.v1"
    target_resource_id: str
    scope: BlastRadiusScope
    affected_resource_ids: list[str]
    affected_services: list[str]
    dependent_services: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    verified: bool
    unknown_dependencies: bool = False


class PreflightEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["kaims.preflight-evidence.v1"] = "kaims.preflight-evidence.v1"
    status: PreflightStatus
    capability_id: str
    target_resource_id: str
    check_references: list[str]
    evidence_ids: list[str] = Field(default_factory=list)
    dry_run_required: bool
    dry_run_evidence_id: str | None = None
    credential_reference: str

    @model_validator(mode="after")
    def passed_preflight_requires_durable_evidence(self) -> "PreflightEvidence":
        if self.status == PreflightStatus.PASSED:
            if not self.evidence_ids:
                raise ValueError("passed preflight requires durable evidence")
            if self.dry_run_required and not self.dry_run_evidence_id:
                raise ValueError("passed preflight requires dry-run evidence")
        return self


class SafeRemediationBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["kaims.safe-remediation-binding.v1"] = "kaims.safe-remediation-binding.v1"
    capability: CapabilitySpec
    credential: CredentialReference
    blast_radius: BlastRadiusAssessment
    preflight: PreflightEvidence

    @model_validator(mode="after")
    def identities_must_be_consistent(self) -> "SafeRemediationBinding":
        target = self.blast_radius.target_resource_id
        if self.capability.connector_id != self.credential.connector_id:
            raise ValueError("capability and credential connector identities must match")
        if target not in self.capability.allowed_resource_ids:
            raise ValueError("target is outside the registered capability scope")
        if target not in self.credential.resource_ids:
            raise ValueError("target is outside the credential scope")
        if self.preflight.capability_id != self.capability.capability_id:
            raise ValueError("preflight capability identity does not match")
        if self.preflight.target_resource_id != target:
            raise ValueError("preflight target identity does not match")
        if self.preflight.credential_reference != self.credential.reference:
            raise ValueError("preflight credential reference does not match")
        if self.capability.mutating and (not self.capability.registered or not self.blast_radius.verified):
            raise ValueError("mutating capability requires registration and verified blast radius")
        if self.capability.mutating and self.blast_radius.unknown_dependencies:
            raise ValueError("mutating capability cannot proceed with unknown dependencies")
        return self
