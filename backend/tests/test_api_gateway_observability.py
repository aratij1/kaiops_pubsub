from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_gateway.control_routes import build_control_router
from api_gateway.modules.users.permissions import AuthContext


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


def _manual_closure_test_app(*, role: str = "Administrator") -> tuple[FastAPI, dict[str, object]]:
    captured: dict[str, object] = {}

    async def guarded_proxy(**kwargs):
        captured.update(kwargs)
        return {"status": "closed"}

    async def auth_context(_request):
        return AuthContext(
            user_id="user-1",
            role=role,
            tenant_id="tenant-a",
            jwt_id="jwt-1",
            session_jti="session-1",
            token_type="access",
            email="reviewer@example.com",
        )

    async def unused_proxy(**_kwargs):
        raise AssertionError("raw proxy should not be called")

    async def load_summary() -> dict[str, int]:
        return {}

    app = FastAPI()
    app.include_router(build_control_router(
        settings=SimpleNamespace(closure_service_url="http://closure-service:8000"),
        guarded_proxy=guarded_proxy,
        raw_proxy=unused_proxy,
        trace_id_from_header=lambda value: value or "test-trace",
        analyzer=SimpleNamespace(),
        load_recent_events=lambda _limit: [],
        build_audit_contract=lambda _event: {},
        load_audit_summary=load_summary,
        auth_context_from_request=auth_context,
    ))
    return app, captured


def test_manual_closure_derives_identity_and_tenant_from_auth_context() -> None:
    app, captured = _manual_closure_test_app()

    response = TestClient(app).post(
        "/incidents/incident%20one/manual-close",
        json={"comment": "Reviewed evidence and accepted the operational risk."},
    )

    assert response.status_code == 200
    assert captured["path"] == "/incidents/incident%20one/manual-close"
    assert captured["payload"] == {
        "comment": "Reviewed evidence and accepted the operational risk.",
        "actor_id": "reviewer@example.com",
        "actor_role": "Administrator",
        "tenant_id": "tenant-a",
        "auth_jti": "jwt-1",
    }


def test_manual_closure_rejects_spoofed_identity_fields() -> None:
    app, captured = _manual_closure_test_app()

    response = TestClient(app).post(
        "/incidents/incident-1/manual-close",
        json={"comment": "Reviewed evidence and accepted the operational risk.", "closed_by": "attacker"},
    )

    assert response.status_code == 422
    assert captured == {}


def test_manual_closure_rejects_unauthorized_role() -> None:
    app, captured = _manual_closure_test_app(role="L1 Operator")

    response = TestClient(app).post(
        "/incidents/incident-1/manual-close",
        json={"comment": "Reviewed evidence and accepted the operational risk."},
    )

    assert response.status_code == 403
    assert captured == {}
