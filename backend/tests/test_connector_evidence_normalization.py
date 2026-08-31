from datetime import UTC, datetime
import json
from pathlib import Path
from uuid import uuid4

from common.context_enrichment_contract import (
    EvidenceRequirement,
    normalize_connector_response,
)
from common.models import Incident


FIXTURES = Path(__file__).parent / "fixtures" / "connectors"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _requirement(incident: Incident) -> EvidenceRequirement:
    now = datetime(2024, 8, 26, 13, 32, tzinfo=UTC)
    return EvidenceRequirement(
        requirement_id=uuid4(), tenant_id=incident.tenant_id, incident_id=incident.id,
        rca_version=1, category="metrics", question="What was gateway latency?",
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
