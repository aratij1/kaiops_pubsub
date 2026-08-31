"""Inspect and replay messages sitting in a KaiOps RabbitMQ dead-letter queue.

Every RabbitMQConsumer (backend/src/common/common/rabbitmq.py) republishes a
message to `<original-queue>.dlq` after `RABBITMQ_CONSUMER_MAX_RETRIES` failed
handler attempts, but nothing in the platform ever reads that queue back —
failed alerts/events accumulate there silently forever. This script uses the
RabbitMQ Management HTTP API (already exposed on port 15672 by the
`rabbitmq:3.13-management` image in docker-compose.yml) to list DLQ queues and
replay their contents back onto the original topic.

Examples:

    python scripts/replay_dead_letters.py --list

    python scripts/replay_dead_letters.py --queue kaiops.alert-intelligence.raw-alerts.dlq --dry-run

    python scripts/replay_dead_letters.py --queue kaiops.alert-intelligence.raw-alerts.dlq --limit 50
"""

from __future__ import annotations

import argparse
import base64
import json
from urllib.parse import quote

import httpx


def list_dlq_queues(client: httpx.Client, vhost: str) -> list[dict]:
    resp = client.get(f"/api/queues/{quote(vhost, safe='')}")
    resp.raise_for_status()
    queues = resp.json()
    return [q for q in queues if str(q.get("name", "")).endswith(".dlq")]


def fetch_messages(client: httpx.Client, vhost: str, queue: str, count: int, *, remove: bool) -> list[dict]:
    ackmode = "ack_requeue_false" if remove else "ack_requeue_true"
    resp = client.post(
        f"/api/queues/{quote(vhost, safe='')}/{quote(queue, safe='')}/get",
        json={"count": count, "ackmode": ackmode, "encoding": "auto"},
    )
    resp.raise_for_status()
    return resp.json()


def decode_body(message: dict) -> dict | None:
    payload_raw = message.get("payload")
    if message.get("payload_encoding") == "base64":
        try:
            payload_raw = base64.b64decode(payload_raw).decode("utf-8")
        except Exception:
            return None
    try:
        decoded = json.loads(payload_raw)
    except (TypeError, ValueError):
        return None
    return decoded if isinstance(decoded, dict) else None


def republish(client: httpx.Client, vhost: str, exchange: str, topic: str, payload: dict) -> None:
    envelope = {"topic": topic, "key": None, "payload": payload}
    resp = client.post(
        f"/api/exchanges/{quote(vhost, safe='')}/{quote(exchange, safe='')}/publish",
        json={
            "properties": {"delivery_mode": 2, "content_type": "application/json"},
            "routing_key": topic,
            "payload": json.dumps(envelope, default=str),
            "payload_encoding": "string",
        },
    )
    resp.raise_for_status()
    if not resp.json().get("routed"):
        raise RuntimeError(f"republish to topic '{topic}' was not routed to any queue")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--management-url", default="http://localhost:15672")
    parser.add_argument("--user", default="guest")
    parser.add_argument("--password", default="guest")
    parser.add_argument("--vhost", default="/")
    parser.add_argument("--exchange", default="kaiops.events")
    parser.add_argument("--list", action="store_true", help="List DLQ queues and their message counts, then exit.")
    parser.add_argument("--queue", help="Full DLQ queue name to replay, e.g. kaiops.alert-intelligence.raw-alerts.dlq")
    parser.add_argument("--limit", type=int, default=100, help="Max messages to replay in one run.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Peek at messages (requeue them, don't remove or republish) instead of replaying them.",
    )
    args = parser.parse_args()

    with httpx.Client(base_url=args.management_url, auth=(args.user, args.password), timeout=30.0) as client:
        if args.list or not args.queue:
            queues = list_dlq_queues(client, args.vhost)
            if not queues:
                print("No DLQ queues found (or none currently hold messages' metadata).")
            for queue in queues:
                print(f"{queue['name']}: {queue.get('messages', 0)} messages")
            if not args.queue:
                return

        messages = fetch_messages(client, args.vhost, args.queue, args.limit, remove=not args.dry_run)
        if not messages:
            print(f"No messages available in {args.queue}.")
            return

        replayed = 0
        undecodable = 0
        for message in messages:
            body = decode_body(message)
            if body is None:
                undecodable += 1
                continue
            failed_topic = body.get("failed_topic")
            payload = body.get("payload")
            if not isinstance(failed_topic, str) or not isinstance(payload, dict):
                undecodable += 1
                continue

            if args.dry_run:
                print(f"[dry-run] would replay topic={failed_topic} error={body.get('error')!r}")
                continue

            republish(client, args.vhost, args.exchange, failed_topic, payload)
            replayed += 1

        mode = "peeked (dry-run)" if args.dry_run else "replayed"
        print(f"{mode}: {len(messages) - undecodable}/{len(messages)} messages ({undecodable} undecodable, left in place)")
        if not args.dry_run:
            print(f"republished: {replayed}")


if __name__ == "__main__":
    main()
