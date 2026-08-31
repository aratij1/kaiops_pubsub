from __future__ import annotations

from common.config import get_settings
from common.service import create_app
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field


class ValidatedPayload(BaseModel):
    count: int = Field(ge=1, le=10)


def error_contract_app():
    settings = get_settings()
    settings.service_name = "error-contract-test"
    settings.database_enabled = False
    app = create_app(title="Error contract test", settings=settings)

    @app.post("/validated")
    async def validated(payload: ValidatedPayload):
        return payload

    @app.get("/missing")
    async def missing():
        raise HTTPException(status_code=404, detail="Incident was not found")

    @app.get("/unexpected")
    async def unexpected():
        raise RuntimeError("database password must never reach the client")

    @app.get("/busy")
    async def busy():
        raise HTTPException(
            status_code=409,
            detail={"code": "target_execution_busy", "message": "Target is busy.", "retryable": True},
        )

    return app


def test_validation_error_is_safe_versioned_and_traceable() -> None:
    response = TestClient(error_contract_app()).post(
        "/validated",
        headers={"x-trace-id": "validation-trace"},
        json={"count": 99, "password": "do-not-echo"},
    )

    assert response.status_code == 422
    assert response.headers["x-trace-id"] == "validation-trace"
    assert response.json()["error"]["contract_version"] == "kaiops.error.v1"
    assert response.json()["error"]["code"] == "request_validation_failed"
    assert response.json()["error"]["validation_errors"][0]["location"] == ["body", "count"]
    assert "do-not-echo" not in response.text


def test_http_error_preserves_detail_and_adds_machine_contract() -> None:
    response = TestClient(error_contract_app()).get("/missing")

    assert response.status_code == 404
    assert response.json()["detail"] == "Incident was not found"
    assert response.json()["error"]["code"] == "http_404"
    assert response.json()["error"]["retryable"] is False
    assert response.json()["trace_id"]


def test_unhandled_error_does_not_leak_internal_exception() -> None:
    response = TestClient(error_contract_app(), raise_server_exceptions=False).get("/unexpected")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert response.json()["error"]["retryable"] is False
    assert "database password" not in response.text


def test_structured_conflict_can_be_declared_retryable() -> None:
    response = TestClient(error_contract_app()).get("/busy")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "target_execution_busy"
    assert response.json()["error"]["message"] == "Target is busy."
    assert response.json()["error"]["retryable"] is True


def test_build_info_exposes_safe_release_contract(monkeypatch) -> None:
    monkeypatch.setenv("KAIMS_RELEASE_SHA", "abc123")
    monkeypatch.setenv("KAIMS_BUILD_TIME", "2026-08-31T11:00:00Z")

    response = TestClient(error_contract_app()).get("/build-info")

    assert response.status_code == 200
    assert response.json() == {
        "service": "error-contract-test",
            "release_sha": "abc123",
            "build_time": "2026-08-31T11:00:00Z",
            "schema_version": "20260923_schema_migration_checksums",
            "contract_versions": {"context_enrichment": "kaiops.context-enrichment.v1"},
    }
