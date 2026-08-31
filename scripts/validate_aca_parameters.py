"""Fail-closed validation for Azure Container Apps deployment parameters."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REQUIRED_APPS = {"ui", "api-gateway", "monitoring-adapter", "alert-intelligence", "orchestrator", "context-agent", "resolution-agent", "approval-service", "remediation-engine", "closure-service", "model-router"}


def validate(path: Path, *, allow_placeholders: bool = False) -> list[str]:
    document = json.loads(path.read_text(encoding="utf-8"))
    apps = document.get("parameters", {}).get("apps", {}).get("value", [])
    errors: list[str] = []
    if not isinstance(apps, list) or not apps:
        return ["parameters.apps.value must be a non-empty array"]
    names = [str(app.get("name", "")) for app in apps]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        errors.append(f"duplicate app names: {', '.join(duplicates)}")
    missing = sorted(REQUIRED_APPS.difference(names))
    if missing:
        errors.append(f"missing required apps: {', '.join(missing)}")
    if [app.get("name") for app in apps if app.get("external")] != ["ui"]:
        errors.append("only ui may have external ingress")
    for app in apps:
        name = app.get("name", "<unnamed>")
        image = str(app.get("image", ""))
        minimum, maximum = app.get("minReplicas"), app.get("maxReplicas")
        if not image:
            errors.append(f"{name}: image is required")
        if image.endswith(":latest") and not allow_placeholders:
            errors.append(f"{name}: immutable image tag or digest required")
        if not isinstance(minimum, int) or not isinstance(maximum, int) or minimum < 0 or maximum < minimum:
            errors.append(f"{name}: invalid replica range {minimum!r}..{maximum!r}")
        if app.get("queueScale") and (not app.get("topic") or not app.get("subscription")):
            errors.append(f"{name}: queue scaling requires topic and subscription")
    if not allow_placeholders and "REPLACE" in json.dumps(document):
        errors.append("unresolved REPLACE placeholder found")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", type=Path, default=Path("deploy/azure-container-apps/production.parameters.json"))
    parser.add_argument("--allow-placeholders", action="store_true")
    args = parser.parse_args()
    errors = validate(args.path, allow_placeholders=args.allow_placeholders)
    for error in errors:
        print(f"ERROR: {error}")
    if errors:
        return 1
    print(f"Validated {args.path} ({'template' if args.allow_placeholders else 'production'} mode)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
