from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.request import Request, urlopen


def classify(payload: dict) -> tuple[str, dict]:
    alert = payload.get("alert") if isinstance(payload.get("alert"), dict) else payload
    labels = alert.get("labels") if isinstance(alert.get("labels"), dict) else {}
    tokens = " ".join(
        str(value or "").strip().lower()
        for value in (
            alert.get("origin_system"),
            labels.get("origin_system"),
            alert.get("source"),
            payload.get("source"),
            alert.get("project_name"),
            labels.get("project_name"),
            alert.get("application"),
            labels.get("application"),
        )
    )
    if "telemetry" in tokens or "opentelemetry" in tokens or "astronomy" in tokens:
        return "telemetry", alert
    if "prometheus" in tokens or "alertmanager" in tokens:
        return "prometheus", alert
    if "email" in tokens or "mail" in tokens:
        return "email", alert
    if "jira" in tokens or "ticket" in tokens:
        return "jira", alert
    if "log" in tokens or "opensearch" in tokens or "docker" in tokens:
        return "logs", alert
    return "", alert


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay latest real persisted source events into the live stream.")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--endpoint", default="http://localhost:8001/landing-pad/events")
    parser.add_argument("--per-source", type=int, default=2)
    parser.add_argument("--source", action="append", dest="sources")
    args = parser.parse_args()

    wanted = set(args.sources or ["prometheus", "telemetry", "email", "jira", "logs"])
    selected: dict[str, list[dict]] = {source: [] for source in wanted}
    files = sorted(args.root.rglob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in files:
        if all(len(rows) >= args.per_source for rows in selected.values()):
            break
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        source, alert = classify(payload)
        if source not in selected or len(selected[source]) >= args.per_source:
            continue
        selected[source].append(alert)

    replayed: dict[str, int] = {}
    for source, alerts in selected.items():
        replayed[source] = 0
        for alert in reversed(alerts):
            body = json.dumps(
                {
                    "origin_system": source,
                    "source": alert.get("source") or source,
                    "name": alert.get("name") or "Persisted source event",
                    "service": alert.get("service") or source,
                    "severity": alert.get("severity") or "warning",
                    "description": alert.get("description") or "",
                }
            ).encode("utf-8")
            request = Request(args.endpoint, data=body, headers={"Content-Type": "application/json"}, method="POST")
            with urlopen(request, timeout=10) as response:
                if response.status >= 400:
                    raise RuntimeError(f"replay failed with HTTP {response.status}")
            replayed[source] += 1

    print(json.dumps({"replayed": replayed}, sort_keys=True))
    return 0 if all(count >= args.per_source for count in replayed.values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
