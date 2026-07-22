from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EXECUTION_DIR = ROOT / "backend" / "rag" / "execution"


def read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def main() -> int:
    actions = read_json(EXECUTION_DIR / "action_catalog.json")
    connectors = read_json(EXECUTION_DIR / "connectors.json")
    playbooks = read_json(EXECUTION_DIR / "playbooks.json")

    command_catalog = actions.get("commands")
    connector_catalog = connectors.get("connectors")
    playbook_rows = playbooks.get("playbooks")
    if not isinstance(command_catalog, dict):
        raise ValueError("action_catalog.json commands must be an object")
    if not isinstance(connector_catalog, dict):
        raise ValueError("connectors.json connectors must be an object")
    if not isinstance(playbook_rows, list):
        raise ValueError("playbooks.json playbooks must be a list")

    errors: list[str] = []
    mutating_safety = {"write", "restart", "scale", "rollback", "archive", "failover"}
    all_connector_ops = {
        str(operation)
        for connector in connector_catalog.values()
        if isinstance(connector, dict)
        for operation in connector.get("allowed_operations", [])
    }

    for command_id, command in command_catalog.items():
        if not isinstance(command, dict):
            errors.append(f"command {command_id} must be an object")
            continue
        operation = str(command.get("operation") or "").strip()
        safety = str(command.get("safety") or "").strip().lower()
        if not operation:
            errors.append(f"command {command_id} missing operation")
        if not str(command.get("command") or "").strip():
            errors.append(f"command {command_id} missing command")
        if operation and operation not in all_connector_ops:
            errors.append(f"command {command_id} operation {operation} is not allowed by any connector")
        if safety in mutating_safety:
            if command.get("approval_required") is not True:
                errors.append(f"mutating command {command_id} must set approval_required=true")
            if not str(command.get("rollback") or "").strip():
                errors.append(f"mutating command {command_id} must define rollback")

    for playbook in playbook_rows:
        if not isinstance(playbook, dict):
            errors.append("playbook entry must be an object")
            continue
        playbook_id = str(playbook.get("id") or "<missing-id>")
        steps = playbook.get("steps")
        if not isinstance(steps, list) or not steps:
            errors.append(f"playbook {playbook_id} must define steps")
            continue
        step_types = {str(step.get("type") or "").strip().lower() for step in steps if isinstance(step, dict)}
        if playbook_id != "generic-kaiops-triage-playbook" and "diagnostic" not in step_types:
            errors.append(f"playbook {playbook_id} missing diagnostic step")
        if "validation" not in step_types:
            errors.append(f"playbook {playbook_id} missing validation step")
        match = playbook.get("match") if isinstance(playbook.get("match"), dict) else {}
        matched_services = [str(item).strip().lower() for item in match.get("services", []) if str(item).strip()]
        playbook_operations: set[str] = set()
        for step in steps:
            if not isinstance(step, dict):
                errors.append(f"playbook {playbook_id} has non-object step")
                continue
            for command_id in step.get("commands", []):
                command = command_catalog.get(str(command_id))
                if not isinstance(command, dict):
                    errors.append(f"playbook {playbook_id} references unknown command {command_id}")
                    continue
                operation = str(command.get("operation") or "").strip()
                if operation:
                    playbook_operations.add(operation)
        for service in matched_services:
            connector = connector_catalog.get(service) or connector_catalog.get(connectors.get("default_connector"))
            if not isinstance(connector, dict):
                errors.append(f"playbook {playbook_id} service {service} has no connector or default connector")
                continue
            allowed_ops = {str(item).strip() for item in connector.get("allowed_operations", []) if str(item).strip()}
            missing_ops = sorted(operation for operation in playbook_operations if operation not in allowed_ops)
            if missing_ops:
                errors.append(
                    f"playbook {playbook_id} service {service} connector {connector.get('connector_id')} "
                    f"does not allow operations: {', '.join(missing_ops)}"
                )

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    print(
        "Execution catalog OK: "
        f"{len(command_catalog)} actions, {len(connector_catalog)} connectors, {len(playbook_rows)} playbooks"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
