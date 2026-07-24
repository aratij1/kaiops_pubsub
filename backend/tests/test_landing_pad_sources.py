from pathlib import Path

from monitoring_adapter.landing_pad_sources import load_landing_pad_file


def test_jira_csv_normalizes_ticket_metadata(tmp_path: Path) -> None:
    path = tmp_path / "jira.csv"
    path.write_text(
        '"Issue ID","Summary","Priority","Service","Alert Name","Incident Correlation ID","Root Cause"\n'
        '"KAI-1","Checkout errors","Highest","checkout-api","High error rate","INC-1","bad release"\n',
        encoding="utf-8",
    )
    alert, raw = load_landing_pad_file(path)[0]
    assert alert["source"] == "jira"
    assert alert["name"] == "High error rate"
    assert alert["labels"]["ticket_id"] == "KAI-1"
    assert alert["application"] == "checkout-api"
    assert alert["project"] == "checkout-api"
    assert alert["labels"]["application"] == "checkout-api"
    assert alert["correlation_id"] == "INC-1"
    assert alert["annotations"]["root_cause"] == "bad release"
    assert alert["resolution"]["root_cause"] == "bad release"
    assert "recommended_action" in alert["resolution"]
    assert "target" in alert["remediation"]
    assert raw["Issue ID"] == "KAI-1"


def test_supplied_email_uses_headers_attachment_and_thread_correlation() -> None:
    source = (
        Path(r"C:\Users\ashish.singh\Downloads\New folder\kaiops-alert-email-samples")
        / "emails"
        / "01_kaiops-scenario-01_checkout-api_FIRING.eml"
    )
    if not source.exists():
        return
    alert, raw = load_landing_pad_file(source)[0]
    assert alert["source"] == "email"
    assert alert["name"] == "High error rate"
    assert alert["service"] == "checkout-api"
    assert alert["environment"] == "prod"
    assert alert["severity"] == "critical"
    assert alert["labels"]["alert_status"] == "firing"
    assert alert["labels"]["scenario_id"] == "kaiops-scenario-01"
    assert alert["labels"]["ticket_id"] == "KAI-0001"
    assert alert["correlation_id"] == "INC-2025-10001"
    assert alert["application"]
    assert alert["labels"]["project"]
    assert "kaiops_context" in alert["annotations"]
    assert "kaiops_resolution" in alert["annotations"]
    assert "kaiops_remediation" in alert["annotations"]
    assert raw["attachments"][0]["status"] == "parsed"
    assert raw["original_sha256"]


def test_supplied_resolved_email_is_correlated_not_marked_firing() -> None:
    source = (
        Path(r"C:\Users\ashish.singh\Downloads\New folder\kaiops-alert-email-samples")
        / "emails"
        / "05_kaiops-scenario-05_user-profile_RESOLVED.eml"
    )
    if not source.exists():
        return
    alert, _ = load_landing_pad_file(source)[0]
    assert alert["name"] == "Pod crash loop"
    assert alert["labels"]["alert_status"] == "resolved"
    assert alert["labels"]["in_reply_to"]
    assert alert["correlation_id"] == "INC-2025-10081"
