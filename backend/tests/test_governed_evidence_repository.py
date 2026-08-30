from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from common.database import (
    AuditLogRecord,
    ContextSnapshotRecord,
    GovernedRagDocumentRecord,
    IncidentInvestigationBindingRecord,
    IncidentProjectionRecord,
    ResolutionOutboxRecord,
)
from common.repository import IncidentRepository
from sqlalchemy import func, select


async def seed_binding(session, tenant_id: str, *, alert_id=None):
    now = datetime.now(UTC)
    incident_id, alert_id = uuid4(), alert_id or uuid4()
    analysis_id, snapshot_id, recommendation_id = uuid4(), uuid4(), uuid4()
    fingerprint, evidence_id, uri = "a" * 64, "evidence-1", "prometheus://query/test"
    session.add(ContextSnapshotRecord(
        snapshot_id=snapshot_id, tenant_id=tenant_id, incident_id=str(incident_id),
        source_incident_id=str(incident_id), alert_signature="signature",
        subject_fingerprint="b" * 64, context_fingerprint=fingerprint,
        contract_version="kaiops.context.v2", quality_score=0.9, reusable=True,
        source_manifest={}, payload={"metadata": {
            "alert_id": str(alert_id), "project_id": "project",
            "context_evidence": {"telemetry": [{
                "evidence_id": evidence_id, "citation": uri, "tenant_id": tenant_id,
            }]},
        }}, collected_at=now, expires_at=now + timedelta(hours=1),
    ))
    session.add(AuditLogRecord(
        id=recommendation_id, tenant_id=tenant_id, actor="agent",
        action="recommendation.generated", resource_type="incident",
        resource_id=str(incident_id), payload={"metadata": {
            "alert_id": str(alert_id), "project_id": "project",
            "analysis_request_id": str(analysis_id), "context_snapshot_id": str(snapshot_id),
            "context_fingerprint": fingerprint, "evidence_ids": [evidence_id],
        }},
    ))
    session.add(IncidentInvestigationBindingRecord(
        binding_id=recommendation_id, tenant_id=tenant_id, project_id="project",
        incident_id=incident_id, alert_id=alert_id, analysis_request_id=analysis_id,
        context_snapshot_id=snapshot_id, context_fingerprint=fingerprint,
        recommendation_id=recommendation_id, rca_version=1, status="grounded",
        created_at=now, expires_at=now + timedelta(hours=1),
    ))
    session.add(IncidentProjectionRecord(
        incident_id=incident_id, alert_id=alert_id, recommendation_id=recommendation_id,
        tenant_id=tenant_id, service="payments", environment="prod", status="investigating",
        first_seen_at=now, projection_payload={},
    ))
    await session.commit()
    return {
        "incident_id": incident_id, "alert_id": alert_id, "analysis_request_id": analysis_id,
        "context_snapshot_id": snapshot_id, "context_fingerprint": fingerprint,
        "recommendation_id": recommendation_id, "rca_version": 1,
        "evidence_ids": [evidence_id], "source_uris": [uri],
    }


def documents():
    return [{"document_kind": kind, "title": f"{kind} title", "content": "x" * 40} for kind in (
        "incident", "jira", "runbook", "deployment", "change", "dependency", "remediation",
    )]


@pytest.mark.asyncio
async def test_tenant_slug_collision_and_shared_alert_remain_isolated(sqlite_session_factory):
    shared_alert = uuid4()
    async with sqlite_session_factory() as session:
        a = await seed_binding(session, "tenant-a", alert_id=shared_alert)
        b = await seed_binding(session, "tenant_a", alert_id=shared_alert)
        for tenant, binding in (("tenant-a", a), ("tenant_a", b)):
            await IncidentRepository(session).create_evidence_rag_drafts(
                tenant_id=tenant, created_by="engineer", binding=binding,
                documents=documents(), evidence_ids=binding["evidence_ids"],
                source_uris=binding["source_uris"],
            )
        await session.commit()
        rows_a = await IncidentRepository(session).list_evidence_rag_drafts(
            tenant_id="tenant-a", alert_id=shared_alert,
        )
        rows_b = await IncidentRepository(session).list_evidence_rag_drafts(
            tenant_id="tenant_a", alert_id=shared_alert,
        )
    assert len(rows_a) == len(rows_b) == 7
    assert {row["draft_id"] for row in rows_a}.isdisjoint(row["draft_id"] for row in rows_b)
    assert {row["document_kind"] for row in rows_a} == {row["document_kind"] for row in rows_b}


@pytest.mark.asyncio
async def test_review_concurrency_and_immutable_incident_jira_approval(sqlite_session_factory):
    async with sqlite_session_factory() as session:
        binding = await seed_binding(session, "tenant-a")
        drafts = await IncidentRepository(session).create_evidence_rag_drafts(
            tenant_id="tenant-a", created_by="engineer", binding=binding,
            documents=documents(), evidence_ids=binding["evidence_ids"],
            source_uris=binding["source_uris"],
        )
        await session.commit()
        repo = IncidentRepository(session)
        approved_ids = []
        for kind in ("incident", "jira"):
            draft = next(row for row in drafts if row["document_kind"] == kind)
            reviewed = await repo.review_evidence_rag_draft(
                tenant_id="tenant-a", draft_id=draft["draft_id"], expected_row_version=1,
                title=draft["title"], content=draft["content"] + " reviewed",
                review_notes=None, reviewed_by="reviewer",
            )
            stale = await repo.review_evidence_rag_draft(
                tenant_id="tenant-a", draft_id=draft["draft_id"], expected_row_version=1,
                title=draft["title"], content="y" * 40, review_notes=None, reviewed_by="other",
            )
            assert stale is None
            result = await repo.approve_evidence_rag_draft(
                tenant_id="tenant-a", draft_id=draft["draft_id"],
                expected_row_version=reviewed["row_version"], approved_by="administrator",
            )
            approved_ids.append(result[1]["document_id"])
        await session.commit()
        kinds = set((await session.execute(select(GovernedRagDocumentRecord.document_kind))).scalars())
        audit_count = await session.scalar(select(func.count()).select_from(AuditLogRecord).where(
            AuditLogRecord.action == "rag.document.approved",
        ))
        outbox_count = await session.scalar(select(func.count()).select_from(ResolutionOutboxRecord).where(
            ResolutionOutboxRecord.topic == "rag.document.approved",
        ))
    assert len(set(approved_ids)) == 2
    assert {"incident", "jira"}.issubset(kinds)
    assert audit_count == outbox_count == 2


@pytest.mark.asyncio
async def test_unrecognized_evidence_and_cross_tenant_mutation_are_blocked(sqlite_session_factory):
    async with sqlite_session_factory() as session:
        binding = await seed_binding(session, "tenant-a")
        bad = dict(binding)
        with pytest.raises(RuntimeError, match="accepted bound snapshot"):
            await IncidentRepository(session).create_evidence_rag_drafts(
                tenant_id="tenant-a", created_by="engineer", binding=bad,
                documents=documents(), evidence_ids=["forged"], source_uris=bad["source_uris"],
            )
        drafts = await IncidentRepository(session).create_evidence_rag_drafts(
            tenant_id="tenant-a", created_by="engineer", binding=binding,
            documents=documents(), evidence_ids=binding["evidence_ids"],
            source_uris=binding["source_uris"],
        )
        await session.commit()
        draft = drafts[0]
        result = await IncidentRepository(session).review_evidence_rag_draft(
            tenant_id="tenant_a", draft_id=draft["draft_id"], expected_row_version=1,
            title=draft["title"], content="z" * 40, review_notes=None, reviewed_by="intruder",
        )
    assert result is None


@pytest.mark.asyncio
async def test_approved_replacement_increments_version_and_index_gate_is_explicit(sqlite_session_factory):
    async with sqlite_session_factory() as session:
        binding = await seed_binding(session, "tenant-a")
        repo = IncidentRepository(session)
        first = (await repo.create_evidence_rag_drafts(
            tenant_id="tenant-a", created_by="engineer", binding=binding,
            documents=documents(), evidence_ids=binding["evidence_ids"],
            source_uris=binding["source_uris"],
        ))[0]
        reviewed = await repo.review_evidence_rag_draft(
            tenant_id="tenant-a", draft_id=first["draft_id"], expected_row_version=1,
            title=first["title"], content=first["content"] + " reviewed",
            review_notes=None, reviewed_by="reviewer",
        )
        approved = await repo.approve_evidence_rag_draft(
            tenant_id="tenant-a", draft_id=first["draft_id"],
            expected_row_version=reviewed["row_version"], approved_by="administrator",
        )
        await session.commit()
        assert await repo.list_retrievable_governed_rag_documents(tenant_id="tenant-a") == []
        await repo.mark_governed_rag_document_indexed(
            tenant_id="tenant-a", document_id=approved[1]["document_id"],
        )
        assert len(await repo.list_retrievable_governed_rag_documents(tenant_id="tenant-a")) == 1
        replacements = await repo.create_evidence_rag_drafts(
            tenant_id="tenant-a", created_by="engineer", binding=binding,
            documents=documents(), evidence_ids=binding["evidence_ids"],
            source_uris=binding["source_uris"],
        )
    incident_replacement = next(row for row in replacements if row["document_kind"] == "incident")
    assert incident_replacement["document_version"] == 2
    assert incident_replacement["draft_id"] != first["draft_id"]
