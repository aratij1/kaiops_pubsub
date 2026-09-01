from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ai_workbench_common.models import Context
from common.models import Alert, AlertSeverity, Incident
from context_agent.context_quality import (
    CONTEXT_CONTRACT_VERSION,
    context_subject_fingerprint,
    govern_context,
    plan_connectors,
)


def make_context(*, stale: bool = False) -> Context:
    observed_at = datetime.now(timezone.utc) - (timedelta(minutes=20) if stale else timedelta(seconds=5))
    alert = Alert(
        tenant_id="tenant-a",
        source="prometheus",
        name="WorkerQueueLagHigh",
        service="worker",
        environment="prod",
        severity=AlertSeverity.WARNING,
        description="Queue lag is above threshold",
        labels={"application": "orders", "namespace": "production"},
        metadata={"tenant_id": "tenant-a"},
    )
    incident = Incident(tenant_id=alert.tenant_id, service="worker", environment="prod", severity=alert.severity, title=alert.name)
    return Context(
        tenant_id=alert.tenant_id,
        incident_id=incident.id,
        alert=alert,
        deployment="orders-worker-v42",
        dependency_services=["redis"],
        runbook="Restart only the affected worker and verify queue recovery.",
        metadata={
            "context_collected_at": observed_at.isoformat(),
            "context_evidence": {
                "logs": [
                    {
                        "source": "logs",
                        "uri": "opensearch://orders/worker-1",
                        "summary": "queue stalled password=supersecret",
                        "observed_at": observed_at.isoformat(),
                        "confidence": 0.9,
                    }
                ],
                "code": [
                    {
                        "source": "code",
                        "uri": "repository://orders/worker.py#L42",
                        "summary": "worker retry loop",
                        "observed_at": observed_at.isoformat(),
                        "confidence": 0.8,
                    }
                ],
            },
        },
    )


def test_govern_context_builds_redacted_provenance_and_strict_package() -> None:
    context = make_context()
    subject = context_subject_fingerprint(context.alert, "tenant-a")

    governed = govern_context(context, tenant_id="tenant-a", subject_fingerprint=subject)

    quality = governed.metadata["context_quality"]
    log = governed.metadata["context_evidence"]["logs"][0]
    package = governed.metadata["context_package"]
    assert governed.metadata["context_contract_version"] == CONTEXT_CONTRACT_VERSION
    assert governed.metadata["context_fingerprint"]
    assert quality["reusable"] is True
    assert quality["provenance_score"] == 1.0
    assert "supersecret" not in log["summary"]
    assert log["content_sha256"]
    assert log["provenance"]["primary_source"] == "opensearch://orders/worker-1"
    assert package["schema_version"] == "1.0"
    assert package["provenance"]["contract_version"] == CONTEXT_CONTRACT_VERSION


def test_stale_operational_evidence_is_not_reusable() -> None:
    context = make_context(stale=True)
    governed = govern_context(
        context,
        tenant_id="tenant-a",
        subject_fingerprint=context_subject_fingerprint(context.alert, "tenant-a"),
    )

    quality = governed.metadata["context_quality"]
    assert quality["reusable"] is False
    assert "logs" in quality["stale_sources"]
    assert governed.metadata["context_sources"]["logs"]["status"] == "stale"


def test_missing_provider_timestamp_is_explicit_and_cannot_claim_full_freshness() -> None:
    context = make_context()
    context.metadata["context_evidence"]["logs"][0].pop("observed_at")

    governed = govern_context(
        context,
        tenant_id="tenant-a",
        subject_fingerprint=context_subject_fingerprint(context.alert, "tenant-a"),
    )

    log = governed.metadata["context_evidence"]["logs"][0]
    source = governed.metadata["context_sources"]["logs"]
    assert log["observed_at_inferred"] is True
    assert log["timestamp_quality"] == "retrieval_fallback"
    assert log["freshness_score"] <= 0.5
    assert source["inferred_timestamp_count"] == 1


def test_governance_preserves_initial_collection_status() -> None:
    context = make_context()
    context.metadata["context_sources"] = {
        "logs": {"attempted": True, "status": "collected"},
        "database": {"attempted": False, "status": "skipped"},
    }

    first = govern_context(context, tenant_id="tenant-a")
    second = govern_context(first, tenant_id="tenant-a")

    assert second.metadata["context_sources"]["logs"]["collection_status"] == "collected"
    assert second.metadata["context_sources"]["database"]["collection_status"] == "skipped"


def test_subject_fingerprint_ignores_ephemeral_pod_but_not_namespace() -> None:
    alert = make_context().alert
    base = context_subject_fingerprint(alert, "tenant-a")
    another_pod = alert.model_copy(update={"labels": {**alert.labels, "pod": "orders-worker-abc"}})
    another_namespace = alert.model_copy(update={"labels": {**alert.labels, "namespace": "staging"}})

    assert context_subject_fingerprint(another_pod, "tenant-a") == base
    assert context_subject_fingerprint(another_namespace, "tenant-a") != base


def test_connector_plan_skips_unjustified_change_probes() -> None:
    alert = make_context().alert.model_copy(
        update={"description": "queue lag is above threshold", "labels": {"application": "orders"}}
    )
    available = [
        "servicenow", "prometheus", "kubernetes", "jenkins", "github",
        "cmdb", "discovery-mcp", "local-evidence", "vector-db",
    ]

    selected, reasons = plan_connectors(alert, available)

    assert set(selected) == {"prometheus", "cmdb", "discovery-mcp", "vector-db"}
    assert "baseline_signal_topology_discovery_knowledge" in reasons
