from __future__ import annotations

import pytest

from ai_workbench_common.models import Context
from common.models import Alert, AlertSeverity, Incident
from context_agent.connectors import DiscoveryMCPConnector
from context_agent.context_quality import assess_context


def _alert_and_incident() -> tuple[Alert, Incident]:
    alert = Alert(
        tenant_id="tenant-a",
        source="prometheus",
        name="CheckoutLatencyHigh",
        service="checkout",
        environment="prod",
        severity=AlertSeverity.CRITICAL,
        description="Checkout latency is above threshold",
    )
    return alert, Incident(
        tenant_id=alert.tenant_id,
        service=alert.service,
        environment=alert.environment,
        severity=alert.severity,
        title=alert.name,
    )


def test_internal_service_bypasses_environment_and_explicit_proxy(monkeypatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://environment-proxy.example:8080")
    monkeypatch.setenv("DISCOVERY_MCP_PROXY_URL", "http://user:secret@explicit-proxy.example:8080")
    connector = DiscoveryMCPConnector()

    options, report = connector._client_policy("http://discovery-mcp:8000/mcp")

    assert options == {"timeout": connector.timeout, "trust_env": False}
    assert report == {"target": "internal", "trust_env": False, "proxy": {"configured": False}}


@pytest.mark.parametrize("proxy_url", ["http://proxy.example:8080", "socks5://proxy.example:1080", "socks5h://proxy.example:1080"])
def test_external_proxy_schemes_are_explicit_and_supported(monkeypatch, proxy_url: str) -> None:
    monkeypatch.setenv("DISCOVERY_MCP_PROXY_URL", proxy_url)
    connector = DiscoveryMCPConnector()

    options, report = connector._client_policy("https://discovery.example.com/mcp")

    assert options["trust_env"] is False
    assert options["proxy"] == proxy_url
    assert report["proxy"]["scheme"] == proxy_url.split(":", 1)[0]


def test_proxy_report_redacts_credentials_and_rejects_unsupported_scheme(monkeypatch) -> None:
    connector = DiscoveryMCPConnector()
    report = connector._safe_proxy_description("http://operator:secret@proxy.example:8080")
    assert report["credentials_redacted"] is True
    assert "operator" not in str(report) and "secret" not in str(report)

    monkeypatch.setenv("DISCOVERY_MCP_PROXY_URL", "ftp://proxy.example")
    with pytest.raises(ValueError, match="Unsupported discovery proxy scheme"):
        connector._client_policy("https://discovery.example.com/mcp")


@pytest.mark.asyncio
async def test_client_construction_failure_returns_explicit_evidence_gap(monkeypatch) -> None:
    connector = DiscoveryMCPConnector()
    alert, incident = _alert_and_incident()
    monkeypatch.setattr(connector, "_build_client", lambda _url: (_ for _ in ()).throw(RuntimeError("proxy bootstrap failed")))

    result = await connector.fetch(alert, incident)

    assert result["provider_status"] == "degraded"
    assert result["evidence"] == []
    assert result["evidence_gap"]["reason"] == "discovery_client_unavailable"
    assert result["evidence_gap"]["execution_ready"] is False
    assert result["report"]["insufficient_evidence"] is True


def test_discovery_failure_caps_context_confidence_and_execution_readiness() -> None:
    alert, incident = _alert_and_incident()
    context = Context(
        tenant_id=alert.tenant_id,
        incident_id=incident.id,
        alert=alert,
        deployment="checkout-v42",
        dependency_services=["payments"],
        runbook="Restart checkout only after evidence review.",
        observability={"latency_ms": 2500},
        recent_changes=[{"id": "change-1"}],
        metadata={
            "discovery_report": {
                "provider_status": "degraded",
                "evidence": [],
                "evidence_gap": {"reason": "discovery_client_unavailable"},
            },
            "context_evidence": {},
        },
    )

    quality = assess_context(context)

    assert quality["quality_score"] <= 0.49
    assert quality["execution_ready"] is False
    assert quality["reusable"] is False
    assert "discovery_evidence" in quality["missing_required"]
