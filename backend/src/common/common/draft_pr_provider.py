from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, HttpUrl

from common.artifact_governance import ArtifactKeyRing, ArtifactProvenance, DraftPullRequestAuthorization
from common.differentiator_contracts import CodePatchProposal


def code_patch_payload_digest(proposal: CodePatchProposal) -> str:
    payload = json.dumps(proposal.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


class DraftPullRequestResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider_pull_request_id: str
    url: HttpUrl
    state: Literal["DRAFT"] = "DRAFT"
    merge_performed: Literal[False] = False
    deployment_performed: Literal[False] = False


class DraftPullRequestJobPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal: CodePatchProposal
    provenance: ArtifactProvenance
    authorization: DraftPullRequestAuthorization

    def idempotency_key(self) -> str:
        return (
            f"draft-pr:{self.proposal.tenant_id}:{self.proposal.proposal_id}:"
            f"{self.authorization.provider_connection_id}"
        )


class DraftPullRequestProvider(Protocol):
    async def create_draft_pull_request(
        self,
        *,
        proposal: CodePatchProposal,
        authorization: DraftPullRequestAuthorization,
    ) -> DraftPullRequestResult: ...


class DraftPullRequestService:
    """Fail-closed boundary: providers can create review drafts, never merge or deploy."""

    def __init__(self, *, key_ring: ArtifactKeyRing, provider: DraftPullRequestProvider | None = None) -> None:
        self._key_ring = key_ring
        self._provider = provider

    async def create_draft(
        self,
        *,
        proposal: CodePatchProposal,
        provenance: ArtifactProvenance,
        authorization: DraftPullRequestAuthorization,
        now: datetime | None = None,
    ) -> DraftPullRequestResult:
        instant = now or datetime.now(UTC)
        if self._provider is None:
            raise RuntimeError("draft pull request provider is not configured")
        if instant >= authorization.expires_at:
            raise PermissionError("draft pull request authorization has expired")
        expected = (
            proposal.tenant_id,
            proposal.proposal_id,
            proposal.repository_id,
            proposal.base_revision,
        )
        authorized = (
            authorization.tenant_id,
            authorization.patch_proposal_id,
            authorization.repository_id,
            authorization.base_revision,
        )
        if expected != authorized:
            raise PermissionError("draft pull request authorization does not match the proposal")
        if (
            provenance.tenant_id != proposal.tenant_id
            or provenance.artifact_id != proposal.proposal_id
            or provenance.artifact_type != "code_patch_proposal"
            or provenance.payload_sha256 != code_patch_payload_digest(proposal)
        ):
            raise PermissionError("artifact provenance does not match the proposal")
        if not self._key_ring.verify(provenance, now=instant):
            raise PermissionError("artifact provenance signature is invalid or expired")

        result = await self._provider.create_draft_pull_request(
            proposal=proposal,
            authorization=authorization,
        )
        if result.state != "DRAFT" or result.merge_performed or result.deployment_performed:
            raise RuntimeError("provider violated the draft-only pull request contract")
        return result


class DraftPullRequestWorkflow:
    """Durable orchestration around the verified provider boundary."""

    def __init__(self, *, repository, service: DraftPullRequestService) -> None:
        self._repository = repository
        self._service = service

    async def enqueue(self, payload: DraftPullRequestJobPayload, *, max_attempts: int = 3) -> tuple[str, bool]:
        return await self._repository.enqueue(
            idempotency_key=payload.idempotency_key(),
            tenant_id=payload.proposal.tenant_id,
            proposal_id=payload.proposal.proposal_id,
            request_payload=payload.model_dump(mode="json"),
            max_attempts=max_attempts,
        )

    async def process_due(self, *, now: datetime | None = None, limit: int = 25) -> dict[str, int]:
        instant = now or datetime.now(UTC)
        counts = {"completed": 0, "retry": 0, "dead_letter": 0}
        for row in await self._repository.list_due(now=instant, limit=limit):
            try:
                payload = DraftPullRequestJobPayload.model_validate(row.request_payload)
                result = await self._service.create_draft(
                    proposal=payload.proposal,
                    provenance=payload.provenance,
                    authorization=payload.authorization,
                    now=instant,
                )
            except Exception as exc:
                status = await self._repository.mark_failed(row.job_id, error=str(exc), now=instant)
                counts[status] += 1
            else:
                await self._repository.mark_completed(
                    row.job_id,
                    provider_response=result.model_dump(mode="json"),
                )
                counts["completed"] += 1
        return counts
