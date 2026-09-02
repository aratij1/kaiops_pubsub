import importlib.util
import json
from pathlib import Path

import pytest


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


def test_project_resolves_unique_service_catalog_match(monkeypatch, tmp_path):
    kaiops_root = tmp_path / "kaiops"
    telemetry_root = tmp_path / "telemetry"
    (kaiops_root / "api-gateway").mkdir(parents=True)
    telemetry_root.mkdir()
    monkeypatch.setattr(
        MODULE,
        "_project_catalog",
        lambda: {
            "kaiops": {"service_catalog_root": str(kaiops_root)},
            "telemetry": {"service_catalog_root": str(telemetry_root)},
        },
    )

    project_id, project = MODULE._project_for({"service": "api-gateway"})

    assert project_id == "kaiops"
    assert project["service_catalog_root"] == str(kaiops_root)


def test_project_does_not_guess_when_service_matches_multiple_catalogs(monkeypatch, tmp_path):
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    (first_root / "shared-service").mkdir(parents=True)
    (second_root / "shared-service").mkdir(parents=True)
    monkeypatch.setattr(
        MODULE,
        "_project_catalog",
        lambda: {
            "first": {"service_catalog_root": str(first_root)},
            "second": {"service_catalog_root": str(second_root)},
        },
    )

    assert MODULE._project_for({"service": "shared-service"}) == ("", {})


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
            "spanID": "root", "processID": "p1",
            "operationName": "GET /alerts/{alert_id}/processed-result",
            "duration": 4_200_000,
            "tags": [{"key": "http.status_code", "value": 503}],
            "logs": [],
        }, {
            "spanID": "child", "processID": "p2", "operationName": "SELECT", "duration": 900_000,
            "references": [{"refType": "CHILD_OF", "spanID": "root"}],
            "tags": [{"key": "db.system", "value": "mysql"}], "logs": [],
        }],
    }

    summary = MODULE._trace_evidence_summary(trace, "/alerts/abc/processed-result")

    assert summary["duration_ms"] == 4200.0
    assert summary["http_status_codes"] == [503]
    assert summary["services"] == ["api-gateway", "mysql"]
    assert set(summary["diagnostic_signals"]) == {"http_5xx", "high_latency"}
    assert summary["slowest_spans"][1]["tags"]["db.system"] == "mysql"
    assert summary["dependency_edges"] == [{"upstream": "api-gateway", "downstream": "mysql"}]


def test_jaeger_operation_normalizes_alert_uuid_and_query_string():
    operation = "/alerts/ab4e7d57-e348-48a3-95bd-4ff1fcae6ca4/processed-result?tenant_id=default"

    assert MODULE._jaeger_operation(operation) == "GET /alerts/{alert_id}/processed-result"


@pytest.mark.asyncio
async def test_missing_bound_trace_falls_back_to_incident_scoped_jaeger_search(monkeypatch):
    trace = {
        "traceID": "fallback-trace",
        "processes": {"p1": {"serviceName": "api-gateway"}},
        "spans": [{
            "spanID": "root", "processID": "p1",
            "operationName": "GET /alerts/{alert_id}/processed-result",
            "duration": 2_500_000, "startTime": 1_788_315_300_000_000,
            "tags": [], "logs": [],
        }],
    }

    class Response:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

        def json(self):
            return self._payload

    class Client:
        def __init__(self, *args, **kwargs):
            self.calls = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, params=None):
            self.calls.append((url, params))
            if url.endswith("/api/traces/missing-correlation-id"):
                return Response(404, {})
            if url.endswith("/api/traces"):
                if params and params.get("operation"):
                    return Response(200, {"data": []})
                return Response(200, {"data": [trace]})
            return Response(200, {"data": {"result": []}})

    monkeypatch.setattr(MODULE.httpx, "AsyncClient", Client)
    monkeypatch.setattr(MODULE, "_project_catalog", lambda: {
        "kaiops": {
            "aliases": ["kaiops"],
            "telemetry": {
                "prometheus_url": "http://prometheus:9090",
                "jaeger_url": "http://jaeger:16686",
            },
        },
    })

    result = await MODULE._search_traces({
        "project": "kaiops", "service": "api-gateway",
        "trace_id": "missing-correlation-id",
        "operation": "/alerts/abc/processed-result?tenant_id=default",
        "start_time": "2026-09-02T02:14:00Z", "end_time": "2026-09-02T02:34:00Z",
        "limit": 5,
    })

    assert result["result_count"] == 1
    assert result["evidence"][0]["trace_id"] == "fallback-trace"
    jaeger = next(source for source in result["sources"] if source["source"] == "jaeger")
    assert jaeger["bound_trace_fallback"] is True
    assert jaeger["operation_filter_fallback"] is True
    assert result["evidence_gap"] == ""

    unbound_result = await MODULE._search_traces({
        "project": "kaiops", "service": "api-gateway",
        "operation": "/alerts/abc/processed-result?tenant_id=default",
        "start_time": "2026-09-02T02:14:00Z", "end_time": "2026-09-02T02:34:00Z",
        "limit": 5,
    })
    assert unbound_result["result_count"] == 1
    unbound_jaeger = next(source for source in unbound_result["sources"] if source["source"] == "jaeger")
    assert unbound_jaeger["operation_filter_fallback"] is True
