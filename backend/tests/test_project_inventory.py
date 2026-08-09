from monitoring_adapter.project_inventory import collect_alert_applications


def test_collect_alert_applications_normalizes_sources_and_deduplicates_case() -> None:
    rows = [
        {"labels": {"application": "payments", "namespace": "prod"}, "service": "api"},
        {"project_name": "Payments"},
        {"service": "prometheus"},
        {"labels": {"project": "checkout"}},
    ]
    assert collect_alert_applications(rows) == ["api", "payments", "checkout"]
