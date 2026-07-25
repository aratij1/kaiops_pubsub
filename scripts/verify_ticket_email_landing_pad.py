from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from monitoring_adapter.landing_pad_sources import load_landing_pad_file


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email-samples", type=Path, required=True)
    parser.add_argument("--jira-csv", type=Path, required=True)
    args = parser.parse_args()

    firing = args.email_samples / "emails" / "01_kaiops-scenario-01_checkout-api_FIRING.eml"
    resolved = args.email_samples / "emails" / "05_kaiops-scenario-05_user-profile_RESOLVED.eml"

    firing_alert, firing_raw = load_landing_pad_file(firing)[0]
    assert firing_alert["name"] == "High error rate"
    assert firing_alert["service"] == "checkout-api"
    assert firing_alert["severity"] == "critical"
    assert firing_alert["labels"]["alert_status"] == "firing"
    assert firing_alert["correlation_id"] == "INC-2025-10001"
    assert firing_raw["attachments"][0]["status"] == "parsed"

    resolved_alert, _ = load_landing_pad_file(resolved)[0]
    assert resolved_alert["name"] == "Pod crash loop"
    assert resolved_alert["labels"]["alert_status"] == "resolved"
    assert resolved_alert["correlation_id"] == "INC-2025-10081"

    jira_rows = load_landing_pad_file(args.jira_csv)
    assert len(jira_rows) == 1000
    assert jira_rows[0][0]["source"] == "jira"
    assert jira_rows[0][0]["labels"]["ticket_id"].startswith("KAI-")

    print(
        {
            "email_firing": firing_alert["name"],
            "email_resolved": resolved_alert["name"],
            "jira_rows": len(jira_rows),
            "status": "ok",
        }
    )


if __name__ == "__main__":
    main()
