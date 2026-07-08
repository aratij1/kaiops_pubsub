from __future__ import annotations

import os
from typing import Any


SERVICE_TOPIC_FLOW: list[dict[str, str]] = [
    {"service": "monitoring-adapter", "consumes": "-", "publishes": "raw-alerts", "agent": "alert"},
    {"service": "alert-intelligence", "consumes": "raw-alerts", "publishes": "enriched-alerts", "agent": "Alert Intelligence Agent"},
    {"service": "orchestrator", "consumes": "enriched-alerts", "publishes": "orchestration-events", "agent": "Orchestrator Agent"},
    {"service": "context-agent", "consumes": "orchestration-events", "publishes": "context-events", "agent": "Context Intelligence Agent"},
    {"service": "resolution-agent", "consumes": "context-events", "publishes": "resolution-events", "agent": "Resolution Intelligence Agent"},
    {"service": "approval-service", "consumes": "resolution-events", "publishes": "approval-events", "agent": "Human Approval Layer"},
    {"service": "remediation-engine", "consumes": "approval-events", "publishes": "remediation-events", "agent": "Remediation Automation Engine"},
    {"service": "closure-service", "consumes": "remediation-events", "publishes": "closure-events", "agent": "Closure & Validation"},
]


def get_message_bus_runtime_config() -> dict[str, str]:
    return {
        "event_bus_provider": os.getenv("EVENT_BUS_PROVIDER", "kafka"),
        "message_bus_dynamic_routing": os.getenv("MESSAGE_BUS_DYNAMIC_ROUTING", "true"),
        "message_bus_stream_threshold": os.getenv("MESSAGE_BUS_STREAM_THRESHOLD", "500"),
        "message_bus_default_provider": os.getenv("MESSAGE_BUS_DEFAULT_PROVIDER", "rabbitmq"),
        "message_bus_worker_count": os.getenv("MESSAGE_BUS_WORKER_COUNT", "1"),
        "kafka_enabled": os.getenv("KAFKA_ENABLED", "true"),
    }


def get_message_bus_topic_rows() -> list[dict[str, str]]:
    return [
        {
            "Service": row["service"],
            "Consumes": row["consumes"] if row["consumes"] == "-" else f"{row['consumes']} (enabled transports)",
            "Publishes": row["publishes"],
        }
        for row in SERVICE_TOPIC_FLOW
    ]


def get_actual_topic_activity(workflow: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(workflow, dict):
        return {"published": [], "consumed": [], "rows": []}

    events = workflow.get("events", []) if isinstance(workflow.get("events"), list) else []
    observed_agents = {str(item.get("agent", "")).strip() for item in events if isinstance(item, dict)}
    observed_provider = str(extract_observed_routing_metrics(workflow).get("message_bus_provider") or "").strip().lower()
    approval = workflow.get("approval", {}) if isinstance(workflow.get("approval"), dict) else {}
    remediation = workflow.get("remediation_action", {}) if isinstance(workflow.get("remediation_action"), dict) else {}
    closure = workflow.get("closure_report", {}) if isinstance(workflow.get("closure_report"), dict) else {}
    has_workflow = bool(workflow.get("alert") or workflow.get("incident") or events)

    published: list[str] = []
    consumed: list[str] = []
    rows: list[dict[str, str]] = []

    for row in SERVICE_TOPIC_FLOW:
        service = row["service"]
        consumes = row["consumes"]
        publishes = row["publishes"]
        agent = row["agent"]

        is_observed = False
        if agent == "alert":
            is_observed = has_workflow
        elif agent in observed_agents:
            is_observed = True
        elif agent == "Human Approval Layer" and approval:
            is_observed = True
        elif agent == "Remediation Automation Engine" and remediation:
            is_observed = True
        elif agent == "Closure & Validation" and closure:
            is_observed = True

        status = "Observed" if is_observed else "Not reached"
        provider = observed_provider.upper() if observed_provider else "N/A"

        if is_observed:
            if consumes != "-" and consumes not in consumed:
                consumed.append(consumes)
            if publishes not in published:
                published.append(publishes)

        rows.append(
            {
                "Service": service,
                "Consumed": consumes if is_observed else "-",
                "Published": publishes if is_observed else "-",
                "Provider": provider,
                "Status": status,
            }
        )

    return {
        "published": published,
        "consumed": consumed,
        "rows": rows,
    }


def extract_observed_routing_metrics(workflow: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(workflow, dict):
        return {}
    events = workflow.get("events", [])
    if not isinstance(events, list):
        return {}
    orchestrator_event = next(
        (item for item in reversed(events) if str(item.get("agent", "")).strip().lower() == "orchestrator agent"),
        None,
    )
    if not isinstance(orchestrator_event, dict):
        return {}
    metrics = orchestrator_event.get("metrics", {})
    return metrics if isinstance(metrics, dict) else {}
