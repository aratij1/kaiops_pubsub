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
