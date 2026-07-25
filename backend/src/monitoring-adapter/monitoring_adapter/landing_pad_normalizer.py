from __future__ import annotations

import json
import re
from typing import Any


_NOISE_TOKENS = {
    "",
    "unknown",
    "unknown-app",
    "n/a",
    "na",
    "none",
    "null",
    "nil",
    "default",
    "prod",
    "staging",
    "dev",
    "production",
}


def _text(value: Any, default: str = "") -> str:
    token = str(value or "").strip()
    return token or default


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_labels(values: dict[str, Any]) -> dict[str, str]:
    return {str(key): _text(value) for key, value in values.items() if _text(value)}


def _normalized_key_values(values: dict[str, Any]) -> dict[str, Any]:
    return {str(key).strip().lower(): value for key, value in values.items()}


def _first_non_empty(values: list[Any]) -> str:
    for value in values:
        text = _text(value)
        if text:
            return text
    return ""


def _clean_application_token(value: str) -> str:
    token = _text(value).strip("[](){}\"")
    if not token:
        return ""
    lowered = token.lower()
    if lowered in _NOISE_TOKENS:
        return ""
    if re.fullmatch(r"[a-zA-Z0-9._:/\\-]+", token):
        return token
    compact = re.sub(r"\s+", "-", token)
    compact = re.sub(r"[^a-zA-Z0-9._:/\\-]", "", compact)
    return compact


def _infer_application(alert: dict[str, Any], raw: dict[str, Any]) -> str:
    labels = _dict(alert.get("labels"))
    annotations = _dict(alert.get("annotations"))
    raw_lowered = _normalized_key_values(raw)
    labels_lowered = _normalized_key_values(labels)
    annotations_lowered = _normalized_key_values(annotations)

    candidates = [
        alert.get("application"),
        alert.get("project"),
        alert.get("app"),
        labels.get("application"),
        labels.get("project"),
        labels.get("project_name"),
        labels.get("application_id"),
        labels.get("app"),
        labels.get("app_kubernetes_io_name"),
        labels.get("k8s_app"),
        labels.get("kubernetes_io_metadata_name"),
        labels.get("namespace"),
        annotations.get("application"),
        annotations.get("project"),
        annotations.get("project_name"),
        raw.get("Application"),
        raw.get("Project"),
        raw.get("Project Key"),
        raw.get("Project Name"),
        raw.get("application"),
        raw.get("project"),
        raw_lowered.get("application"),
        raw_lowered.get("project"),
        raw_lowered.get("project key"),
        raw_lowered.get("project_name"),
        raw_lowered.get("application_id"),
        labels_lowered.get("application"),
        labels_lowered.get("project"),
        labels_lowered.get("project_name"),
        labels_lowered.get("app"),
        labels_lowered.get("namespace"),
        annotations_lowered.get("application"),
        annotations_lowered.get("project"),
    ]

    for candidate in candidates:
        cleaned = _clean_application_token(_text(candidate))
        if cleaned:
            return cleaned

    service = _clean_application_token(_text(alert.get("service")))
    return service or "unknown-app"


def _build_context(alert: dict[str, Any], raw: dict[str, Any], *, application: str, project: str) -> dict[str, Any]:
    labels = _dict(alert.get("labels"))
    annotations = _dict(alert.get("annotations"))
    return {
        "source": _text(alert.get("source"), "unknown"),
        "application": application,
        "project": project,
        "service": _text(alert.get("service"), "unknown"),
        "environment": _text(alert.get("environment"), "prod"),
        "summary": _first_non_empty(
            [
                annotations.get("summary"),
                alert.get("name"),
                raw.get("Summary"),
                raw.get("summary"),
            ]
        ),
        "description": _first_non_empty(
            [
                alert.get("description"),
                annotations.get("description"),
                raw.get("Description"),
                raw.get("description"),
            ]
        ),
        "evidence": _first_non_empty(
            [
                annotations.get("metric_evidence"),
                annotations.get("threshold"),
                raw.get("Metric / Evidence"),
                raw.get("Threshold"),
            ]
        ),
        "correlation_id": _first_non_empty(
            [
                alert.get("correlation_id"),
                labels.get("incident_correlation_id"),
                raw.get("Incident Correlation ID"),
            ]
        ),
    }


def _build_resolution(alert: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    annotations = _dict(alert.get("annotations"))
    root_cause = _first_non_empty(
        [
            annotations.get("root_cause"),
            annotations.get("root_cause_hint"),
            raw.get("Root Cause"),
        ]
    )
    impact = _first_non_empty(
        [
            annotations.get("business_impact"),
            annotations.get("impact"),
            raw.get("Business Impact"),
        ]
    )
    recommended_action = _first_non_empty(
        [
            annotations.get("resolution_steps"),
            annotations.get("recommended_action"),
            raw.get("Resolution Steps"),
            "Execute runbook steps and validate service recovery.",
        ]
    )
    return {
        "root_cause": root_cause,
        "impact": impact,
        "recommended_action": recommended_action,
    }


def _build_remediation(alert: dict[str, Any], raw: dict[str, Any], *, application: str) -> dict[str, Any]:
    labels = _dict(alert.get("labels"))
    annotations = _dict(alert.get("annotations"))
    runbook_id = _first_non_empty([labels.get("runbook_id"), raw.get("Runbook ID")])
    steps = _first_non_empty([annotations.get("resolution_steps"), raw.get("Resolution Steps")])
    preventive_action = _first_non_empty([annotations.get("preventive_action"), raw.get("Preventive Action")])
    validation = _first_non_empty([annotations.get("validation_criteria"), raw.get("Validation / Closure Criteria")])
    target = _first_non_empty([alert.get("service"), application, "unknown"])
    return {
        "runbook_id": runbook_id,
        "target": target,
        "steps": steps,
        "preventive_action": preventive_action,
        "validation": validation,
    }


def normalize_landing_pad_alert(mapped_alert: dict[str, Any], raw_alert: dict[str, Any] | None = None) -> dict[str, Any]:
    alert = dict(mapped_alert or {})
    raw = raw_alert if isinstance(raw_alert, dict) else {}

    labels = _safe_labels(_dict(alert.get("labels")))
    annotations = _safe_labels(_dict(alert.get("annotations")))

    alert["source"] = _text(alert.get("source"), "unknown")
    alert["name"] = _text(alert.get("name"), "provider-alert")
    alert["service"] = _text(alert.get("service"), "unknown")
    alert["environment"] = _text(alert.get("environment"), "prod").lower()
    alert["severity"] = _text(alert.get("severity"), "warning").lower()
    alert["description"] = _text(alert.get("description") or annotations.get("description"), alert["name"])

    application = _infer_application(alert, raw)
    project = _clean_application_token(_first_non_empty([alert.get("project"), labels.get("project"), labels.get("project_name"), application])) or application

    labels.setdefault("application", application)
    labels.setdefault("project", project)
    labels.setdefault("project_name", project)
    labels.setdefault("service", alert["service"])
    labels.setdefault("environment", alert["environment"])
    labels.setdefault("alertname", _text(labels.get("alertname"), alert["name"]))
    labels.setdefault("alert_status", _text(labels.get("alert_status"), "firing").lower())

    context = _build_context(alert, raw, application=application, project=project)
    resolution = _build_resolution(alert, raw)
    remediation = _build_remediation(alert, raw, application=application)

    annotations.setdefault("summary", _text(annotations.get("summary"), alert["name"]))
    annotations.setdefault("description", _text(annotations.get("description"), alert["description"]))
    annotations.setdefault("root_cause", _text(annotations.get("root_cause"), resolution["root_cause"]))
    annotations.setdefault("business_impact", _text(annotations.get("business_impact"), resolution["impact"]))
    annotations.setdefault("resolution_steps", _text(annotations.get("resolution_steps"), resolution["recommended_action"]))
    annotations.setdefault("preventive_action", _text(annotations.get("preventive_action"), remediation["preventive_action"]))
    annotations.setdefault("validation_criteria", _text(annotations.get("validation_criteria"), remediation["validation"]))
    annotations.setdefault("kaiops_context", json.dumps(context, sort_keys=True))
    annotations.setdefault("kaiops_resolution", json.dumps(resolution, sort_keys=True))
    annotations.setdefault("kaiops_remediation", json.dumps(remediation, sort_keys=True))

    alert["application"] = application
    alert["project"] = project
    alert["labels"] = labels
    alert["annotations"] = annotations
    alert["context"] = context
    alert["resolution"] = resolution
    alert["remediation"] = remediation
    return alert