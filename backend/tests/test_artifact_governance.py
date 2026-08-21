from datetime import UTC, datetime, timedelta
from uuid import uuid4
import hashlib
import hmac

import pytest
from pydantic import ValidationError

from common.artifact_governance import (
    ArtifactKeyRing,
    ArtifactProvenance,
    ArtifactVerificationKey,
    DraftPullRequestAuthorization,
    verify_artifact_provenance,
)


def _provenance(key: bytes) -> ArtifactProvenance:
    now = datetime.now(UTC)
    values = dict(artifact_id=uuid4(), tenant_id="tenant-a", artifact_type="code_patch_proposal", payload_sha256=f"sha256:{'a' * 64}", signer_key_id="artifact-key-v1", signed_at=now, expires_at=now + timedelta(days=30))
    material = f"{values['artifact_id']}:{values['tenant_id']}:{values['artifact_type']}:{values['payload_sha256']}:{values['signer_key_id']}:{values['signed_at'].isoformat()}:{values['expires_at'].isoformat()}".encode()
    return ArtifactProvenance(**values, signature="hmac-sha256:" + hmac.new(key, material, hashlib.sha256).hexdigest())


def test_provenance_verifies_signature_and_expiry() -> None:
    provenance = _provenance(b"verification-key")
    assert verify_artifact_provenance(provenance, verification_key=b"verification-key") is True
    assert verify_artifact_provenance(provenance, verification_key=b"wrong-key") is False
    assert verify_artifact_provenance(provenance, verification_key=b"verification-key", now=provenance.expires_at) is False


def test_draft_pr_authorization_cannot_merge_deploy_or_live_too_long() -> None:
    now = datetime.now(UTC)
    authorization = DraftPullRequestAuthorization(tenant_id="tenant-a", patch_proposal_id=uuid4(), repository_id="payments", base_revision="abc123", provider_connection_id=uuid4(), actor_id="operator-a", actor_role="L3 Engineer", authorized_at=now, expires_at=now + timedelta(minutes=10))
    assert authorization.merge_authorized is False and authorization.deployment_authorized is False
    with pytest.raises(ValidationError, match="15 minutes"):
        DraftPullRequestAuthorization.model_validate({**authorization.model_dump(), "expires_at": now + timedelta(minutes=16)})


def test_key_ring_supports_rotation_and_rejects_revoked_or_unknown_keys() -> None:
    now = datetime.now(UTC)
    old = _provenance(b"old-key")
    current = _provenance(b"current-key")
    current = current.model_copy(update={"signer_key_id": "artifact-key-v2"})
    material = current.signing_material()
    current = current.model_copy(update={"signature": "hmac-sha256:" + hmac.new(b"current-key", material, hashlib.sha256).hexdigest()})
    key_ring = ArtifactKeyRing([
        ArtifactVerificationKey(key_id="artifact-key-v1", verification_key=b"old-key", revoked_at=now + timedelta(days=1)),
        ArtifactVerificationKey(key_id="artifact-key-v2", verification_key=b"current-key"),
    ])

    assert key_ring.verify(old, now=now) is True
    assert key_ring.verify(current, now=now) is True
    assert key_ring.verify(old, now=now + timedelta(days=2)) is False
    assert key_ring.verify(current.model_copy(update={"signer_key_id": "unknown"}), now=now) is False


def test_key_ring_rejects_duplicate_key_ids() -> None:
    with pytest.raises(ValueError, match="unique"):
        ArtifactKeyRing([
            ArtifactVerificationKey(key_id="duplicate", verification_key=b"one"),
            ArtifactVerificationKey(key_id="duplicate", verification_key=b"two"),
        ])
