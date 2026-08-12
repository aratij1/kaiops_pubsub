from monitoring_adapter.project_inventory import collect_alert_applications


def test_collect_alert_applications_normalizes_sources_and_deduplicates_case() -> None:
    rows = [
        {"labels": {"application": "payments", "namespace": "prod"}, "service": "api"},
        {"project_name": "Payments"},
        {"service": "prometheus"},
        {"labels": {"project": "checkout"}},
    ]
    assert collect_alert_applications(rows) == ["api", "payments", "checkout"]


def test_collect_alert_applications_hides_test_and_smoke_projects() -> None:
    rows = [
        {"application": "UX Test Application 0807194413"},
        {"project": "landing-alert-e2e-20260721181052"},
        {"service": "test4"},
        {"service": "kaiops-platform"},
    ]

    assert collect_alert_applications(rows) == ["kaiops-platform"]
