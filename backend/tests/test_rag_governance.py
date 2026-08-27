from datetime import UTC, datetime

from common.rag_governance import content_checksum, retrieval_allowed


def governed_metadata(*, tenant_scope: str, classification: str, status: str = "approved") -> dict:
    now = datetime.now(UTC).isoformat()
    return {
        "kind": "runbook",
        "title": "Governed checkout runbook",
        "tenant_scope": tenant_scope,
        "services": ["checkout"],
        "owner_team": "checkout-ops",
        "source_system": "runbook-registry",
        "source_ref": "runbook://checkout/v1",
        "review_status": status,
        "corpus_classification": classification,
        "content_version": 1,
        "created_at": now,
        "updated_at": now,
        "last_reviewed": now,
        "reviewed_by": "reviewer@example.test",
        "approved_by": "approver@example.test",
        "approved_at": now,
        "content_checksum": content_checksum("Verified checkout recovery steps."),
    }


def test_tenant_curated_document_is_retrievable_only_by_exact_tenant() -> None:
    metadata = governed_metadata(tenant_scope="tenant-a", classification="TENANT_CURATED")

    assert retrieval_allowed(metadata, "tenant-a") is True
    assert retrieval_allowed(metadata, "tenant-b") is False


def test_global_production_curated_document_is_retrievable_by_tenants() -> None:
    metadata = governed_metadata(tenant_scope="global", classification="PRODUCTION_CURATED")

    assert retrieval_allowed(metadata, "tenant-a") is True
    assert retrieval_allowed(metadata, "tenant-b") is True


def test_unapproved_and_unverified_documents_are_never_retrievable() -> None:
    pending = governed_metadata(
        tenant_scope="tenant-a", classification="TENANT_CURATED", status="pending_review"
    )
    unverified = governed_metadata(
        tenant_scope="tenant-a", classification="GENERATED_UNVERIFIED"
    )

    assert retrieval_allowed(pending, "tenant-a") is False
    assert retrieval_allowed(unverified, "tenant-a") is False


def test_classification_and_scope_must_form_an_allowed_pair() -> None:
    tenant_marked_production = governed_metadata(
        tenant_scope="tenant-a", classification="PRODUCTION_CURATED"
    )
    global_marked_tenant = governed_metadata(
        tenant_scope="global", classification="TENANT_CURATED"
    )

    assert retrieval_allowed(tenant_marked_production, "tenant-a") is False
    assert retrieval_allowed(global_marked_tenant, "tenant-a") is False


def test_missing_governance_metadata_fails_closed() -> None:
    assert retrieval_allowed({"review_status": "approved"}, "tenant-a") is False
