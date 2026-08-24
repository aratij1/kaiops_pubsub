from __future__ import annotations

import pytest
from pydantic import ValidationError

from common.canonical_events import CanonicalEventEnvelopeV1, canonical_event_from_legacy
from common.event_publishers import build_event_envelope
from common.operational_models import (
    Dependency,
    OperationalResource,
    Provenance,
    RelationshipSource,
    RelationshipType,
    ResourceKind,
)


def test_operational_resource_uses_stable_identity_separate_from_display_name() -> None:
    resource = OperationalResource(
        resource_id="k8s://cluster-a/namespaces/payments/deployments/api",
        tenant_id="tenant-a",
        project_id="project-a",
        kind=ResourceKind.WORKLOAD,
        display_name="payment-api-v2",
        provider_resource_id="uid-123",
        provenance=Provenance(source="kubernetes-api", evidence=["discovery://snapshot/1"]),
    )

    assert resource.resource_id != resource.display_name
    assert resource.provenance.confidence == 1.0


def test_inferred_relationship_requires_evidence() -> None:
    with pytest.raises(ValidationError, match="inferred relationship requires evidence"):
        Dependency(
            relationship_id="rel-1",
            tenant_id="tenant-a",
            project_id="project-a",
            source_resource_id="service-a",
            target_resource_id="db-a",
            relationship_type=RelationshipType.USES_DATABASE,
            relationship_source=RelationshipSource.INFERRED,
            provenance=Provenance(source="kai-inference", confidence=0.72),
        )


def test_canonical_event_serializes_every_required_envelope_field() -> None:
    event = CanonicalEventEnvelopeV1(
        event_type="topology.resource.discovered",
        tenant_id="tenant-a",
        project_id="project-a",
        trace_id="trace-1",
        correlation_id="discovery-1",
        source="kubernetes-connector",
        payload={"resource_id": "resource-1"},
    )

    wire = event.wire_payload()
    expected = {
        "event_id", "event_type", "event_version", "timestamp", "tenant_id",
        "project_id", "application_id", "environment", "resource_id", "incident_id",
        "trace_id", "correlation_id", "causation_id", "source", "payload", "metadata",
    }
    assert expected == set(wire)
    assert wire["application_id"] is None


def test_legacy_event_adapter_preserves_payload_and_governance_metadata() -> None:
    legacy = build_event_envelope(
        event_type="incident.workflow.selected",
        identity={"incident_id": "incident-1", "trace_id": "trace-1", "correlation_id": "corr-1"},
        scope={"tenant_id": "tenant-a", "project_id": "project-a", "environment": "prod", "agent": "orchestrator"},
        state={"status": "investigating"},
        policy={"requires_approval": True},
        transport={"provider": "rabbitmq", "channel": "orchestration-events"},
        payload={"workflow": "critical"},
    )

    canonical = canonical_event_from_legacy(legacy)

    assert canonical.incident_id == "incident-1"
    assert canonical.source == "orchestrator"
    assert canonical.payload == {"workflow": "critical"}
    assert canonical.metadata["policy"]["requires_approval"] is True

