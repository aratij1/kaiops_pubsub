from __future__ import annotations

import json
from pathlib import Path

from common.models import ApplicationRegistration
from common.monitoring_onboarding import (
    DiscoveryAgent,
    scan_codebase,
    scan_logs,
)


def _make_fault_app(root: Path) -> Path:
    """Create a minimal tree that mimics the vendored fault-lab app."""
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "runtime").mkdir(parents=True, exist_ok=True)
    (root / "fault_lab.py").write_text(
        "from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer\n"
        "def do_GET(self):\n"
        "    if self.path == '/metrics':\n"
        "        return self.send_body(200, self.lab.prometheus())\n"
        "parser.add_argument('--port', type=int, default=8080)\n",
        encoding="utf-8",
    )
    (root / "Dockerfile").write_text("FROM python:3.12-slim\nEXPOSE 8080\n", encoding="utf-8")
    (root / "data" / "tickets.csv").write_text(
        "Issue ID,Service,Component/s,Labels\n"
        "KAI-1,checkout-api,Application,\"kaiops,kaiops-scenario-01\"\n"
        "KAI-2,orders-api,Queue,\"kaiops,kaiops-scenario-07\"\n"
        "KAI-3,checkout-api,Application,\"kaiops,kaiops-scenario-01\"\n",
        encoding="utf-8",
    )
    log_lines = [
        {"level": "ERROR", "service": "checkout-api", "component": "Application", "scenario_id": "kaiops-scenario-01", "alert_name": "High error rate", "message": "boom"},
        {"level": "INFO", "service": "checkout-api", "component": "Application", "scenario_id": "kaiops-scenario-01", "alert_name": "High error rate", "message": "ok"},
        {"level": "ERROR", "service": "orders-api", "component": "Queue", "scenario_id": "kaiops-scenario-07", "alert_name": "Consumer lag", "message": "lag"},
    ]
    (root / "runtime" / "application.log").write_text(
        "\n".join(json.dumps(line) for line in log_lines), encoding="utf-8"
    )
    return root


def test_scan_codebase_discovers_context(tmp_path: Path) -> None:
    root = _make_fault_app(tmp_path / "fault-lab")
    scan = scan_codebase(root)

    assert scan["technology"] == "python-http-server"
    assert scan["metrics_path"] == "/metrics"
    assert scan["metrics_port"] == "8080"
    assert "checkout-api" in scan["services"]
    assert "orders-api" in scan["services"]
    assert set(scan["scenarios"]) == {"kaiops-scenario-01", "kaiops-scenario-07"}
    assert scan["files_scanned"] >= 1


def test_scan_codebase_missing_root_is_safe() -> None:
    scan = scan_codebase(Path("/does/not/exist"))
    assert scan["services"] == []
    assert scan["technology"] == ""
    assert scan["files_scanned"] == 0


def test_scan_logs_extracts_runtime_activity(tmp_path: Path) -> None:
    root = _make_fault_app(tmp_path / "fault-lab")
    scan = scan_logs(root / "runtime" / "application.log")

    assert "checkout-api" in scan["services"]
    assert "orders-api" in scan["services"]
    assert set(scan["active_scenarios"]) == {"kaiops-scenario-01", "kaiops-scenario-07"}
    assert scan["error_count"] == 2
    assert scan["levels"].get("ERROR") == 2
    assert len(scan["recent_errors"]) == 2


def test_scan_logs_missing_file_is_safe() -> None:
    scan = scan_logs(None)
    assert scan["services"] == []
    assert scan["error_count"] == 0


async def test_discovery_agent_surfaces_scanned_context(tmp_path: Path, monkeypatch) -> None:
    root = _make_fault_app(tmp_path / "fault-lab")
    monkeypatch.setenv("DISCOVERY_CODEBASE_ROOT", str(root))
    monkeypatch.setenv("DISCOVERY_LOG_PATH", str(root / "runtime" / "application.log"))

    application = ApplicationRegistration(
        tenant_id="tenant-a",
        name="checkout-api",
        owner_team="payments-sre",
        owner_email="payments@example.com",
        environment="prod",
        namespace="payments",
        region="us-east-1",
        technology="",
        metrics_endpoint="",
        labels={"workload_kind": "Deployment"},
    )

    result = await DiscoveryAgent().run(application)

    # Technology and metrics endpoint are derived from the codebase, not the (empty) payload.
    assert result.technology == "python-http-server"
    assert result.metrics_endpoint.endswith(":8080/metrics")
    # Discovered services from code + logs appear as resources and labels.
    discovered = {res.get("name") for res in result.discovered_resources if res.get("kind") == "DiscoveredService"}
    assert {"checkout-api", "orders-api"} <= discovered
    assert "checkout-api" in result.labels["discovered_services"]
    assert "kaiops-scenario-01" in result.labels["active_scenarios"]
    assert result.labels["log_error_count"] == "2"


async def test_discovery_agent_without_scan_root_falls_back(tmp_path: Path, monkeypatch) -> None:
    # No scan root -> behave like the payload-only discovery (backward compatible).
    monkeypatch.setenv("DISCOVERY_CODEBASE_ROOT", str(tmp_path / "missing"))
    monkeypatch.delenv("DISCOVERY_LOG_PATH", raising=False)

    application = ApplicationRegistration(
        tenant_id="tenant-a",
        name="billing-api",
        owner_team="billing",
        owner_email="billing@example.com",
        environment="prod",
        namespace="billing",
        region="us-east-1",
        technology="python-fastapi",
        metrics_endpoint="http://billing-api:8000/metrics",
        labels={"workload_kind": "Deployment"},
    )

    result = await DiscoveryAgent().run(application)

    assert result.technology == "python-fastapi"
    assert result.metrics_endpoint == "http://billing-api:8000/metrics"
    assert "discovered_services" not in result.labels
    # Only the payload-derived resources remain.
    assert all(res.get("kind") != "DiscoveredService" for res in result.discovered_resources)
