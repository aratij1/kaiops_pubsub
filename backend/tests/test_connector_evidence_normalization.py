import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from common.context_enrichment_contract import (
    EvidenceRequirement,
    build_evidence_requirements,
    normalize_connector_response,
)
from common.models import Incident

FIXTURES = Path(__file__).parent / "fixtures" / "connectors"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _requirement(incident: Incident, category: str = "metrics") -> EvidenceRequirement:
    now = datetime(2024, 8, 26, 13, 32, tzinfo=UTC)
    return EvidenceRequirement(
        requirement_id=uuid4(), tenant_id=incident.tenant_id, incident_id=incident.id,
        rca_version=1, category=category, question="What factual evidence was observed?",
        reason="Confirm the observed latency signal", priority="high", collection_mode="automatic",
        candidate_connectors=["prometheus"], created_at=now, updated_at=now,
    )


def test_prometheus_range_matrix_preserves_wrapper_provenance_and_samples() -> None:
    incident = Incident(tenant_id="tenant-a", service="api-gateway", title="latency")
    requirement = _requirement(incident)
    result = normalize_connector_response(
        raw_response=_fixture("prometheus_range_matrix.json"), requirement=requirement,
        incident=incident, connector="prometheus",
        collected_at=datetime(2024, 8, 26, 13, 32, tzinfo=UTC),
    )

    assert result.rejected == []
    assert len(result.records) == 1
    record = result.records[0]
    assert record.content["metric_name"] == "http_request_duration_seconds"
    assert record.content["labels"]["instance"] == "api-gateway:8010"
    assert [sample["value"] for sample in record.content["samples"]] == ["3.2", "3.4"]
    assert record.provenance["api_path"] == "/api/v1/query_range"
    assert record.source_reference.startswith("prometheus://prometheus:9090/query")


def test_prometheus_instant_vector_is_stable_across_retries() -> None:
    incident = Incident(tenant_id="tenant-a", service="api-gateway", title="availability")
    requirement = _requirement(incident)
    payload = _fixture("prometheus_instant_vector.json")
    first = normalize_connector_response(
        raw_response=payload, requirement=requirement, incident=incident, connector="prometheus",
        collected_at=datetime(2024, 8, 26, 13, 32, tzinfo=UTC),
    )
    retry = normalize_connector_response(
        raw_response=payload, requirement=requirement, incident=incident, connector="prometheus",
        collected_at=datetime(2024, 8, 26, 13, 33, tzinfo=UTC),
    )

    assert first.records[0].evidence_id == retry.records[0].evidence_id
    assert first.records[0].content["samples"] == [{
        "timestamp": "2024-08-26T13:30:30+00:00", "value": "1",
    }]


def test_normalization_rejects_cross_tenant_binding() -> None:
    incident = Incident(tenant_id="tenant-a", service="api-gateway", title="availability")
    requirement = _requirement(incident).model_copy(update={"tenant_id": "tenant-b"})
    result = normalize_connector_response(
        raw_response=_fixture("prometheus_instant_vector.json"), requirement=requirement,
        incident=incident, connector="prometheus", collected_at=datetime.now(UTC),
    )

    assert result.records == []
    assert result.rejected == [{"code": "EVIDENCE_BINDING_MISMATCH"}]


def test_sanitized_connector_fixtures_normalize_to_governed_evidence() -> None:
    incident = Incident(tenant_id="tenant-a", service="api-gateway", title="availability")
    cases = [
        ("logs_response.json", "logs", "opensearch", "logs"),
        ("otel_trace.json", "traces", "otel", "traces"),
        ("deployment_change.json", "deployment", "jenkins", "changes"),
        ("source_repository.json", "source_code", "github", "source_code"),
        ("approved_rag_document.json", "runbook", "vector-db", "knowledge"),
        ("jira_issue_comment.json", "ticket", "jira", "tickets"),
    ]
    for filename, requirement_category, connector, canonical_category in cases:
        result = normalize_connector_response(
            raw_response=_fixture(filename),
            requirement=_requirement(incident, requirement_category),
            incident=incident,
            connector=connector,
            collected_at=datetime(2024, 8, 26, 13, 32, tzinfo=UTC),
        )
        assert result.rejected == [], filename
        assert len(result.records) == 1, filename
        record = result.records[0]
        assert record.category == canonical_category
        assert record.source_reference
        assert record.evidence_id.startswith("EVD-")
        assert record.tenant_id == incident.tenant_id
        assert record.incident_id == str(incident.id)


def test_unapproved_rag_document_is_rejected_with_reason() -> None:
    incident = Incident(tenant_id="tenant-a", service="api-gateway", title="availability")
    payload = _fixture("approved_rag_document.json")
    payload["records"][0]["approved"] = False
    result = normalize_connector_response(
        raw_response=payload, requirement=_requirement(incident, "runbook"), incident=incident,
        connector="vector-db", collected_at=datetime(2024, 8, 26, 13, 32, tzinfo=UTC),
    )
    assert result.records == []
    assert result.rejected == [{"code": "KNOWLEDGE_NOT_APPROVED", "record_index": 0}]


def test_governed_vector_search_match_normalizes_as_approved_runbook() -> None:
    incident = Incident(tenant_id="tenant-a", service="api-gateway", title="availability")
    payload = {
        "matches": [{
            "document_id": "runbook-123",
            "kind": "runbook",
            "title": "API gateway recovery",
            "content": "Restore the gateway using the approved procedure.",
            "content_version": "3",
            "review_status": "approved",
            "source_ref": "governed-rag://runbook-123",
            "tenant_scope": "tenant-a",
            "service": "api-gateway",
            "approved_by": "platform-ops",
            "approved_at": "2024-08-26T12:00:00+00:00",
        }],
        "document_count": 1,
    }

    result = normalize_connector_response(
        raw_response=payload, requirement=_requirement(incident, "runbook"), incident=incident,
        connector="vector-db", collected_at=datetime(2024, 8, 26, 13, 32, tzinfo=UTC),
    )

    assert result.rejected == []
    assert len(result.records) == 1
    assert result.records[0].content["version"] == "3"
    assert result.records[0].content["approved"] is True
    assert result.records[0].source_reference == "governed-rag://runbook-123"


def test_rca_domain_gap_aliases_create_executable_canonical_requirements() -> None:
    incident = Incident(tenant_id="tenant-a", service="api-gateway", title="availability")
    requirements = build_evidence_requirements(
        tenant_id=incident.tenant_id, incident_id=incident.id, rca_version=2,
        missing_evidence=["dependency", "dependencies", "runbooks"],
        now=datetime(2024, 8, 26, 13, 32, tzinfo=UTC),
    )
    assert [(item.category, item.candidate_connectors) for item in requirements] == [
        ("topology", ["discovery-mcp", "cmdb"]),
        ("runbook", ["vector-db"]),
    ]
