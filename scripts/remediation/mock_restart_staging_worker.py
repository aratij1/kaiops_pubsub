"""Safe mock remediation used by continuous-learning integration tests and demos."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime


def execute(*, incident_id: str, target: str, dry_run: bool) -> dict[str, object]:
    if not target.startswith("staging-"):
        raise ValueError("mock remediation is restricted to staging-* targets")
    return {
        "incident_id": incident_id,
        "target": target,
        "dry_run": dry_run,
        "changed": not dry_run,
        "validation": {
            "alert_cleared": True,
            "service_health_restored": True,
            "error_rate_acceptable": True,
            "latency_acceptable": True,
            "dependencies_healthy": True,
            "no_regressions": True,
        },
        "rollback": "mock action has no external side effects",
        "completed_at": datetime.now(UTC).isoformat(),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--incident-id", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--execute", action="store_true", help="simulate a state change; default is dry-run")
    args = parser.parse_args()
    print(json.dumps(execute(incident_id=args.incident_id, target=args.target, dry_run=not args.execute)))
