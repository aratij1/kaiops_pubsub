from alert_intelligence import AlertIntelligenceAgent
from common.models import Alert, AlertSeverity
import pytest


def make_alert(description: str = "payment latency above threshold") -> Alert:
    return Alert(
        source="prometheus",
        name="PaymentLatencyHigh",
        service="payments",
        severity=AlertSeverity.WARNING,
        description=description,
        labels={"deployment": "payments-api", "team": "payments-sre"},
    )


@pytest.mark.asyncio
async def test_alert_intelligence_deduplicates_and_classifies() -> None:
    agent = AlertIntelligenceAgent()
    first, first_incident = await agent.process(make_alert())
    second, _ = await agent.process(make_alert())

    assert first.severity == AlertSeverity.CRITICAL
    assert second.deduplicated_count == 2
    assert second.correlation_id == first.correlation_id
    assert first_incident.owner_team == "payments-sre"


@pytest.mark.asyncio
async def test_alert_intelligence_uses_embedding_correlation() -> None:
    agent = AlertIntelligenceAgent(correlation_threshold=0.2)
    first, _ = await agent.process(make_alert("checkout payment latency high"))
    correlated, _ = await agent.process(make_alert("payment checkout latency degraded"))

    assert correlated.correlation_id == first.correlation_id


@pytest.mark.asyncio
async def test_alert_intelligence_uses_enterprise_correlation_evidence() -> None:
    agent = AlertIntelligenceAgent(correlation_threshold=0.72)
    first, _ = await agent.process(
        Alert(
            source="prometheus",
            name="PaymentLatencyHigh",
            service="payments-api",
            severity=AlertSeverity.HIGH,
            description="checkout p95 latency above threshold after deployment 2.5",
            labels={
                "team": "payments-sre",
                "deployment": "payments-api",
                "namespace": "checkout",
                "dependency": "ledger-api",
                "metric": "http_request_duration_seconds",
            },
        )
    )
    correlated, _ = await agent.process(
        Alert(
            source="prometheus",
            name="PaymentTimeoutRateHigh",
            service="checkout",
            severity=AlertSeverity.HIGH,
            description="payment timeout rate degraded for checkout path",
            labels={
                "team": "payments-sre",
                "deployment": "payments-api",
                "namespace": "checkout",
                "upstream": "payments-api",
                "dependency": "ledger-api",
                "metric": "http_request_duration_seconds",
            },
        )
    )

    assert correlated.correlation_id == first.correlation_id
    assert correlated.metadata["correlation"]["matched"] is True
    assert correlated.metadata["correlation"]["evidence"]["deployment_change"] > 0
    assert "ledger" in correlated.metadata["correlation"]["evidence"]["topology_overlap"]


@pytest.mark.asyncio
async def test_alert_intelligence_does_not_correlate_unrelated_services() -> None:
    agent = AlertIntelligenceAgent(correlation_threshold=0.72)
    first, _ = await agent.process(make_alert("payment latency above threshold"))
    unrelated, _ = await agent.process(
        Alert(
            source="prometheus",
            name="WarehouseDiskUsageHigh",
            service="warehouse-storage",
            severity=AlertSeverity.WARNING,
            description="warehouse disk usage crossed warning threshold",
            labels={"deployment": "warehouse-storage", "team": "data-platform", "metric": "disk_usage_percent"},
        )
    )

    assert unrelated.correlation_id != first.correlation_id
    assert unrelated.metadata["correlation"]["matched"] is False
