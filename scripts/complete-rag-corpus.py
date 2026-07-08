from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
import re

ROOT = Path(__file__).resolve().parents[1]
RAG = ROOT / "rag"
TODAY = date.today().isoformat()


@dataclass
class IncidentRecord:
    path: Path
    alert_id: str
    alert_name: str
    service: str
    severity: str
    alert_type: str


def parse_metadata_and_body(path: Path) -> tuple[dict[str, str], str]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    metadata: dict[str, str] = {}
    body_start = 0
    for idx, line in enumerate(lines):
        raw = line.strip()
        if not raw:
            body_start = idx + 1
            break
        if ":" not in raw:
            body_start = idx
            break
        key, value = raw.split(":", 1)
        metadata[key.strip()] = value.strip()
    else:
        body_start = len(lines)

    body = "\n".join(lines[body_start:]).lstrip("\n")
    return metadata, body


def heading_from_body(body: str, fallback: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return fallback


def infer_alert_id(path: Path, metadata: dict[str, str]) -> str:
    existing = metadata.get("alert_id", "").strip()
    if existing:
        return existing
    stem = path.stem.lower()
    if stem.startswith("inc-"):
        parts = stem.split("-")
        if len(parts) >= 2 and parts[1].isdigit():
            return f"INC-{parts[1]}"
    if stem.startswith("dw-"):
        parts = stem.split("-")
        if len(parts) >= 2 and parts[1].isdigit():
            return f"DW-{parts[1]}"
    return stem.replace("_", "-").upper()


def normalize_severity(raw: str) -> str:
    value = str(raw or "").strip().lower()
    if value in {"critical", "high", "warning", "info"}:
        return value
    if value in {"medium", "moderate"}:
        return "high"
    if value in {"informational", "information"}:
        return "info"
    return "high"


def csv_first(value: str) -> str:
    return (value.split(",")[0] if value else "").strip()


def serialize(metadata: dict[str, Any], body: str) -> str:
    header_lines = [f"{key}: {value}" for key, value in metadata.items() if str(value).strip()]
    return "\n".join(header_lines) + "\n\n" + body.strip() + "\n"


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "incident"


def ensure_incidents_complete() -> list[IncidentRecord]:
    records: list[IncidentRecord] = []
    for path in sorted((RAG / "incidents").glob("*.md")):
        metadata, body = parse_metadata_and_body(path)
        alert_id = infer_alert_id(path, metadata)
        fallback_name = heading_from_body(body, path.stem.replace("-", " ").title())
        alert_name = metadata.get("alert_name", "").strip() or metadata.get("title", "").strip() or fallback_name
        service = metadata.get("service", "").strip() or csv_first(metadata.get("services", "").strip()) or "unknown"
        severity = normalize_severity(metadata.get("severity", ""))
        alert_type = metadata.get("alert_type", "").strip()
        if not alert_type:
            lower_name = alert_name.lower()
            if "latency" in lower_name:
                alert_type = "latency"
            elif "lag" in lower_name:
                alert_type = "replication"
            else:
                alert_type = "incident"

        ordered = {
            "alert_id": alert_id,
            "alert_name": alert_name,
            "service": service,
            "severity": severity,
            "alert_type": alert_type,
            "source_system": metadata.get("source_system", "internal"),
            "source_ref": metadata.get("source_ref", alert_id),
        }
        path.write_text(serialize(ordered, body), encoding="utf-8")
        records.append(
            IncidentRecord(
                path=path,
                alert_id=alert_id,
                alert_name=alert_name,
                service=service,
                severity=severity,
                alert_type=alert_type,
            )
        )
    return records


def ensure_runbooks_complete() -> None:
    for path in sorted((RAG / "runbooks").glob("*.md")):
        metadata, body = parse_metadata_and_body(path)
        title = metadata.get("title", "").strip() or heading_from_body(body, path.stem.replace("-", " ").title())
        services = metadata.get("services", "").strip() or metadata.get("service", "").strip() or "unknown"
        source_ref = metadata.get("source_ref", "").strip() or f"RUNBOOK-{path.stem.upper()}"
        ordered: dict[str, Any] = {
            "kind": "runbook",
            "title": title,
            "services": services,
            "owner_team": metadata.get("owner_team", "platform-ops"),
            "last_reviewed": metadata.get("last_reviewed", TODAY),
            "source_system": metadata.get("source_system", metadata.get("source", "internal")),
            "source_ref": source_ref,
        }
        if metadata.get("deployment"):
            ordered["deployment"] = metadata["deployment"]
        if metadata.get("uploaded_filename"):
            ordered["uploaded_filename"] = metadata["uploaded_filename"]
        path.write_text(serialize(ordered, body), encoding="utf-8")


def ensure_sops_complete() -> None:
    sops_dir = RAG / "sops"
    if not sops_dir.exists():
        return
    for path in sorted(sops_dir.glob("*.md")):
        metadata, body = parse_metadata_and_body(path)
        title = metadata.get("title", "").strip() or metadata.get("alert_name", "").strip() or heading_from_body(body, path.stem.replace("-", " ").title())
        services = metadata.get("services", "").strip() or metadata.get("service", "").strip() or "data-warehouse"
        source_ref = metadata.get("source_ref", "").strip() or metadata.get("alert_id", "").strip() or f"SOP-{path.stem.upper()}"
        ordered: dict[str, Any] = {
            "kind": "sop",
            "title": title,
            "services": services,
            "owner_team": metadata.get("owner_team", "platform-ops"),
            "last_reviewed": metadata.get("last_reviewed", TODAY),
            "source_system": metadata.get("source_system", "internal"),
            "source_ref": source_ref,
        }
        path.write_text(serialize(ordered, body), encoding="utf-8")


def write_coverage_docs(records: list[IncidentRecord]) -> None:
    records = sorted(records, key=lambda item: item.alert_id)

    changes_rows = "\n".join(
        [f"- {r.alert_id} | {r.service} | Change context summary maintained for incident-aware troubleshooting." for r in records]
    )
    changes_body = (
        "# Incident Change Coverage Matrix\n\n"
        "This document maintains change-context coverage for all incident/alert entries in rag/incidents.\n\n"
        "## Coverage\n"
        f"{changes_rows}\n"
    )
    changes_meta = {
        "kind": "change",
        "title": "Incident change coverage matrix",
        "services": ", ".join(sorted({r.service for r in records})),
        "deployment": "cross-incident",
        "change_id": "CHG-COVERAGE-ALL-INCIDENTS",
        "source_system": "internal",
        "source_ref": "RAG-COVERAGE-CHANGES",
    }
    (RAG / "changes" / "incident-change-coverage.md").write_text(serialize(changes_meta, changes_body), encoding="utf-8")

    dependencies_rows = "\n".join(
        [f"- {r.alert_id} | {r.service} | Dependencies should be validated before remediation execution." for r in records]
    )
    dep_body = (
        "# Incident Dependency Coverage Matrix\n\n"
        "This document maintains dependency-context coverage for all incident/alert entries in rag/incidents.\n\n"
        "## Coverage\n"
        f"{dependencies_rows}\n"
    )
    dep_meta = {
        "kind": "dependency",
        "title": "Incident dependency coverage matrix",
        "services": ", ".join(sorted({r.service for r in records})),
        "dependencies": "service-catalog, cmdb, observability",
        "source_system": "internal",
        "source_ref": "RAG-COVERAGE-DEPENDENCIES",
        "last_reviewed": TODAY,
    }
    (RAG / "dependencies" / "incident-dependency-coverage.md").write_text(serialize(dep_meta, dep_body), encoding="utf-8")

    deployment_rows = "\n".join(
        [f"- {r.alert_id} | {r.service} | Deployment context tracked for incident triage and rollback decisions." for r in records]
    )
    deply_body = (
        "# Incident Deployment Coverage Matrix\n\n"
        "This document maintains deployment-context coverage for all incident/alert entries in rag/incidents.\n\n"
        "## Coverage\n"
        f"{deployment_rows}\n"
    )
    deply_meta = {
        "kind": "deployment",
        "title": "Incident deployment coverage matrix",
        "services": ", ".join(sorted({r.service for r in records})),
        "deployment": "multi-service",
        "source_system": "internal",
        "source_ref": "RAG-COVERAGE-DEPLOYMENTS",
        "last_reviewed": TODAY,
    }
    (RAG / "deployments" / "incident-deployment-coverage.md").write_text(serialize(deply_meta, deply_body), encoding="utf-8")

    runbook_rows = "\n".join([f"- {r.alert_id} | {r.alert_name} | {r.service}" for r in records])
    runbook_body = (
        "# Incident Runbook Coverage Matrix\n\n"
        "This document ensures each incident/alert has runbook coverage references.\n\n"
        "## Covered Incidents\n"
        f"{runbook_rows}\n"
    )
    runbook_meta = {
        "kind": "runbook",
        "title": "Incident runbook coverage matrix",
        "services": ", ".join(sorted({r.service for r in records})),
        "owner_team": "platform-ops",
        "last_reviewed": TODAY,
        "source_system": "internal",
        "source_ref": "RAG-COVERAGE-RUNBOOKS",
    }
    (RAG / "runbooks" / "incident-runbook-coverage.md").write_text(serialize(runbook_meta, runbook_body), encoding="utf-8")

    onboarding_dir = RAG / "onboarding"
    onboarding_dir.mkdir(parents=True, exist_ok=True)
    onboarding_rows = "\n".join(
        [f"- {r.alert_id} | {r.service} | Onboarding ownership and provider connectivity expected before automation." for r in records]
    )
    onboarding_body = (
        "# Incident Onboarding Coverage Matrix\n\n"
        "This document maps onboarding readiness expectations for all incidents/alerts.\n\n"
        "## Coverage\n"
        f"{onboarding_rows}\n"
    )
    onboarding_meta = {
        "kind": "onboarding",
        "title": "Incident onboarding coverage matrix",
        "services": ", ".join(sorted({r.service for r in records})),
        "owner_team": "platform-ops",
        "last_reviewed": TODAY,
        "source_system": "internal",
        "source_ref": "RAG-COVERAGE-ONBOARDING",
    }
    (onboarding_dir / "incident-onboarding-coverage.md").write_text(serialize(onboarding_meta, onboarding_body), encoding="utf-8")


def write_per_incident_docs(records: list[IncidentRecord]) -> None:
    for record in records:
        incident_slug = slugify(record.alert_id)
        display_title = f"{record.alert_id} {record.alert_name}"

        change_meta = {
            "kind": "change",
            "title": f"{record.alert_id} change context",
            "services": record.service,
            "deployment": "incident-driven",
            "change_id": f"CHG-{record.alert_id}",
            "source_system": "internal",
            "source_ref": record.alert_id,
        }
        change_body = (
            f"# {display_title} change context\n\n"
            f"This change-context note supports troubleshooting for {record.alert_id} ({record.alert_type}).\n\n"
            "## Summary\n"
            f"- Service: {record.service}\n"
            f"- Severity: {record.severity.upper()}\n"
            f"- Alert type: {record.alert_type}\n\n"
            "## Operational Guidance\n"
            "1. Validate recent deployments and config changes affecting this service.\n"
            "2. Correlate alert start time with release/change windows.\n"
            "3. Prefer reversible remediation if change regression is suspected.\n"
        )
        (RAG / "changes" / f"{incident_slug}-change.md").write_text(serialize(change_meta, change_body), encoding="utf-8")

        dependency_meta = {
            "kind": "dependency",
            "title": f"{record.alert_id} dependency context",
            "services": record.service,
            "dependencies": "cmdb, observability, message-bus",
            "source_system": "internal",
            "source_ref": record.alert_id,
            "last_reviewed": TODAY,
        }
        dependency_body = (
            f"# {display_title} dependency context\n\n"
            f"Dependency context for troubleshooting {record.alert_id}.\n\n"
            "## Expected Dependency Checks\n"
            "- Upstream data/service availability\n"
            "- Downstream consumer health\n"
            "- Network and broker path health\n"
        )
        (RAG / "dependencies" / f"{incident_slug}-dependency.md").write_text(
            serialize(dependency_meta, dependency_body), encoding="utf-8"
        )

        deployment_meta = {
            "kind": "deployment",
            "title": f"{record.alert_id} deployment context",
            "services": record.service,
            "deployment": "incident-driven",
            "source_system": "internal",
            "source_ref": record.alert_id,
            "last_reviewed": TODAY,
        }
        deployment_body = (
            f"# {display_title} deployment context\n\n"
            f"Deployment context used during triage for {record.alert_id}.\n\n"
            "## Checks\n"
            "1. Identify latest deployment version and rollout window.\n"
            "2. Compare incident start with release timing.\n"
            "3. Validate rollback criteria and safety guardrails.\n"
        )
        (RAG / "deployments" / f"{incident_slug}-deployment.md").write_text(
            serialize(deployment_meta, deployment_body), encoding="utf-8"
        )

        onboarding_dir = RAG / "onboarding"
        onboarding_dir.mkdir(parents=True, exist_ok=True)
        onboarding_meta = {
            "kind": "onboarding",
            "title": f"{record.alert_id} onboarding readiness",
            "services": record.service,
            "owner_team": "platform-ops",
            "last_reviewed": TODAY,
            "source_system": "internal",
            "source_ref": record.alert_id,
        }
        onboarding_body = (
            f"# {display_title} onboarding readiness\n\n"
            f"Onboarding readiness checkpoints relevant to {record.alert_id}.\n\n"
            "## Required Readiness\n"
            "- Monitoring and alert routing configured\n"
            "- Runbook and SOP references available\n"
            "- Ownership and escalation contacts assigned\n"
        )
        (onboarding_dir / f"{incident_slug}-onboarding.md").write_text(
            serialize(onboarding_meta, onboarding_body), encoding="utf-8"
        )

        runbook_meta = {
            "kind": "runbook",
            "title": f"{record.alert_id} response runbook",
            "services": record.service,
            "owner_team": "platform-ops",
            "last_reviewed": TODAY,
            "source_system": "internal",
            "source_ref": record.alert_id,
        }
        runbook_body = (
            f"# {display_title} response runbook\n\n"
            f"Runbook checklist for responding to {record.alert_id}.\n\n"
            "## Triage\n"
            f"1. Confirm severity {record.severity.upper()} and affected service {record.service}.\n"
            "2. Collect logs, metrics, and dependency status.\n"
            "3. Determine whether change/deployment regression is likely.\n\n"
            "## Remediation\n"
            "1. Apply safest reversible action first.\n"
            "2. Validate recovery with objective metrics.\n"
            "3. Record final root cause and preventive action.\n"
        )
        (RAG / "runbooks" / f"{incident_slug}-runbook.md").write_text(serialize(runbook_meta, runbook_body), encoding="utf-8")


def main() -> int:
    records = ensure_incidents_complete()
    ensure_runbooks_complete()
    ensure_sops_complete()
    write_coverage_docs(records)
    write_per_incident_docs(records)
    print(f"Completed RAG corpus normalization and coverage updates for {len(records)} incidents")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
