from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_validation_failure_has_durable_automatic_rollback_path() -> None:
    workflow = (ROOT / "backend/src/temporal-pilot/temporal_pilot/workflow.py").read_text(encoding="utf-8")
    activities = (ROOT / "backend/src/temporal-pilot/temporal_pilot/activities.py").read_text(encoding="utf-8")
    worker = (ROOT / "backend/src/temporal-pilot/temporal_pilot/worker.py").read_text(encoding="utf-8")
    assert 'status != "validation_failed"' in workflow
    assert '"rollback_remediation_action"' in workflow
    assert '"/rollback-direct"' in activities
    assert '"/rollback-reconcile-direct"' in activities
    assert '"/rollback-timeout-direct"' in activities
    assert "rollback_remediation_action" in worker


def test_rollback_endpoint_uses_only_approved_plan_commands_and_escalates() -> None:
    app = (ROOT / "backend/src/remediation-engine/app.py").read_text(encoding="utf-8")
    start = app.index('@app.post("/rollback-direct"')
    end = app.index('@app.post("/execution-failed"', start)
    endpoint = app[start:end]
    assert 'plan.get("rollback_commands"' in endpoint
    assert "approved_rollback_unavailable" in endpoint
    assert "automatic_rollback_failed" in app
    assert "RemediationStatus.ROLLED_BACK" in endpoint
    assert "engine.dispatch(action)" in endpoint
    assert "engine.execute(action)" not in endpoint
    assert "llm" not in endpoint.lower()
