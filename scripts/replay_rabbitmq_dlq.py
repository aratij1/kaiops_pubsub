from __future__ import annotations

import argparse
import base64
import json
import os
import urllib.request
from pathlib import Path
from typing import Any


def _publish(url: str, username: str, password: str, routing_key: str, payload: dict[str, Any]) -> bool:
    body = json.dumps(
        {
            "properties": {},
            "routing_key": routing_key,
            "payload": json.dumps({"topic": routing_key, "payload": payload}),
            "payload_encoding": "string",
        }
    ).encode("utf-8")
    credentials = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Authorization": f"Basic {credentials}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.loads(response.read().decode("utf-8"))
    return bool(result.get("routed"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay rabbitmqadmin raw_json DLQ exports.")
    parser.add_argument("path", type=Path)
    parser.add_argument("--routing-key", required=True)
    parser.add_argument(
        "--url",
        default="http://rabbitmq:15672/api/exchanges/%2F/kaiops.events/publish",
    )
    args = parser.parse_args()
    rows = json.loads(args.path.read_text(encoding="utf-8"))
    replayed = 0
    for row in rows:
        failed = json.loads(row["payload"])
        payload = failed.get("payload")
        if not isinstance(payload, dict):
            continue
        if _publish(
            args.url,
            os.getenv("RABBITMQ_DEFAULT_USER", "guest"),
            os.getenv("RABBITMQ_DEFAULT_PASS", "guest"),
            args.routing_key,
            payload,
        ):
            replayed += 1
    print(json.dumps({"replayed": replayed, "examined": len(rows)}))


if __name__ == "__main__":
    main()
