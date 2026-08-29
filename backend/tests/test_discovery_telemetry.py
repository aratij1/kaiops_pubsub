import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "src" / "discovery-mcp" / "app.py"
SPEC = importlib.util.spec_from_file_location("discovery_mcp_telemetry_app", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_telemetry_project_routes_code_search_to_astronomy_shop(monkeypatch):
    project_root = Path("/workspace/external/telemetry/opentelemetry-demo")
    monkeypatch.setattr(
        MODULE,
        "_project_catalog",
        lambda: {
            "telemetry": {
                "name": "telemetry",
                "aliases": ["astronomy-shop"],
                "code_roots": [str(project_root)],
            }
        },
    )

    roots = MODULE._code_roots({"project": "telemetry", "terms": ["payment"]})

    assert roots == [project_root]


def test_telemetry_tool_is_published():
    names = {tool["name"] for tool in MODULE.TOOLS}
    assert "telemetry.search" in names


def test_kaiops_project_exposes_internal_prometheus_and_jaeger():
    catalog_path = Path(__file__).parents[1] / "config" / "discovery-projects.json"
    kaiops = json.loads(catalog_path.read_text(encoding="utf-8"))["projects"]["kaiops"]

    assert kaiops["telemetry"]["prometheus_url"] == "http://prometheus:9090"
    assert kaiops["telemetry"]["jaeger_url"] == "http://jaeger:16686"


def test_trace_summary_preserves_causal_diagnostics():
    trace = {
        "traceID": "trace-1",
        "processes": {"p1": {"serviceName": "api-gateway"}, "p2": {"serviceName": "mysql"}},
        "spans": [{
            "operationName": "GET /alerts/{alert_id}/processed-result",
            "duration": 4_200_000,
            "tags": [{"key": "http.status_code", "value": 503}],
            "logs": [],
        }],
    }

    summary = MODULE._trace_evidence_summary(trace, "/alerts/abc/processed-result")

    assert summary["duration_ms"] == 4200.0
    assert summary["http_status_codes"] == [503]
    assert summary["services"] == ["api-gateway", "mysql"]
    assert set(summary["diagnostic_signals"]) == {"http_5xx", "high_latency"}


def test_jaeger_operation_normalizes_alert_uuid_and_query_string():
    operation = "/alerts/ab4e7d57-e348-48a3-95bd-4ff1fcae6ca4/processed-result?tenant_id=default"

    assert MODULE._jaeger_operation(operation) == "GET /alerts/{alert_id}/processed-result"
