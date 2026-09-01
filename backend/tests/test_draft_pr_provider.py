from datetime import UTC, datetime, timedelta
import hashlib
import hmac
from uuid import uuid4

import pytest

from common.artifact_governance import (
    ArtifactKeyRing,
    ArtifactProvenance,
    ArtifactVerificationKey,
    DraftPullRequestAuthorization,
)
from common.differentiator_contracts import CodePatchProposal
from common.draft_pr_provider import DraftPullRequestResult, DraftPullRequestService, code_patch_payload_digest


class FakeDraftProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def create_draft_pull_request(self, *, proposal, authorization) -> DraftPullRequestResult:
        self.calls += 1
        return DraftPullRequestResult(provider_pull_request_id="42", url="https://scm.example/pull/42")


def _inputs():
    now = datetime.now(UTC)
    key = b"phase-nine-test-key"
    proposal = CodePatchProposal(
        tenant_id="tenant-a", incident_id=uuid4(), repository_id="payments", base_revision="abc123",
        source_uri="repo://payments/src/app.py", title="Guard retry loop", explanation="Bounds retry attempts.",
        unified_diff="--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new", supporting_code_evidence_ids=["code-1"],
        test_plan=["run unit tests"],
    )
    values = dict(
        artifact_id=proposal.proposal_id, tenant_id=proposal.tenant_id, artifact_type="code_patch_proposal",
        payload_sha256=code_patch_payload_digest(proposal), signer_key_id="artifact-key-v2", signed_at=now,
        expires_at=now + timedelta(days=1),
    )
    unsigned = ArtifactProvenance(**values, signature="hmac-sha256:" + "0" * 64)
    provenance = unsigned.model_copy(update={"signature": "hmac-sha256:" + hmac.new(key, unsigned.signing_material(), hashlib.sha256).hexdigest()})
    authorization = DraftPullRequestAuthorization(
        tenant_id=proposal.tenant_id, patch_proposal_id=proposal.proposal_id, repository_id=proposal.repository_id,
        base_revision=proposal.base_revision, provider_connection_id=uuid4(), actor_id="operator-a",
        actor_role="Administrator", authorized_at=now, expires_at=now + timedelta(minutes=10),
    )
    ring = ArtifactKeyRing([ArtifactVerificationKey(key_id="artifact-key-v2", verification_key=key)])
    return now, proposal, provenance, authorization, ring


@pytest.mark.asyncio
async def test_validated_boundary_creates_draft_only() -> None:
    now, proposal, provenance, authorization, ring = _inputs()
    provider = FakeDraftProvider()
    result = await DraftPullRequestService(key_ring=ring, provider=provider).create_draft(
        proposal=proposal, provenance=provenance, authorization=authorization, now=now,
    )
    assert provider.calls == 1
    assert result.state == "DRAFT"
    assert result.merge_performed is False and result.deployment_performed is False


@pytest.mark.asyncio
async def test_boundary_fails_closed_without_provider() -> None:
    now, proposal, provenance, authorization, ring = _inputs()
    with pytest.raises(RuntimeError, match="not configured"):
        await DraftPullRequestService(key_ring=ring).create_draft(
            proposal=proposal, provenance=provenance, authorization=authorization, now=now,
        )


@pytest.mark.asyncio
async def test_boundary_rejects_mismatched_authorization_before_provider_call() -> None:
    now, proposal, provenance, authorization, ring = _inputs()
    provider = FakeDraftProvider()
    authorization = authorization.model_copy(update={"base_revision": "different"})
    with pytest.raises(PermissionError, match="does not match"):
        await DraftPullRequestService(key_ring=ring, provider=provider).create_draft(
            proposal=proposal, provenance=provenance, authorization=authorization, now=now,
        )
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_boundary_rejects_tampered_proposal_before_provider_call() -> None:
    now, proposal, provenance, authorization, ring = _inputs()
    provider = FakeDraftProvider()
    proposal = proposal.model_copy(update={"explanation": "tampered"})
    with pytest.raises(PermissionError, match="provenance"):
        await DraftPullRequestService(key_ring=ring, provider=provider).create_draft(
            proposal=proposal, provenance=provenance, authorization=authorization, now=now,
        )
    assert provider.calls == 0
