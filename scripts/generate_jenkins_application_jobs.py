"""Generate governed Jenkins job definitions from KaiOps application registrations."""
from __future__ import annotations

import argparse
import json
import re
import urllib.request
from pathlib import Path
from typing import Any


def _slug(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "application").lower()).strip("-") or "application"


def _load_json(location: str) -> Any:
    if location.startswith(("http://", "https://")):
        with urllib.request.urlopen(location, timeout=30) as response:  # noqa: S310 - operator-supplied URL
            return json.load(response)
    return json.loads(Path(location).read_text(encoding="utf-8"))


def generate(applications: list[dict[str, Any]], catalog: dict[str, Any]) -> dict[str, Any]:
    profiles = catalog.get("technology_profiles", {})
    defaults = list(catalog.get("defaults", []))
    definitions = catalog.get("resolutions", {})
    jobs = []
    for row in applications:
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else row
        technology = str(payload.get("technology") or "").lower()
        resolution_ids = list(dict.fromkeys([*profiles.get(technology, []), *defaults]))
        resolutions = {
            key: definitions[key]
            for key in resolution_ids
            if key in definitions and definitions[key].get("enabled", True) is not False
        }
        name = str(payload.get("name") or row.get("name") or "application")
        jobs.append({
            "job_name": f"kaiops/remediation/{_slug(name)}",
            "application_id": str(payload.get("id") or row.get("id") or ""),
            "application": name,
            "service": str(payload.get("labels", {}).get("service") or name),
            "environment": str(payload.get("environment") or "prod"),
            "namespace": str(payload.get("namespace") or "default"),
            "technology": technology or "unknown",
            "jenkinsfile": "deploy/jenkins/Jenkinsfile.auto-remediation",
            "resolution_ids": list(resolutions),
            "resolutions": resolutions,
        })
    return {
        "catalog_version": catalog.get("version", 1),
        "contract": catalog.get("contract", "kaiops.remediation.v1"),
        "policy": catalog.get("policy", {}),
        "jobs": jobs,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--applications", required=True, help="Applications JSON file or /applications URL")
    parser.add_argument("--catalog", default="deploy/jenkins/application-resolution-catalog.json")
    parser.add_argument("--output", default="deploy/jenkins/generated/application-jobs.json")
    args = parser.parse_args()
    raw = _load_json(args.applications)
    applications = raw.get("rows", raw) if isinstance(raw, dict) else raw
    if not isinstance(applications, list):
        raise ValueError("Applications input must be a list or an object containing rows")
    result = generate(applications, _load_json(args.catalog))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Generated {len(result['jobs'])} Jenkins application jobs in {output}")


if __name__ == "__main__":
    main()
