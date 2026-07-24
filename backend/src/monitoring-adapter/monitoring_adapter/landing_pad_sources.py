from __future__ import annotations

import csv
import hashlib
import json
import re
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Any

from monitoring_adapter.landing_pad_normalizer import normalize_landing_pad_alert


SUPPORTED_SUFFIXES = {".json", ".csv", ".eml"}


def _text(value: Any, default: str = "") -> str:
    result = str(value or "").strip()
    return result or default


def _severity(value: Any) -> str:
    normalized = _text(value, "warning").lower()
    return {
        "blocker": "critical",
        "highest": "critical",
        "critical": "critical",
        "high": "error",
        "major": "error",
        "error": "error",
        "medium": "warning",
        "moderate": "warning",
        "warning": "warning",
        "low": "info",
        "minor": "info",
        "info": "info",
    }.get(normalized, "warning")


def _environment(value: Any) -> str:
    normalized = _text(value, "prod").lower()
    return {"production": "prod", "prd": "prod", "development": "dev", "stage": "staging"}.get(normalized, normalized)


def _safe_labels(values: dict[str, Any]) -> dict[str, str]:
    return {str(key): _text(value) for key, value in values.items() if _text(value)}


def jira_row_to_alert(row: dict[str, Any]) -> dict[str, Any]:
    issue_id = _text(row.get("Issue ID") or row.get("Key"), "jira-ticket")
    summary = _text(row.get("Summary"), issue_id)
    service = _text(row.get("Service") or row.get("Component/s"), "unknown")
    description = _text(row.get("Description"), summary)
    correlation_id = _text(row.get("Incident Correlation ID"), issue_id)
    fingerprint = hashlib.sha256(f"jira:{issue_id}".encode()).hexdigest()[:24]
    annotations = {
        "summary": summary,
        "description": description,
        "metric_evidence": _text(row.get("Metric / Evidence")),
        "threshold": _text(row.get("Threshold")),
        "root_cause": _text(row.get("Root Cause")),
        "root_cause_category": _text(row.get("Root Cause Category")),
        "business_impact": _text(row.get("Business Impact")),
        "resolution_steps": _text(row.get("Resolution Steps")),
        "validation_criteria": _text(row.get("Validation / Closure Criteria")),
        "preventive_action": _text(row.get("Preventive Action")),
        "environment_detail": _text(row.get("Environment")),
    }
    return {
        "source": "jira",
        "name": _text(row.get("Alert Name"), summary),
        "service": service,
        "environment": _text(row.get("Environment"), "prod").split()[0].lower(),
        "severity": _severity(row.get("Severity") or row.get("Priority")),
        "description": description,
        "labels": _safe_labels(
            {
                "alertname": _text(row.get("Alert Name"), summary),
                "alert_status": "firing",
                "alert_fingerprint": fingerprint,
                "ticket_id": issue_id,
                "ticket_type": _text(row.get("Issue Type")),
                "ticket_status": _text(row.get("Status")),
                "project": _text(row.get("Project Key")),
                "component": _text(row.get("Component/s")),
                "runbook_id": _text(row.get("Runbook ID")),
                "incident_correlation_id": correlation_id,
                "external_reference": _text(row.get("External Reference")),
                "source_channel": "jira-csv",
            }
        ),
        "annotations": _safe_labels(annotations),
        "correlation_id": correlation_id,
        "raw_ticket": row,
    }


def email_to_alert(
    *,
    subject: str,
    sender: str,
    body: str,
    message_id: str = "",
    headers: dict[str, Any] | None = None,
    attachment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    header_values = {str(key).lower(): value for key, value in (headers or {}).items()}
    structured = attachment if isinstance(attachment, dict) else {}
    service_match = re.search(r"(?:service|application)\s*[:=]\s*([a-zA-Z0-9_.-]+)", body, re.IGNORECASE)
    severity_match = re.search(r"(?:severity|priority)\s*[:=]\s*([a-zA-Z]+)", body, re.IGNORECASE)
    service = _text(structured.get("service") or header_values.get("x-kaiops-service")) or (service_match.group(1) if service_match else "unknown")
    severity = _text(structured.get("severity") or header_values.get("x-kaiops-severity")) or (severity_match.group(1) if severity_match else "warning")
    identity = message_id or f"{sender}:{subject}:{body[:500]}"
    fingerprint = hashlib.sha256(identity.encode(errors="replace")).hexdigest()[:24]
    correlation_id = _text(
        structured.get("incident_correlation_id")
        or header_values.get("x-kaiops-correlation-id")
        or header_values.get("x-correlation-id"),
        message_id or fingerprint,
    )
    status = _text(structured.get("status") or header_values.get("x-kaiops-alert-status"), "firing").lower()
    alert_name = _text(structured.get("alert_name"))
    if not alert_name:
        match = re.search(r"(?:^|\n)Alert\s*:\s*([^\r\n]+)", body, re.IGNORECASE)
        alert_name = _text(match.group(1) if match else subject, "Email incident")
    return {
        "source": "email",
        "name": alert_name,
        "service": service,
        "environment": _environment(structured.get("environment") or header_values.get("x-kaiops-environment")),
        "severity": _severity(severity),
        "description": body or subject,
        "labels": _safe_labels(
            {
                "alertname": alert_name,
                "alert_status": status,
                "alert_fingerprint": fingerprint,
                "sender": sender,
                "message_id": message_id,
                "in_reply_to": header_values.get("in-reply-to"),
                "incident_correlation_id": correlation_id,
                "scenario_id": structured.get("scenario_id") or header_values.get("x-kaiops-scenario-id"),
                "application_id": structured.get("application_id") or header_values.get("x-kaiops-application-id"),
                "component": structured.get("component"),
                "ticket_id": structured.get("ticket_example"),
                "runbook_id": structured.get("runbook_id"),
                "source_channel": "email",
            }
        ),
        "annotations": _safe_labels(
            {
                "summary": subject,
                "description": body,
                "threshold": structured.get("threshold"),
                "metric_evidence": structured.get("evidence"),
                "root_cause_hint": structured.get("root_cause_hint"),
            }
        ),
        "correlation_id": correlation_id,
    }


def _email_body(message: Any) -> str:
    body = message.get_body(preferencelist=("plain",))
    if body is not None:
        return _text(body.get_content())
    if not message.is_multipart():
        return _text(message.get_content())
    return ""


def _json_attachments(message: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    payloads: list[dict[str, Any]] = []
    provenance: list[dict[str, Any]] = []
    for part in message.walk():
        filename = _text(part.get_filename())
        content_type = _text(part.get_content_type()).lower()
        if content_type != "application/json" and not filename.lower().endswith(".json"):
            continue
        raw = part.get_payload(decode=True) or b""
        if len(raw) > 1_000_000:
            provenance.append({"filename": filename, "content_type": content_type, "size": len(raw), "status": "rejected_too_large"})
            continue
        digest = hashlib.sha256(raw).hexdigest()
        try:
            value = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            provenance.append({"filename": filename, "content_type": content_type, "size": len(raw), "sha256": digest, "status": "invalid_json"})
            continue
        if isinstance(value, dict):
            payloads.append(value)
            provenance.append({"filename": filename, "content_type": content_type, "size": len(raw), "sha256": digest, "status": "parsed"})
    return payloads, provenance


def load_landing_pad_file(path: Path) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        return [(normalize_landing_pad_alert(jira_row_to_alert(row), row), row) for row in rows]
    if suffix == ".eml":
        original = path.read_bytes()
        message = BytesParser(policy=policy.default).parsebytes(original)
        headers = {key: _text(value) for key, value in message.items()}
        attachments, attachment_provenance = _json_attachments(message)
        body = _email_body(message)
        mapped = email_to_alert(
            subject=_text(message.get("Subject"), "Email incident"),
            sender=_text(message.get("From")),
            body=body,
            message_id=_text(message.get("Message-ID")),
            headers=headers,
            attachment=attachments[0] if attachments else None,
        )
        raw_payload = {
            "headers": headers,
            "body": body,
            "attachments": attachment_provenance,
            "original_sha256": hashlib.sha256(original).hexdigest(),
            "original_size": len(original),
        }
        return [(normalize_landing_pad_alert(mapped, raw_payload), raw_payload)]
    if suffix != ".json":
        raise ValueError(f"unsupported landing-pad file type: {suffix}")

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("landing pad input must be a JSON object")
    if _text(payload.get("source")).lower() == "email" or {"subject", "from"} <= {str(key).lower() for key in payload}:
        lowered = {str(key).lower(): value for key, value in payload.items()}
        mapped = email_to_alert(
            subject=_text(lowered.get("subject"), "Email incident"),
            sender=_text(lowered.get("from") or lowered.get("sender")),
            body=_text(lowered.get("body") or lowered.get("description")),
            message_id=_text(lowered.get("message_id") or lowered.get("message-id")),
            headers=lowered.get("headers") if isinstance(lowered.get("headers"), dict) else lowered,
        )
        return [(normalize_landing_pad_alert(mapped, payload), payload)]
    return [(normalize_landing_pad_alert(payload, payload), payload)]
