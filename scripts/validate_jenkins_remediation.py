"""Static safety validation for the governed Jenkins self-healing contract."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "deploy" / "jenkins" / "application-resolution-catalog.json"
JENKINSFILE = ROOT / "deploy" / "jenkins" / "Jenkinsfile.auto-remediation"

SAFE_PREFIXES = (
    "kubectl get ", "kubectl describe ", "kubectl logs ", "kubectl rollout ", "kubectl scale ",
    "ansible-playbook playbooks/", "redis-cli ", "terraform init", "terraform apply ", "mysql -e ", "curl --fail ",
)


def validate(catalog: dict[str, Any], jenkinsfile: str) -> list[str]:
    errors: list[str] = []
    if catalog.get("version") != 2 or catalog.get("contract") != "kaiops.remediation.v2":
        errors.append("catalog must use kaiops.remediation.v2")
    policy = catalog.get("policy") if isinstance(catalog.get("policy"), dict) else {}
    if policy.get("automatic_rollback") is not True or policy.get("dry_run_default") is not True:
        errors.append("policy must require automatic rollback and default dry-run")
    for resolution_id, item in (catalog.get("resolutions") or {}).items():
        if not isinstance(item, dict) or item.get("enabled") is False:
            continue
        mutating = resolution_id != "investigate-first"
        for field in ("preflight", "commands", "validation_commands", "rollback_commands"):
            value = item.get(field)
            if not isinstance(value, list):
                errors.append(f"{resolution_id} missing list {field}")
                continue
            if mutating and not value:
                errors.append(f"{resolution_id} requires executable {field}")
            for command in value:
                if not isinstance(command, str) or "\n" in command or not command.startswith(SAFE_PREFIXES):
                    errors.append(f"{resolution_id} has unsafe {field} command: {command!r}")
        if mutating and item.get("approval_required") is not True:
            errors.append(f"{resolution_id} must require approval")
    required_tokens = {
        "concurrency guard": "disableConcurrentBuilds()",
        "durable execution": "MAX_SURVIVABILITY",
        "stale-run guard": "milestone ordinal: 20",
        "bounded retry": "retry(3)",
        "automatic rollback": "Automatic rollback",
        "audit artifact": "kaiops-result.json",
        "artifact fingerprint": "fingerprint: true",
        "live safety contract": "Live self-healing requires executable preflight, validation, and rollback commands",
    }
    for capability, token in required_tokens.items():
        if token not in jenkinsfile:
            errors.append(f"Jenkinsfile missing {capability}")
    if re.search(r"\b(rm\s+-rf|kubectl\s+delete|chmod\s+777)\b", jenkinsfile, re.I):
        errors.append("Jenkinsfile contains a prohibited destructive primitive")
    return errors


def main() -> int:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    errors = validate(catalog, JENKINSFILE.read_text(encoding="utf-8"))
    for error in errors:
        print(f"ERROR: {error}")
    if errors:
        return 1
    print(f"Jenkins self-healing contract OK: {len(catalog['resolutions'])} catalog resolutions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
