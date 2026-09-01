from datetime import UTC, datetime, timedelta
import hashlib
import hmac
from uuid import uuid4

import pytest
from sqlalchemy import select

from common.artifact_governance import ArtifactKeyRing, ArtifactProvenance, ArtifactVerificationKey, DraftPullRequestAuthorization
from common.database import AuditLogRecord, DraftPullRequestOutboxRecord
from common.differentiator_contracts import CodePatchProposal
from common.draft_pr_provider import (
    DraftPullRequestJobPayload,
    DraftPullRequestResult,
    DraftPullRequestService,
    DraftPullRequestWorkflow,
    code_patch_payload_digest,
)
from common.repository import DraftPullRequestOutboxRepository


class RecordingProvider:
    def __init__(self, *, failures: int = 0) -> None:
        self.calls = 0
        self.failures = failures

    async def create_draft_pull_request(self, *, proposal, authorization) -> DraftPullRequestResult:
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("provider unavailable: sensitive detail")
        return DraftPullRequestResult(provider_pull_request_id="pr-42", url="https://scm.example/pull/42")


def _payload() -> tuple[datetime, bytes, DraftPullRequestJobPayload]:
    now = datetime.now(UTC)
    key = b"phase-ten-key"
    proposal = CodePatchProposal(
        tenant_id="tenant-a", incident_id=uuid4(), repository_id="payments", base_revision="abc123",
        source_uri="repo://payments/app.py", title="Bound retry", explanation="Prevents retry storms.",
        unified_diff="--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new",
        supporting_code_evidence_ids=["code-1"], test_plan=["run unit tests"],
    )
    unsigned = ArtifactProvenance(
        artifact_id=proposal.proposal_id, tenant_id=proposal.tenant_id, artifact_type="code_patch_proposal",
        payload_sha256=code_patch_payload_digest(proposal), signer_key_id="artifact-key-v2",
        signature="hmac-sha256:" + "0" * 64, signed_at=now, expires_at=now + timedelta(hours=1),
    )
    provenance = unsigned.model_copy(update={
        "signature": "hmac-sha256:" + hmac.new(key, unsigned.signing_material(), hashlib.sha256).hexdigest()
    })
    authorization = DraftPullRequestAuthorization(
        tenant_id=proposal.tenant_id, patch_proposal_id=proposal.proposal_id,
        repository_id=proposal.repository_id, base_revision=proposal.base_revision,
        provider_connection_id=uuid4(), actor_id="admin-a", actor_role="Administrator",
        authorized_at=now, expires_at=now + timedelta(minutes=15),
    )
    return now, key, DraftPullRequestJobPayload(proposal=proposal, provenance=provenance, authorization=authorization)


@pytest.mark.asyncio
async def test_outbox_is_idempotent_and_completes_once_with_redacted_audit(sqlite_session_factory) -> None:
    now, key, payload = _payload()
    provider = RecordingProvider()
    async with sqlite_session_factory() as session:
        repo = DraftPullRequestOutboxRepository(session)
        workflow = DraftPullRequestWorkflow(
            repository=repo,
            service=DraftPullRequestService(
                key_ring=ArtifactKeyRing([ArtifactVerificationKey(key_id="artifact-key-v2", verification_key=key)]),
                provider=provider,
            ),
        )
        first_id, first_created = await workflow.enqueue(payload)
        second_id, second_created = await workflow.enqueue(payload)
        assert (first_id, first_created) == (second_id, True)
        assert second_created is False
        counts = await workflow.process_due(now=now + timedelta(seconds=1))
        await session.commit()
        reconciled = await repo.get_by_idempotency_key(payload.idempotency_key(), tenant_id="tenant-a")
        audits = (await session.execute(select(AuditLogRecord))).scalars().all()

    assert counts == {"completed": 1, "retry": 0, "dead_letter": 0}
    assert provider.calls == 1
    assert reconciled is not None and reconciled["status"] == "completed"
    assert reconciled["provider_response"]["state"] == "DRAFT"
    assert len(audits) == 1 and audits[0].action == "draft_pull_request.created"
    assert "unified_diff" not in str(audits[0].payload)


@pytest.mark.asyncio
async def test_outbox_stops_at_retry_limit_and_reconciliation_is_tenant_scoped(sqlite_session_factory) -> None:
    now, key, payload = _payload()
    provider = RecordingProvider(failures=5)
    async with sqlite_session_factory() as session:
        repo = DraftPullRequestOutboxRepository(session)
        workflow = DraftPullRequestWorkflow(
            repository=repo,
            service=DraftPullRequestService(
                key_ring=ArtifactKeyRing([ArtifactVerificationKey(key_id="artifact-key-v2", verification_key=key)]),
                provider=provider,
            ),
        )
        await workflow.enqueue(payload, max_attempts=2)
        first = await workflow.process_due(now=now + timedelta(seconds=1))
        second = await workflow.process_due(now=now + timedelta(seconds=10))
        third = await workflow.process_due(now=now + timedelta(seconds=30))
        await session.commit()
        own = await repo.get_by_idempotency_key(payload.idempotency_key(), tenant_id="tenant-a")
        other = await repo.get_by_idempotency_key(payload.idempotency_key(), tenant_id="tenant-b")
        rows = (await session.execute(select(DraftPullRequestOutboxRecord))).scalars().all()
        audits = (await session.execute(select(AuditLogRecord).order_by(AuditLogRecord.created_at))).scalars().all()

    assert first["retry"] == 1 and second["dead_letter"] == 1
    assert third == {"completed": 0, "retry": 0, "dead_letter": 0}
    assert provider.calls == 2
    assert own is not None and own["status"] == "dead_letter" and own["attempts"] == 2
    assert other is None and rows[0].status == "dead_letter"
    assert [item.action for item in audits] == ["draft_pull_request.retry_scheduled", "draft_pull_request.dead_lettered"]
    assert all("sensitive detail" not in str(item.payload) for item in audits)


@pytest.mark.asyncio
async def test_idempotency_key_cannot_be_rebound_to_another_tenant(sqlite_session_factory) -> None:
    _, _, payload = _payload()
    async with sqlite_session_factory() as session:
        repo = DraftPullRequestOutboxRepository(session)
        await repo.enqueue(
            idempotency_key="fixed-key", tenant_id="tenant-a", proposal_id=payload.proposal.proposal_id,
            request_payload=payload.model_dump(mode="json"),
        )
        await session.flush()
        with pytest.raises(ValueError, match="another request"):
            await repo.enqueue(
                idempotency_key="fixed-key", tenant_id="tenant-b", proposal_id=payload.proposal.proposal_id,
                request_payload=payload.model_dump(mode="json"),
            )
