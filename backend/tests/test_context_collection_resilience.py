from __future__ import annotations

import pytest

from common.models import Alert, AlertSeverity, Incident
from context_agent import ContextIntelligenceAgent
from context_agent.connectors import BaseConnector


class HealthyPrometheus(BaseConnector):
    name = "prometheus"

    async def fetch(self, alert: Alert, incident: Incident) -> dict[str, object]:
        return {"latency_p95_ms": 420, "error_rate": 0.01, "alerts_cleared": False}


class FailedKubernetes(BaseConnector):
    name = "kubernetes"

    async def fetch(self, alert: Alert, incident: Incident) -> dict[str, object]:
        raise RuntimeError("cluster API unavailable")


@pytest.mark.asyncio
async def test_context_collection_preserves_healthy_evidence_when_a_connector_fails() -> None:
    alert = Alert(
        tenant_id="tenant-a",
        source="prometheus",
        name="CheckoutLatencyHigh",
        service="checkout",
        severity=AlertSeverity.HIGH,
        description="latency is elevated",
    )
    incident = Incident(tenant_id="tenant-a", service="checkout", severity=AlertSeverity.HIGH, title="checkout latency")

    context = await ContextIntelligenceAgent(connectors=[HealthyPrometheus(), FailedKubernetes()]).collect(alert, incident)

    graph = context.metadata["context_graph"]
    assert context.observability["latency_p95_ms"] == 420
    assert graph["collected_count"] == 1
    assert graph["degraded"] is True
    assert graph["connectors"]["prometheus"]["status"] == "collected"
    assert graph["connectors"]["kubernetes"]["status"] == "failed"
    assert graph["connectors"]["kubernetes"]["error_type"] == "RuntimeError"
