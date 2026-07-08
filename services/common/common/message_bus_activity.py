from __future__ import annotations

import json
import os
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _activity_log_path() -> Path:
    configured = str(os.getenv("MESSAGE_BUS_ACTIVITY_LOG_PATH", "")).strip()
    if configured:
        return Path(configured)
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "logs" / "local" / "message-bus-activity.jsonl"


def reset_message_bus_activity_log() -> None:
    path = _activity_log_path()
    if path.exists():
        path.unlink()


def record_message_bus_activity(
    *,
    direction: str,
    topic: str,
    service: str,
    provider: str,
    key: str | None = None,
    status: str = "ok",
    metadata: dict[str, Any] | None = None,
) -> None:
    normalized_topic = str(topic or "").strip()
    normalized_service = str(service or "").strip()
    normalized_provider = str(provider or "unknown").strip().lower()
    normalized_direction = str(direction or "").strip().lower()
    if normalized_direction not in {"published", "consumed"}:
        return
    if not normalized_topic or not normalized_service:
        return

    path = _activity_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "direction": normalized_direction,
        "topic": normalized_topic,
        "service": normalized_service,
        "provider": normalized_provider,
        "key": str(key or "").strip() or None,
        "status": str(status or "ok").strip().lower(),
        "metadata": metadata or {},
    }
    try:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, default=str) + "\n")
    except OSError:
        return



def summarize_message_bus_activity(limit: int = 2000) -> dict[str, Any]:
    path = _activity_log_path()
    if not path.exists():
        return {
            "totals": {"published_events": 0, "consumed_events": 0, "topics_seen": 0},
            "published_topics": [],
            "consumed_topics": [],
            "topic_rows": [],
            "service_rows": [],
            "recent_events": [],
        }

    events: deque[dict[str, Any]] = deque(maxlen=max(1, int(limit)))
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                raw = line.strip()
                if not raw:
                    continue
                try:
                    record = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    events.append(record)
    except OSError:
        return {
            "totals": {"published_events": 0, "consumed_events": 0, "topics_seen": 0},
            "published_topics": [],
            "consumed_topics": [],
            "topic_rows": [],
            "service_rows": [],
            "recent_events": [],
        }

    by_topic: dict[str, dict[str, Any]] = {}
    by_service: dict[str, dict[str, Any]] = {}
    published_topics: list[str] = []
    consumed_topics: list[str] = []
    published_events = 0
    consumed_events = 0

    for event in events:
        topic = str(event.get("topic") or "").strip()
        service = str(event.get("service") or "").strip()
        provider = str(event.get("provider") or "unknown").strip().lower()
        direction = str(event.get("direction") or "").strip().lower()
        timestamp = str(event.get("timestamp") or "").strip()
        status = str(event.get("status") or "ok").strip().lower()
        if not topic or not service or direction not in {"published", "consumed"}:
            continue

        topic_row = by_topic.setdefault(
            topic,
            {
                "Topic": topic,
                "Published": 0,
                "Consumed": 0,
                "Last Provider": provider.upper(),
                "Last Service": service,
                "Last Activity At": timestamp,
                "Last Status": status.upper(),
            },
        )
        service_row = by_service.setdefault(
            service,
            {
                "Service": service,
                "Published": 0,
                "Consumed": 0,
                "Last Provider": provider.upper(),
                "Last Topic": topic,
                "Last Activity At": timestamp,
            },
        )

        if direction == "published":
            topic_row["Published"] += 1
            service_row["Published"] += 1
            published_events += 1
            if topic not in published_topics:
                published_topics.append(topic)
        else:
            topic_row["Consumed"] += 1
            service_row["Consumed"] += 1
            consumed_events += 1
            if topic not in consumed_topics:
                consumed_topics.append(topic)

        topic_row["Last Provider"] = provider.upper()
        topic_row["Last Service"] = service
        topic_row["Last Activity At"] = timestamp
        topic_row["Last Status"] = status.upper()
        service_row["Last Provider"] = provider.upper()
        service_row["Last Topic"] = topic
        service_row["Last Activity At"] = timestamp

    recent_events = list(reversed(list(events)[-20:]))
    topic_rows = sorted(by_topic.values(), key=lambda item: str(item["Topic"]))
    service_rows = sorted(by_service.values(), key=lambda item: str(item["Service"]))

    return {
        "totals": {
            "published_events": published_events,
            "consumed_events": consumed_events,
            "topics_seen": len(by_topic),
        },
        "published_topics": published_topics,
        "consumed_topics": consumed_topics,
        "topic_rows": topic_rows,
        "service_rows": service_rows,
        "recent_events": recent_events,
    }
