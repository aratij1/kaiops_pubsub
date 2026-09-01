from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio

_APP_PATH = Path(__file__).resolve().parents[2] / "ai-workbench" / "src" / "evaluation-service" / "app.py"
_SPEC = importlib.util.spec_from_file_location("evaluation_service_app", _APP_PATH)
assert _SPEC is not None and _SPEC.loader is not None
evaluation_service_app = importlib.util.module_from_spec(_SPEC)
# Register before exec so pydantic's forward-ref resolution (from `from __future__ import
# annotations` in app.py) can find this module's namespace (e.g. `typing.Any`) by name.
sys.modules[_SPEC.name] = evaluation_service_app
_SPEC.loader.exec_module(evaluation_service_app)


@pytest_asyncio.fixture
async def eval_client(sqlite_session_factory, monkeypatch):
    monkeypatch.setattr(evaluation_service_app.settings, "database_enabled", True)
    monkeypatch.setattr(evaluation_service_app.app.state, "session_factory", sqlite_session_factory, raising=False)
    transport = httpx.ASGITransport(app=evaluation_service_app.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def test_summary_route_registered_before_parameterized_id_route() -> None:
    # Regression guard: if /evaluations/{evaluation_id} were registered first, a request to
    # /evaluations/summary would be captured by it (evaluation_id="summary") instead.
    paths = [
        route.path for route in evaluation_service_app.app.routes
        if getattr(route, "path", "").startswith("/evaluations")
    ]
    assert paths.index("/evaluations/summary") < paths.index("/evaluations/{evaluation_id}")
    assert paths.index("/evaluations/autonomy/assess") < paths.index("/evaluations/{evaluation_id}")


@pytest.mark.asyncio
async def test_autonomy_assessment_is_read_only_and_stops_at_hitl(eval_client: httpx.AsyncClient) -> None:
    response = await eval_client.post("/evaluations/autonomy/assess", json={
        "tenant_id": "tenant-a", "service": "payments-api", "action_type": "restart_service",
        "current_tier": "HITL", "reviewed_attempts": 30, "successful_attempts": 30,
        "rollback_attempts": 0, "operator_corrections": 0, "critical_failures": 0,
        "calibration_samples": [{"confidence": 1.0, "correct": True} for _ in range(30)],
        "approved_runbook": True, "rollback_tested": True,
        "credential_scope_verified": True, "blast_radius_verified": True,
    })

    assert response.status_code == 200
    assert response.json()["disposition"] == "HOLD"
    assert response.json()["recommended_tier"] == "HITL"


@pytest.mark.asyncio
async def test_create_and_get_evaluation_round_trip(eval_client: httpx.AsyncClient) -> None:
    incident_id = str(uuid4())
    recommendation_id = str(uuid4())
    create_response = await eval_client.post(
        "/evaluations",
        json={
            "report": {"overall_score": 0.84, "quality_label": "high", "requires_review": False},
            "agent": "resolution-agent",
            "incident_id": incident_id,
            "recommendation_id": recommendation_id,
            "model_provider": "groq",
            "model_name": "llama-3.3-70b-versatile",
        },
    )
    assert create_response.status_code == 201
    evaluation_id = create_response.json()["id"]

    get_response = await eval_client.get(f"/evaluations/{evaluation_id}")
    assert get_response.status_code == 200
    body = get_response.json()
    assert body["agent"] == "resolution-agent"
    assert body["incident_id"] == incident_id
    assert body["overall_score"] == 0.84
    assert body["feedback"] is None


@pytest.mark.asyncio
async def test_create_evaluation_rejects_empty_report(eval_client: httpx.AsyncClient) -> None:
    response = await eval_client.post("/evaluations", json={"report": {}, "agent": "resolution-agent"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_evaluation_accepts_non_deterministic_report_shape(eval_client: httpx.AsyncClient) -> None:
    # model-router's judge-only report is a different, equally valid shape (Step H).
    response = await eval_client.post(
        "/evaluations",
        json={
            "report": {"contract_version": "kaiops.evaluation.judge.v1", "provider": "llm-judge", "metrics": []},
            "agent": "model-router",
        },
    )
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_create_evaluation_persists_typed_memory_trace_and_outcome(eval_client: httpx.AsyncClient) -> None:
    incident_id = str(uuid4())
    now = datetime.now(UTC)
    response = await eval_client.post("/evaluations", json={
        "report": {"overall_score": 0.96}, "agent": "resolution-agent", "incident_id": incident_id,
        "outcome_label": "RECOVERED",
        "incident_memory": {
            "tenant_id": "tenant-a", "incident_id": incident_id, "service": "payments-api",
            "environment": "prod", "issue_signature": "sig-1", "root_cause": "Pool exhaustion",
            "resolution_option_id": "restart", "execution_id": str(uuid4()), "outcome": "RECOVERED",
            "validation_evidence_ids": ["validation:1"], "rollback_disposition": "NOT_REQUIRED",
            "operator_reviewed": True,
        },
        "agent_trace": {
            "trace_id": "trace-1", "tenant_id": "tenant-a", "incident_id": incident_id,
            "agent": "resolution-agent", "started_at": now.isoformat(), "completed_at": now.isoformat(),
            "tool_calls": 4, "outcome": "completed",
        },
    })

    assert response.status_code == 201
    record = await eval_client.get(f"/evaluations/{response.json()['id']}")
    assert record.json()["report"]["outcome_label"] == "RECOVERED"
    assert record.json()["report"]["incident_memory"]["operator_reviewed"] is True
    assert record.json()["report"]["agent_trace"]["tool_calls"] == 4


@pytest.mark.asyncio
async def test_create_evaluation_persists_non_executing_differentiator_artifacts(eval_client: httpx.AsyncClient) -> None:
    incident_id = str(uuid4())
    response = await eval_client.post("/evaluations", json={
        "report": {"overall_score": 0.9}, "agent": "resolution-agent", "incident_id": incident_id,
        "code_patch_proposals": [{
            "tenant_id": "tenant-a", "incident_id": incident_id, "repository_id": "payments",
            "base_revision": "abc123", "source_uri": "repo://payments/app.py", "title": "Bound the pool",
            "explanation": "Evidence-backed review proposal", "unified_diff": "--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new",
            "supporting_code_evidence_ids": ["CODE-1"], "test_plan": ["Run pool tests"],
        }],
        "preventive_recommendations": [{
            "tenant_id": "tenant-a", "service": "payments-api", "risk_signal": "Pool pressure rising",
            "forecast_window_seconds": 3600, "confidence": 0.8, "evidence_ids": ["METRIC-1", "METRIC-2"],
            "recommended_review": "Review capacity before the forecast window.",
        }],
    })

    assert response.status_code == 201
    record = await eval_client.get(f"/evaluations/{response.json()['id']}")
    report = record.json()["report"]
    assert report["code_patch_proposals"][0]["executable"] is False
    assert report["preventive_recommendations"][0]["execution_authorized"] is False


@pytest.mark.asyncio
async def test_get_evaluation_returns_404_when_missing(eval_client: httpx.AsyncClient) -> None:
    response = await eval_client.get(f"/evaluations/{uuid4()}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_evaluation_returns_422_for_malformed_id(eval_client: httpx.AsyncClient) -> None:
    response = await eval_client.get("/evaluations/not-a-uuid")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_evaluations_filters_by_incident_id(eval_client: httpx.AsyncClient) -> None:
    incident_id = str(uuid4())
    await eval_client.post(
        "/evaluations",
        json={"report": {"overall_score": 0.5}, "agent": "resolution-agent", "incident_id": incident_id},
    )
    await eval_client.post("/evaluations", json={"report": {"overall_score": 0.6}, "agent": "resolution-agent"})

    response = await eval_client.get("/evaluations", params={"incident_id": incident_id})
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["evaluations"][0]["incident_id"] == incident_id


@pytest.mark.asyncio
async def test_summary_endpoint_returns_expected_aggregates(eval_client: httpx.AsyncClient) -> None:
    await eval_client.post(
        "/evaluations",
        json={"report": {"overall_score": 0.9, "quality_label": "high"}, "agent": "resolution-agent"},
    )
    await eval_client.post(
        "/evaluations",
        json={
            "report": {"overall_score": 0.3, "quality_label": "low", "requires_review": True},
            "agent": "resolution-agent",
        },
    )

    response = await eval_client.get("/evaluations/summary", params={"agent": "resolution-agent"})
    assert response.status_code == 200
    body = response.json()
    assert body["total_evaluations"] == 2
    assert body["average_overall_score"] == 0.6
    assert body["requires_review_rate"] == 0.5


@pytest.mark.asyncio
async def test_summary_endpoint_on_empty_store_does_not_error(eval_client: httpx.AsyncClient) -> None:
    response = await eval_client.get("/evaluations/summary")
    assert response.status_code == 200
    assert response.json()["total_evaluations"] == 0


@pytest.mark.asyncio
async def test_feedback_updates_existing_evaluation(eval_client: httpx.AsyncClient) -> None:
    recommendation_id = str(uuid4())
    create_response = await eval_client.post(
        "/evaluations",
        json={"report": {"overall_score": 0.81}, "agent": "resolution-agent", "recommendation_id": recommendation_id},
    )
    evaluation_id = create_response.json()["id"]

    feedback_response = await eval_client.post(
        f"/evaluations/by-recommendation/{recommendation_id}/feedback",
        json={"decision": "approved", "approver": "alice", "comment": "looks good"},
    )
    assert feedback_response.status_code == 200
    assert feedback_response.json() == {"updated": True}

    get_response = await eval_client.get(f"/evaluations/{evaluation_id}")
    assert get_response.json()["feedback"] == {"decision": "approved", "approver": "alice", "comment": "looks good"}


@pytest.mark.asyncio
async def test_feedback_for_unknown_recommendation_returns_updated_false(eval_client: httpx.AsyncClient) -> None:
    response = await eval_client.post(
        f"/evaluations/by-recommendation/{uuid4()}/feedback",
        json={"decision": "approved"},
    )
    assert response.status_code == 200
    assert response.json() == {"updated": False}


@pytest.mark.asyncio
async def test_incorrect_feedback_requires_reason_category(eval_client: httpx.AsyncClient) -> None:
    response = await eval_client.post(
        f"/evaluations/by-recommendation/{uuid4()}/feedback",
        json={"decision": "incorrect", "comment": "The proposed cause does not match the logs."},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_structured_feedback_is_persisted(eval_client: httpx.AsyncClient) -> None:
    recommendation_id = str(uuid4())
    create_response = await eval_client.post(
        "/evaluations",
        json={"report": {"overall_score": 0.5}, "agent": "resolution-agent", "recommendation_id": recommendation_id},
    )
    evaluation_id = create_response.json()["id"]
    payload = {
        "decision": "incomplete",
        "approver": "reviewer@example.com",
        "reason_category": "missing_evidence",
        "missing_evidence": "Deployment change history",
        "corrected_cause": "Not established",
        "comment": "Collect change events before approving remediation.",
    }
    response = await eval_client.post(f"/evaluations/by-recommendation/{recommendation_id}/feedback", json=payload)
    assert response.status_code == 200
    record = await eval_client.get(f"/evaluations/{evaluation_id}")
    assert record.json()["feedback"] == payload


@pytest.mark.asyncio
async def test_endpoints_return_503_when_database_disabled(monkeypatch) -> None:
    monkeypatch.setattr(evaluation_service_app.settings, "database_enabled", False)
    monkeypatch.setattr(evaluation_service_app.app.state, "session_factory", None, raising=False)
    transport = httpx.ASGITransport(app=evaluation_service_app.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        create = await client.post("/evaluations", json={"report": {"overall_score": 1.0}, "agent": "x"})
        get = await client.get(f"/evaluations/{uuid4()}")
        listing = await client.get("/evaluations")
        summary = await client.get("/evaluations/summary")
        feedback = await client.post(
            f"/evaluations/by-recommendation/{uuid4()}/feedback", json={"decision": "approved"}
        )

    assert create.status_code == 503
    assert get.status_code == 503
    assert listing.status_code == 503
    assert summary.status_code == 503
    assert feedback.status_code == 503
