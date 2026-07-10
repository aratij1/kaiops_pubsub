from __future__ import annotations

import pytest
from common.models import Alert, AlertSeverity, Incident
from context_agent import ContextIntelligenceAgent


@pytest.mark.asyncio
async def test_context_agent_registers_connector_tools() -> None:
    agent = ContextIntelligenceAgent()

    assert "connector.prometheus" in agent.tool_registry.tools
    assert "connector.cmdb" in agent.tool_registry.tools
    assert "connector.vector-db" in agent.tool_registry.tools


@pytest.mark.asyncio
async def test_context_agent_connector_tool_executes_with_permissions() -> None:
    agent = ContextIntelligenceAgent()
    alert = Alert(
        source="prometheus",
        name="PaymentLatencyHigh",
        service="payments",
        severity=AlertSeverity.CRITICAL,
        description="payment latency after deployment",
    )
    incident = Incident(service="payments", severity=AlertSeverity.CRITICAL, title="payments latency")

    result = await agent.tool_registry.execute(
        "connector.prometheus",
        {
            "alert": alert.model_dump(mode="json"),
            "incident": incident.model_dump(mode="json"),
        },
        role="context-agent",
    )

    assert isinstance(result, dict)
    assert "latency_p95_ms" in result


@pytest.mark.asyncio
async def test_context_agent_connector_tool_denies_unauthorized_role() -> None:
    agent = ContextIntelligenceAgent()
    alert = Alert(
        source="prometheus",
        name="PaymentLatencyHigh",
        service="payments",
        severity=AlertSeverity.CRITICAL,
        description="payment latency after deployment",
    )
    incident = Incident(service="payments", severity=AlertSeverity.CRITICAL, title="payments latency")

    with pytest.raises(PermissionError):
        await agent.tool_registry.execute(
            "connector.prometheus",
            {
                "alert": alert.model_dump(mode="json"),
                "incident": incident.model_dump(mode="json"),
            },
            role="readonly",
        )
