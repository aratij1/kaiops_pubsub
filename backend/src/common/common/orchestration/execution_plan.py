from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from common.config import Settings
from common.connection_config import connector_catalog_from_connection_config, load_connection_config
from common.models import Alert


def _repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "pyproject.toml").exists() and (parent / "backend").exists():
            return parent
    return current.parents[5]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _merge_connector_catalogs(legacy: dict[str, Any], central: dict[str, Any]) -> dict[str, Any]:
    legacy_connectors = legacy.get("connectors", {}) if isinstance(legacy.get("connectors"), dict) else {}
    central_connectors = central.get("connectors", {}) if isinstance(central.get("connectors"), dict) else {}
    connectors = {
        **{
            str(key).strip().lower(): value
            for key, value in legacy_connectors.items()
            if str(key).strip() and isinstance(value, dict)
        },
        **{
            str(key).strip().lower(): value
            for key, value in central_connectors.items()
            if str(key).strip() and isinstance(value, dict)
        },
    }
    default_connector = str(
        central.get("default_connector") or legacy.get("default_connector") or "generic-api"
    ).strip()
    return {
        "version": str(central.get("version") or legacy.get("version") or "connectors-v1"),
        "default_connector": default_connector,
        "connectors": connectors,
    }


def _execution_catalogs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    root = _repo_root() / "backend" / "rag"
    legacy_connectors = _read_json(root / "execution" / "connectors.json")
    connection_config = load_connection_config(Settings())
    central_connectors = connector_catalog_from_connection_config(connection_config)
    connectors = _merge_connector_catalogs(legacy_connectors, central_connectors)
    actions = _read_json(root / "execution" / "action_catalog.json")
    playbooks = _read_json(root / "execution" / "playbooks.json")
    connectivity = _read_json(root / "onboarding" / "connectivity.json")
    return connectors, actions, playbooks, connectivity, connection_config


def _match_playbook(*, alert: Alert, playbooks: dict[str, Any]) -> dict[str, Any]:
    candidates = playbooks.get("playbooks", []) if isinstance(playbooks.get("playbooks"), list) else []
    service = str(alert.service or "").strip().lower()
    alert_id = str(getattr(alert, "id", "") or getattr(alert, "alert_id", "") or getattr(alert, "source_ref", "")).strip().lower()
    alert_type = str(getattr(alert, "type", "") or getattr(alert, "alert_type", "") or "").strip().lower()
    text = " ".join(
        [
            str(alert.name or "").strip().lower(),
            str(alert.description or "").strip().lower(),
            str(alert.source or "").strip().lower(),
        ]
    )

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        match = candidate.get("match", {}) if isinstance(candidate.get("match"), dict) else {}
        alert_ids = [str(item).strip().lower() for item in match.get("alert_ids", []) if str(item).strip()]
        services = [str(item).strip().lower() for item in match.get("services", []) if str(item).strip()]
        alert_types = [str(item).strip().lower() for item in match.get("alert_types", []) if str(item).strip()]
        keywords = [str(item).strip().lower() for item in match.get("alert_keywords", []) if str(item).strip()]
        alert_id_match = not alert_ids or alert_id in alert_ids
        service_match = not services or service in services
        alert_type_match = not alert_types or alert_type in alert_types
        keyword_match = not keywords or any(keyword in text for keyword in keywords)
        if alert_id_match and service_match and alert_type_match and keyword_match:
            return candidate

    return {
        "id": "generic-triage-playbook",
        "name": "Generic triage playbook",
        "preflight_checks": ["Connector health check passes", "Incident context available"],
        "steps": [
            {
                "name": "Collect baseline diagnostics",
                "type": "diagnostic",
                "commands": [],
            },
            {
                "name": "Prepare manual remediation path",
                "type": "remediation",
                "approval_gate": True,
                "commands": [],
            },
        ],
    }


def _connector_for_service(*, service: str, connectors: dict[str, Any]) -> dict[str, Any]:
    service_key = str(service or "").strip().lower()
    available = connectors.get("connectors", {}) if isinstance(connectors.get("connectors"), dict) else {}
    default_key = str(connectors.get("default_connector") or "generic-api").strip()

    if service_key in available and isinstance(available[service_key], dict):
        return available[service_key]
    if default_key in available and isinstance(available[default_key], dict):
        return available[default_key]

    return {
        "connector_id": "generic-api",
        "system": service_key or "generic",
        "type": "api",
        "endpoint": "https://api.internal",
        "auth_method": "service-account-token",
        "secret_ref": "vault://kaiops/prod/default-token",
        "allowed_operations": ["read_status"],
    }


def resolve_execution_plan(
    *,
    alert: Alert,
    workflow_name: str,
    requires_approval: bool,
    risk_tier: str,
    execution_mode: str,
) -> dict[str, Any]:
    connectors, actions, playbooks, connectivity, connection_config = _execution_catalogs()
    playbook = _match_playbook(alert=alert, playbooks=playbooks)
    connector = _connector_for_service(service=str(alert.service or ""), connectors=connectors)

    command_catalog = actions.get("commands", {}) if isinstance(actions.get("commands"), dict) else {}

    resolved_steps: list[dict[str, Any]] = []
    for index, step in enumerate(playbook.get("steps", []) if isinstance(playbook.get("steps"), list) else [], start=1):
        if not isinstance(step, dict):
            continue
        command_ids = [str(item).strip() for item in step.get("commands", []) if str(item).strip()]
        commands: list[dict[str, Any]] = []
        for command_id in command_ids:
            command = command_catalog.get(command_id)
            if not isinstance(command, dict):
                continue
            operation = str(command.get("operation") or "").strip()
            allowed_ops = connector.get("allowed_operations", []) if isinstance(connector.get("allowed_operations"), list) else []
            commands.append(
                {
                    "id": command_id,
                    "operation": operation,
                    "allowed": operation in allowed_ops if operation else False,
                    "command": str(command.get("command") or "").strip(),
                    "rollback": str(command.get("rollback") or "").strip(),
                    "safety": str(command.get("safety") or "unknown").strip(),
                }
            )

        resolved_steps.append(
            {
                "order": index,
                "name": str(step.get("name") or f"Step {index}"),
                "type": str(step.get("type") or "task"),
                "approval_gate": bool(step.get("approval_gate", False)),
                "commands": commands,
            }
        )

    project = connectivity.get("project", {}) if isinstance(connectivity.get("project"), dict) else {}
    return {
        "version": "execution-plan-v1",
        "workflow": workflow_name,
        "alert": {
            "service": str(alert.service or "").strip(),
            "name": str(alert.name or "").strip(),
            "source": str(alert.source or "").strip(),
            "id": str(getattr(alert, "id", "") or getattr(alert, "alert_id", "") or getattr(alert, "source_ref", "")).strip(),
            "type": str(getattr(alert, "type", "") or getattr(alert, "alert_type", "") or "").strip(),
        },
        "risk_tier": str(risk_tier or "unknown").lower(),
        "execution_mode": str(execution_mode or "unknown").lower(),
        "approval_required": bool(requires_approval),
        "connection": {
            "architecture": connection_config.get("connection_architecture", {})
            if isinstance(connection_config.get("connection_architecture"), dict)
            else {},
            "platform": connection_config.get("platform", {}) if isinstance(connection_config.get("platform"), dict) else {},
            "project": {
                "name": str(project.get("name") or "unknown"),
                "environment": str(project.get("environment") or "unknown"),
                "region": str(project.get("region") or "unknown"),
                "owner_team": str(project.get("owner_team") or "unknown"),
            },
            "connector": connector,
            "connectivity_checks": {
                "prometheus_url": str(connectivity.get("prometheus_url") or ""),
                "new_relic_url": str(connectivity.get("new_relic_url") or ""),
                "datadog_url": str(connectivity.get("datadog_url") or ""),
            },
        },
        "playbook": {
            "id": str(playbook.get("id") or "generic-triage-playbook"),
            "name": str(playbook.get("name") or "Generic triage playbook"),
            "match": playbook.get("match", {}) if isinstance(playbook.get("match"), dict) else {},
            "preflight_checks": [
                str(item) for item in playbook.get("preflight_checks", []) if str(item).strip()
            ],
            "steps": resolved_steps,
        },
    }
