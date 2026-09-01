from datetime import datetime, timedelta, timezone

from monitoring_adapter.dedup import compute_fingerprint
from monitoring_adapter.jira_admission import JiraAdmissionState


def _state(tmp_path, **overrides):
    options = {
        "recurrence_window_seconds": 300,
        "comment_cooldown_seconds": 900,
        "max_new_issues_per_hour": 2,
        "min_occurrences": {"logs": 3, "prometheus": 1, "email": 1},
    }
    options.update(overrides)
    return JiraAdmissionState(tmp_path / "admission.json", **options)


def test_log_requires_recurrence_before_create(tmp_path) -> None:
    state = _state(tmp_path)
    now = datetime(2026, 7, 26, tzinfo=timezone.utc)

    first = state.evaluate(fingerprint="same", source="logs", severity="warning", has_open_ticket=False, now=now)
    second = state.evaluate(
        fingerprint="same",
        source="logs",
        severity="warning",
        has_open_ticket=False,
        now=now + timedelta(seconds=20),
    )
    third = state.evaluate(
        fingerprint="same",
        source="logs",
        severity="warning",
        has_open_ticket=False,
        now=now + timedelta(seconds=40),
    )

    assert first.action == "deferred"
    assert second.action == "deferred"
    assert third.allowed is True
    assert third.action == "create"


def test_critical_bypasses_recurrence_and_creation_is_rate_limited(tmp_path) -> None:
    state = _state(tmp_path, max_new_issues_per_hour=1)
    now = datetime(2026, 7, 26, tzinfo=timezone.utc)

    first = state.evaluate(fingerprint="one", source="logs", severity="critical", has_open_ticket=False, now=now)
    second = state.evaluate(
        fingerprint="two",
        source="email",
        severity="critical",
        has_open_ticket=False,
        now=now + timedelta(seconds=1),
    )

    assert first.action == "create"
    assert second.action == "rate_limited"


def test_existing_ticket_comment_has_cooldown(tmp_path) -> None:
    state = _state(tmp_path)
    now = datetime(2026, 7, 26, tzinfo=timezone.utc)

    first = state.evaluate(fingerprint="same", source="logs", severity="warning", has_open_ticket=True, now=now)
    second = state.evaluate(
        fingerprint="same",
        source="logs",
        severity="warning",
        has_open_ticket=True,
        now=now + timedelta(seconds=60),
    )

    assert first.action == "comment"
    assert second.action == "suppressed"


def test_error_signature_controls_log_fingerprint() -> None:
    base = {
        "name": "human title that may change",
        "service": "checkout",
        "environment": "prod",
        "labels": {"error_signature": "database connection refused <n>"},
    }
    changed_title = {**base, "name": "a better human title"}

    assert compute_fingerprint(base) == compute_fingerprint(changed_title)


def test_discovery_gate_does_not_consume_jira_creation_budget(tmp_path) -> None:
    state = _state(tmp_path, max_new_issues_per_hour=1, min_occurrences={"logs": 2, "prometheus": 1})
    now = datetime(2026, 7, 26, tzinfo=timezone.utc)

    first = state.evaluate_for_discovery(
        fingerprint="same-error", source="logs", severity="warning", now=now
    )
    second = state.evaluate_for_discovery(
        fingerprint="same-error", source="logs", severity="warning", now=now + timedelta(seconds=1)
    )
    jira = state.evaluate(
        fingerprint="qualified-error",
        source="prometheus",
        severity="critical",
        has_open_ticket=False,
        now=now + timedelta(seconds=2),
    )

    assert first.allowed is False
    assert second.allowed is True
    assert second.action == "discover"
    assert jira.allowed is True
    assert jira.action == "create"


def _load_monitoring_app():
    import importlib.util
    from pathlib import Path
    app_path = Path(__file__).resolve().parents[1] / "src" / "monitoring-adapter" / "app.py"
    spec = importlib.util.spec_from_file_location("monitoring_adapter_app_test", app_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_kaiops_managed_jira_webhook_loop_prevention() -> None:
    app = _load_monitoring_app()
    _is_kaiops_managed_jira_update = app._is_kaiops_managed_jira_update
    _jira_payload_to_alert_payload = app._jira_payload_to_alert_payload

    for label in [
        "kaiops-auto-created",
        "kaiops-managed-by-kaiops",
        "managed_by_kaiops",
        "kaiops_incident_11111111-1111-4111-8111-111111111111",
        "kaiops-candidate-22222222-2222-4222-8222-222222222222",
    ]:
        payload = {
            "webhookEvent": "jira:issue_updated",
            "issue": {
                "key": "KAN-100",
                "id": "10100",
                "fields": {
                    "summary": "Service degradation test",
                    "description": "Auto-created incident",
                    "labels": [label, "kaiops-severity-critical"],
                    "status": {"name": "In Progress"},
                    "priority": {"name": "High"},
                    "project": {"key": "KAN"},
                },
            },
        }
        assert _is_kaiops_managed_jira_update(payload) is True, f"Failed for label {label}"

        mapped, key = _jira_payload_to_alert_payload(payload)
        assert key == "KAN-100"
        assert mapped["labels"]["managed_by_kaiops"] == "true"
        assert mapped["labels"]["event_origin"] == "kaiops"


def test_external_jira_webhook_allowed_as_unmanaged() -> None:
    app = _load_monitoring_app()
    _is_kaiops_managed_jira_update = app._is_kaiops_managed_jira_update
    _jira_payload_to_alert_payload = app._jira_payload_to_alert_payload

    payload = {
        "webhookEvent": "jira:issue_created",
        "issue": {
            "key": "KAN-200",
            "id": "10200",
            "fields": {
                "summary": "Customer reported checkout error",
                "description": "Checkout page returning 500",
                "labels": ["bug", "user-reported"],
                "status": {"name": "Open"},
                "priority": {"name": "Highest"},
                "project": {"key": "KAN"},
            },
        },
    }
    assert _is_kaiops_managed_jira_update(payload) is False
    mapped, key = _jira_payload_to_alert_payload(payload)
    assert key == "KAN-200"
    assert mapped["labels"]["managed_by_kaiops"] == "false"
    assert mapped["labels"]["event_origin"] == "jira"


