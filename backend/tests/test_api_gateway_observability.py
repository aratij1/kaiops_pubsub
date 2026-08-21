from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_gateway.control_routes import build_control_router


class _AuditEvent:
    def __init__(self, sequence: int) -> None:
        self.sequence = sequence

    def model_dump(self, *, mode: str) -> dict[str, object]:
        assert mode == "json"
        return {"id": str(self.sequence), "latency_ms": float(self.sequence + 1)}


def test_recent_observability_supports_dashboard_sample_window() -> None:
    requested_limits: list[int] = []

    async def load_recent_events(limit: int) -> list[_AuditEvent]:
        requested_limits.append(limit)
        return [_AuditEvent(index) for index in range(limit)]

    async def unused_proxy(**_kwargs):
        raise AssertionError("proxy should not be called")

    async def load_summary() -> dict[str, int]:
        return {}

    app = FastAPI()
    app.include_router(
        build_control_router(
            settings=SimpleNamespace(),
            guarded_proxy=unused_proxy,
            raw_proxy=unused_proxy,
            trace_id_from_header=lambda value: value or "test-trace",
            analyzer=SimpleNamespace(),
            load_recent_events=load_recent_events,
            build_audit_contract=lambda event: {"sequence": event.sequence},
            load_audit_summary=load_summary,
        )
    )

    response = TestClient(app).get("/observability/recent?limit=120")

    assert response.status_code == 200
    assert requested_limits == [120]
    assert len(response.json()["events"]) == 120


def test_control_router_owns_the_complete_remediation_gateway_surface() -> None:
    async def unused_proxy(**_kwargs):
        raise AssertionError("proxy should not be called")

    async def load_summary() -> dict[str, int]:
        return {}

    router = build_control_router(
        settings=SimpleNamespace(),
        guarded_proxy=unused_proxy,
        raw_proxy=unused_proxy,
        trace_id_from_header=lambda value: value or "test-trace",
        analyzer=SimpleNamespace(),
        load_recent_events=lambda _limit: [],
        build_audit_contract=lambda _event: {},
        load_audit_summary=load_summary,
    )
    paths = {route.path for route in router.routes}

    assert {
        "/remediation/execute",
        "/remediation/dry-run",
        "/remediation/diagnostic/complete",
        "/remediation/actions/by-incident/{incident_id}/latest",
        "/remediation/actions/{action_id}/emergency-stop",
        "/remediation/reconciliation/terminal-actions",
        "/context/strategy",
        "/context/snapshots/{incident_id}",
    }.issubset(paths)
