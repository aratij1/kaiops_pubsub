from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from common.tenant_identity import require_tenant_id


class ArtifactProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["kaims.artifact-provenance.v1"] = "kaims.artifact-provenance.v1"
    artifact_id: UUID
    tenant_id: str
    artifact_type: str
    payload_sha256: str
    signer_key_id: str
    signature: str
    signed_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def provenance_is_well_formed(self) -> "ArtifactProvenance":
        require_tenant_id(self.tenant_id, source="artifact provenance")
        if not self.payload_sha256.startswith("sha256:") or len(self.payload_sha256) != 71:
            raise ValueError("artifact payload requires a complete sha256 digest")
        if not self.signature.startswith("hmac-sha256:") or len(self.signature) != 76:
            raise ValueError("artifact requires a complete HMAC-SHA256 signature")
        if self.expires_at <= self.signed_at:
            raise ValueError("artifact expiry must follow signing time")
        return self

    def signing_material(self) -> bytes:
        return f"{self.artifact_id}:{self.tenant_id}:{self.artifact_type}:{self.payload_sha256}:{self.signer_key_id}:{self.signed_at.isoformat()}:{self.expires_at.isoformat()}".encode()


def verify_artifact_provenance(provenance: ArtifactProvenance, *, verification_key: bytes, now: datetime | None = None) -> bool:
    instant = now or datetime.now(UTC)
    if instant >= provenance.expires_at:
        return False
    expected = "hmac-sha256:" + hmac.new(verification_key, provenance.signing_material(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, provenance.signature)


@dataclass(frozen=True)
class ArtifactVerificationKey:
    key_id: str
    verification_key: bytes = field(repr=False)
    revoked_at: datetime | None = None


class ArtifactKeyRing:
    """Verification-only key registry supporting overlap during safe rotation."""

    def __init__(self, keys: list[ArtifactVerificationKey]) -> None:
        self._keys = {key.key_id: key for key in keys}
        if len(self._keys) != len(keys):
            raise ValueError("artifact verification key ids must be unique")

    def verify(self, provenance: ArtifactProvenance, *, now: datetime | None = None) -> bool:
        instant = now or datetime.now(UTC)
        key = self._keys.get(provenance.signer_key_id)
        if key is None or (key.revoked_at is not None and instant >= key.revoked_at):
            return False
        return verify_artifact_provenance(provenance, verification_key=key.verification_key, now=instant)


class DraftPullRequestAuthorization(BaseModel):
    """Human authorization to create a draft review object; never merge or deploy."""

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["kaims.draft-pr-authorization.v1"] = "kaims.draft-pr-authorization.v1"
    authorization_id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    patch_proposal_id: UUID
    repository_id: str
    base_revision: str
    provider_connection_id: UUID
    actor_id: str
    actor_role: Literal["Administrator", "L3 Engineer"]
    operation: Literal["CREATE_DRAFT_PULL_REQUEST"] = "CREATE_DRAFT_PULL_REQUEST"
    authorized_at: datetime
    expires_at: datetime
    merge_authorized: Literal[False] = False
    deployment_authorized: Literal[False] = False

    @model_validator(mode="after")
    def authorization_is_bounded(self) -> "DraftPullRequestAuthorization":
        require_tenant_id(self.tenant_id, source="draft pull request authorization")
        if self.expires_at <= self.authorized_at:
            raise ValueError("draft pull request authorization must expire after authorization")
        if (self.expires_at - self.authorized_at).total_seconds() > 900:
            raise ValueError("draft pull request authorization cannot exceed 15 minutes")
        return self
