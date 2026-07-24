#!/usr/bin/env python3
"""Derive email incident tickets (.eml) from the historical Jira ticket CSV.

Some incidents reach KaiOps as emails rather than monitoring alerts. The landing
pad already ingests ``.eml`` files via
``monitoring_adapter.landing_pad_sources.email_to_alert``, which reads the
``X-KaiOps-*`` headers first and falls back to ``Service:`` / ``Severity:`` lines
in the body.

This script converts a bounded subset of Jira rows into RFC-822 ``.eml`` files
written to ``backend/ingested_alerts/input`` so the same incidents can be
exercised through the email channel. The generated emails represent the *same*
incidents as the CSV rows (matching ``Incident Correlation ID``), so email and
CSV ingestion correlate.

Examples
--------
    python scripts/generate_email_tickets.py                 # 25 emails
    python scripts/generate_email_tickets.py --count 100     # first 100 rows
"""

from __future__ import annotations

import argparse
import csv
import re
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = REPO_ROOT / "fault-lab" / "data" / "kaiops_jira_1000_tickets.csv"
DEFAULT_INPUT_DIR = REPO_ROOT / "backend" / "ingested_alerts" / "input"
DEFAULT_SENDER = "monitoring-alerts@kaiops.local"


def _text(value: object, default: str = "") -> str:
    result = str(value or "").strip()
    return result or default


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "ticket"


def build_email(row: dict[str, str], sender: str) -> EmailMessage:
    issue_id = _text(row.get("Issue ID") or row.get("Key"), "jira-ticket")
    summary = _text(row.get("Summary"), issue_id)
    service = _text(row.get("Service") or row.get("Component/s"), "unknown")
    severity = _text(row.get("Severity") or row.get("Priority"), "warning")
    environment = _text(row.get("Environment"), "prod").split()[0].lower()
    description = _text(row.get("Description"), summary)
    correlation_id = _text(row.get("Incident Correlation ID"), issue_id)
    alert_name = _text(row.get("Alert Name"), summary)

    message = EmailMessage()
    message["Subject"] = f"[{severity}] {alert_name} on {service}"
    message["From"] = sender
    message["To"] = "kaiops-landing-pad@kaiops.local"
    message["Message-ID"] = f"<{issue_id}@kaiops.local>"
    message["X-KaiOps-Service"] = service
    message["X-KaiOps-Severity"] = severity
    message["X-KaiOps-Environment"] = environment
    message["X-Correlation-ID"] = correlation_id

    body = (
        f"Service: {service}\n"
        f"Severity: {severity}\n"
        f"Environment: {environment}\n"
        f"Alert: {alert_name}\n"
        f"Ticket: {issue_id}\n"
        f"Correlation ID: {correlation_id}\n\n"
        f"{description}\n"
    )
    message.set_content(body)
    return message


def generate(source: Path, input_dir: Path, count: int, sender: str) -> list[Path]:
    if not source.is_file():
        raise SystemExit(f"source CSV not found: {source}")
    input_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")

    written: list[Path] = []
    with source.open(encoding="utf-8-sig", newline="") as stream:
        for index, row in enumerate(csv.DictReader(stream)):
            if index >= count:
                break
            issue_id = _text(row.get("Issue ID") or row.get("Key"), f"ticket-{index}")
            message = build_email(row, sender)
            target = input_dir / f"email-{stamp}-{_slug(issue_id)}.eml"
            target.write_bytes(message.as_bytes())
            written.append(target)

    print(f"Generated {len(written)} email ticket(s) in {input_dir}")
    print("The monitoring-adapter watcher will ingest each .eml as a source=email alert.")
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="Jira ticket CSV to derive emails from")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR, help="landing-pad input directory")
    parser.add_argument("--count", type=int, default=25, help="number of emails to generate (default: 25)")
    parser.add_argument("--sender", default=DEFAULT_SENDER, help="From address for the generated emails")
    args = parser.parse_args()
    generate(args.source, args.input_dir, max(1, args.count), args.sender)


if __name__ == "__main__":
    main()
