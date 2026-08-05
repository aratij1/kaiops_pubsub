import json
import os
import sys
from pathlib import Path

# Optional run tag (e.g. a worker-count label for benchmarking) so repeated
# runs produce fresh, non-deduplicated ids/fingerprints instead of colliding
# with a previous run's identical payloads. Usage: python gen_test_data.py w5
TAG = sys.argv[1] if len(sys.argv) > 1 else ""
BASE_DIR = str(Path(__file__).resolve().parent)
OUT_DIR = os.path.join(BASE_DIR, f"run-{TAG}") if TAG else BASE_DIR
os.makedirs(OUT_DIR, exist_ok=True)

CATEGORIES = [
    "database", "network", "cpu", "memory", "disk", "application", "api",
    "kubernetes", "rabbitmq", "kafka", "redis", "mysql", "authentication",
    "payment", "inventory",
]

# Wording is chosen deliberately to land in the correct discovery.py _impact()
# bucket, since priority is derived from severity + these exact keywords, not
# from labels:
#   P1 -> severity=critical + bucket-1 words (outage/unavailable/down/data loss)
#   P2 -> severity=high     + bucket-2 words (timeout/error/failed/degraded/latency)
#   P3 -> severity=warning  + neutral wording (bucket-3, no floor/escalation words)
#   P4 -> severity=info     + neutral wording (bucket-3)
P1_WORDING = {
    "database": "Primary database cluster outage, all queries failing and unavailable",
    "network": "Complete network outage in the primary region, all routes unavailable",
    "cpu": "Host CPU pegged at 100 percent, service unavailable to all clients",
    "memory": "OOM killer triggered repeatedly, application unavailable, in-flight writes at risk of data loss",
    "disk": "Disk array failure, storage volume completely unavailable",
    "application": "Checkout application outage, no requests succeeding, service unavailable",
    "api": "Public API gateway down, all endpoints unavailable",
    "kubernetes": "Cluster control plane outage, nodes unreachable and unavailable",
    "rabbitmq": "RabbitMQ cluster outage, message delivery completely down and unavailable",
    "kafka": "Kafka broker quorum lost, cluster unavailable",
    "redis": "Redis primary node down, cache layer completely unavailable",
    "mysql": "MySQL primary outage, writes unavailable across all shards",
    "authentication": "Authentication service outage, all logins unavailable",
    "payment": "Payment gateway outage, all transactions unavailable, in-flight charges at risk of data loss",
    "inventory": "Inventory sync service outage, stock levels unavailable storewide",
}

P2_WORDING = {
    "database": "Repeated query timeouts and elevated error rates on the primary database",
    "network": "Intermittent packet loss causing request timeouts across the network fabric",
    "cpu": "Sustained high CPU causing request latency and timeout errors",
    "memory": "Memory pressure causing garbage-collection pauses and degraded response latency",
    "disk": "Disk I/O latency degraded, write operations timing out intermittently",
    "application": "Application error rate elevated with repeated request timeouts",
    "api": "API response latency degraded, several endpoints returning timeout errors",
    "kubernetes": "Pod scheduling degraded, repeated container restarts and readiness timeouts",
    "rabbitmq": "RabbitMQ consumer lag degraded, message processing timeouts increasing",
    "kafka": "Kafka consumer group degraded, partition rebalance timeouts observed",
    "redis": "Redis latency degraded, command timeouts increasing under load",
    "mysql": "MySQL replica lag degraded, replication timeouts intermittent",
    "authentication": "Authentication latency degraded, token validation timeouts increasing",
    "payment": "Payment processing degraded, gateway timeouts on a subset of transactions",
    "inventory": "Inventory update latency degraded, sync job timeouts increasing",
}

P3_WORDING = {
    "database": "Elevated query queue depth observed on the reporting database, requires verification",
    "network": "Minor throughput variance observed on the secondary network link",
    "cpu": "CPU utilization trending upward on a background worker host",
    "memory": "Memory usage trending upward on a background worker, requires verification",
    "disk": "Disk usage crossed a capacity watch threshold on a secondary volume",
    "application": "Background job queue depth elevated, requires verification",
    "api": "API request volume above the typical baseline for this hour",
    "kubernetes": "Node resource usage trending upward, requires verification",
    "rabbitmq": "RabbitMQ queue depth elevated on a non-critical queue",
    "kafka": "Kafka consumer offset lag observed on a non-critical topic",
    "redis": "Redis memory usage trending upward, requires verification",
    "mysql": "MySQL connection pool usage elevated, requires verification",
    "authentication": "Authentication request volume above baseline, requires verification",
    "payment": "Payment queue depth elevated on the retry pipeline, requires verification",
    "inventory": "Inventory sync queue depth elevated, requires verification",
}

P4_WORDING = {
    "database": "Routine database maintenance job completed with a minor advisory notice",
    "network": "Routine network interface flap observed and self-recovered",
    "cpu": "Routine CPU scaling event observed during a scheduled autoscale check",
    "memory": "Routine pod restart observed during a scheduled maintenance window",
    "disk": "Routine disk cleanup job completed with an informational notice",
    "application": "Routine application restart observed during a deployment window",
    "api": "Routine API health probe flagged an informational notice",
    "kubernetes": "Routine node cordon observed during a scheduled upgrade window",
    "rabbitmq": "Routine RabbitMQ queue purge completed with an informational notice",
    "kafka": "Routine Kafka topic retention cleanup completed",
    "redis": "Routine Redis key eviction cycle completed with an informational notice",
    "mysql": "Routine MySQL backup job completed with an informational notice",
    "authentication": "Routine authentication token rotation completed",
    "payment": "Routine payment reconciliation job completed with an informational notice",
    "inventory": "Routine inventory recount job completed with an informational notice",
}

PRIORITY_PLAN = {
    "P1": {"severity": "critical", "wording": P1_WORDING},
    "P2": {"severity": "high", "wording": P2_WORDING},
    "P3": {"severity": "warning", "wording": P3_WORDING},
    "P4": {"severity": "info", "wording": P4_WORDING},
}

# Cycle priority P1,P2,P3,P4,P1,P2,P3,P4... and category 0..14 independently,
# so category+priority combos vary across the run. At COUNT=100 with only 15
# categories, the same (category, priority) pair recurs ~6-7 times -- worded()
# below appends a distinct real-sounding detail (region/host) each time so
# repeats read as distinct incidents, not literal copies.
PRIORITY_CYCLE = ["P1", "P2", "P3", "P4"]
COUNT = int(os.environ.get("ALERT_COUNT", "100"))

_REGIONS = ["us-east-1", "us-west-2", "eu-west-1", "ap-south-1", "eu-central-1", "sa-east-1", "ca-central-1"]
_HOST_PREFIXES = ["host", "node", "pod", "instance", "shard", "replica", "worker"]


def variant_detail(idx):
    region = _REGIONS[idx % len(_REGIONS)]
    host = f"{_HOST_PREFIXES[idx % len(_HOST_PREFIXES)]}-{(idx % 37) + 1:02d}"
    return region, host


def worded(cfg, category, idx):
    region, host = variant_detail(idx)
    base = cfg["wording"][category]
    return f"{base} (region={region}, {host})"


def plan_n(n=None):
    n = n if n is not None else COUNT
    items = []
    for i in range(n):
        priority = PRIORITY_CYCLE[i % 4]
        category = CATEGORIES[i % len(CATEGORIES)]
        items.append((i + 1, priority, category))
    return items


# Backward-compatible alias (older docs/scripts reference plan_25()).
def plan_25():
    return plan_n(25)


def title_for(category, priority):
    cat_title = category.replace("_", " ").title()
    return f"{cat_title} {priority} test alert"


def service_for(channel, category, idx):
    suffix = f"-{TAG}" if TAG else ""
    return f"{channel}-{category}-svc-{idx:02d}{suffix}"


def uid(base):
    return f"{base}-{TAG}" if TAG else base


# ---------------------------------------------------------------------------
# 1. Prometheus / Alertmanager  (POST /alerts/alertmanager)
# ---------------------------------------------------------------------------
def build_prometheus():
    alerts = []
    for idx, priority, category in plan_n():
        cfg = PRIORITY_PLAN[priority]
        service = service_for("prom", category, idx)
        description = worded(cfg, category, idx)
        alerts.append({
            "status": "firing",
            "labels": {
                "alertname": f"{category.title()}Alert{idx:02d}",
                "service": service,
                "severity": cfg["severity"],
                "environment": "production",
                "category_hint": category,
            },
            "annotations": {"summary": description},
            "fingerprint": uid(f"prom-fp-{idx:02d}-{category}"),
            "startsAt": "2026-08-03T12:00:00Z",
        })
    return {
        "status": "firing",
        "commonLabels": {},
        "commonAnnotations": {},
        "alerts": alerts,
    }


# ---------------------------------------------------------------------------
# 2. Email (landing-pad file-drop shape, consumed by email_to_alert() in
#    monitoring_adapter/landing_pad_sources.py)
# ---------------------------------------------------------------------------
def build_email():
    items = []
    severity_subject_tag = {"critical": "SEV1", "high": "SEV2", "warning": "SEV3", "info": "SEV4"}
    for idx, priority, category in plan_n():
        cfg = PRIORITY_PLAN[priority]
        service = service_for("email", category, idx)
        description = worded(cfg, category, idx)
        tag = severity_subject_tag[cfg["severity"]]
        items.append({
            "message_id": uid(f"email-test-{idx:02d}-{category}") + "@kaiops.test",
            "subject": f"[{tag}] {title_for(category, priority)}",
            "from": "monitoring-alerts@kaiops.test",
            "body": f"Service: {service}\nEnvironment: production\n\n{description}",
            "received_at": "2026-08-03T12:00:00Z",
        })
    return items


# ---------------------------------------------------------------------------
# 3. Jira (webhook shape, POST /api/v1/alerts/jira?token=...)
# ---------------------------------------------------------------------------
def build_jira():
    items = []
    jira_priority_name = {"critical": "Highest", "high": "High", "warning": "Medium", "info": "Low"}
    project_key = f"TESTQ{TAG.upper()}" if TAG else "TESTQ"
    for idx, priority, category in plan_n():
        cfg = PRIORITY_PLAN[priority]
        service = service_for("jira", category, idx)
        description = worded(cfg, category, idx)
        items.append({
            "webhookEvent": "jira:issue_created",
            "issue": {
                "key": f"{project_key}-{1000 + idx}",
                "fields": {
                    "summary": f"{title_for(category, priority)} ({service})",
                    "description": description,
                    "priority": {"name": jira_priority_name[cfg["severity"]]},
                    "status": {"name": "Open"},
                    "project": {"key": project_key},
                    "labels": ["e2e-test", category],
                    "components": [{"name": category}],
                },
            },
        })
    return items


# ---------------------------------------------------------------------------
# 4. Logs (structured JSON lines matching log_line_to_alert_payload(), for
#    dropping into a LOG_WATCH_PATHS-watched file or the landing-pad log path)
# ---------------------------------------------------------------------------
def build_logs():
    # log_line_to_alert_payload() hard-drops (returns None, no alert at all)
    # any structured line whose level isn't error/critical/fatal -- warning
    # and info level lines are treated as pure noise by design. So P3/P4 are
    # structurally impossible on this channel; this generates a realistic
    # P1/P2-only mix (critical/fatal -> P1-equivalent, error -> P2-equivalent)
    # instead of handing over data that would silently vanish on ingestion.
    lines = []
    for i in range(COUNT):
        category = CATEGORIES[i % len(CATEGORIES)]
        is_p1 = (i % 2 == 0)
        priority = "P1" if is_p1 else "P2"
        level = "critical" if is_p1 else "error"
        cfg = PRIORITY_PLAN[priority]
        service = service_for("log", category, i + 1)
        message = worded(cfg, category, i + 1)
        record = {
            "timestamp": "2026-08-03T12:00:00Z",
            "level": level,
            "service": service,
            "environment": "production",
            "message": message,
            "component": category,
            "scenario_id": f"e2e-log-{i + 1:02d}",
        }
        lines.append(json.dumps(record))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# 5. Invalid / malformed payloads, for validation/DLQ/retry/isolation testing.
#
# IMPORTANT (verified directly against the code, corrected from an earlier
# incorrect assumption): POST /alerts takes `payload: dict = Body(...)` with
# NO field-level schema -- _build_alert_from_payload() supplies a lenient
# fallback for every field (source/name/service/description all default to
# generic strings; severity falls back to "warning" for any unrecognized
# value). So "missing field" / "wrong type" / "invalid enum" / "empty body"
# do NOT error on this endpoint -- they succeed with generic values. Each
# case below is labeled with "actually_errors": true/false so you know which
# ones to expect a real 4xx from versus which are silently accepted.
# ---------------------------------------------------------------------------
def build_invalid():
    return [
        {
            "case": "missing_fields",
            "endpoint": "POST /alerts",
            "actually_errors": False,
            "expect": "200 OK -- service/name/description all default to generic fallback values, no error",
            "body": {"id": "invalid-01", "source": "prometheus", "severity": "critical",
                     "title": "Missing service field", "description": "no service field provided"},
        },
        {
            "case": "wrong_type_for_severity",
            "endpoint": "POST /alerts",
            "actually_errors": False,
            "expect": "200 OK -- severity is str()-coerced then falls back to 'warning' since '12345' isn't a recognized value",
            "body": {"id": "invalid-02", "source": "prometheus", "service": "bad-type-svc",
                     "environment": "production", "severity": 12345,
                     "title": "Wrong type", "description": "severity is a number, not a string"},
        },
        {
            "case": "invalid_severity_enum_value",
            "endpoint": "POST /alerts",
            "actually_errors": False,
            "expect": "200 OK -- unrecognized severity string falls back to 'warning', no error",
            "body": {"id": "invalid-03", "source": "prometheus", "service": "bad-enum-svc",
                     "environment": "production", "severity": "super-critical",
                     "title": "Invalid enum", "description": "severity value not in the allowed enum"},
        },
        {
            "case": "empty_body",
            "endpoint": "POST /alerts",
            "actually_errors": False,
            "expect": "200 OK -- every field defaults (source='unknown', name='unknown-alert', etc.), no error",
            "body": {},
        },
        {
            "case": "wrong_json_malformed_syntax",
            "endpoint": "POST /alerts",
            "actually_errors": True,
            "expect": "422 -- this is the one genuine parse failure: syntactically invalid JSON can't bind to `dict` at all",
            "raw_body": '{"id": "invalid-05", "source": "prometheus", "service": "broken-json-svc" ',
        },
        {
            "case": "wrong_json_non_object_body",
            "endpoint": "POST /alerts",
            "actually_errors": True,
            "expect": "422 -- valid JSON but a top-level array/string/number instead of an object also can't bind to `dict`",
            "raw_body": '["this", "is", "an", "array", "not", "an", "object"]',
        },
        {
            "case": "unsupported_provider",
            "endpoint": "POST /api/v1/alerts/nonexistentvendor",
            "actually_errors": True,
            "expect": "422/500 -- normalize_provider_name() raises ValueError for a provider not in SUPPORTED_MONITORING_PROVIDERS",
            "body": {"id": "invalid-06", "alertname": "test", "severity": "critical"},
        },
        {
            "case": "jira_webhook_missing_token",
            "endpoint": "POST /api/v1/alerts/jira  (call WITHOUT the ?token= query param)",
            "actually_errors": True,
            "expect": "401/403 -- the one endpoint with real auth enforcement; fails closed with no token configured",
            "body": {"webhookEvent": "jira:issue_created", "issue": {"key": "TESTQ-9999", "fields": {"summary": "no token test"}}},
        },
        {
            "case": "jira_webhook_missing_fields",
            "endpoint": "POST /api/v1/alerts/jira?token=<JIRA_WEBHOOK_SECRET>",
            "actually_errors": False,
            "expect": "200 OK -- issue.fields absent just yields a mostly-empty alert, same lenient-fallback pattern",
            "body": {"webhookEvent": "jira:issue_created", "issue": {"key": "TESTQ-9998"}},
        },
        {
            "case": "alertmanager_alerts_wrong_type",
            "endpoint": "POST /alerts/alertmanager",
            "actually_errors": False,
            "expect": "200 OK with received count reflecting only valid entries; malformed 'alerts' array entries (a string/number instead of a dict) must not crash the handler",
            "body": {"status": "firing", "alerts": ["not-a-dict", 12345, {"status": "firing", "labels": {"alertname": "PartiallyValid"}}]},
        },
        {
            "case": "oversized_description_field",
            "endpoint": "POST /alerts",
            "actually_errors": False,
            "expect": "200 OK accepted; description should be safely truncated downstream (evidence summary capped at 1000 chars) and must not crash any consumer",
            "body": {"id": "invalid-10", "source": "prometheus", "service": "oversized-field-svc",
                     "environment": "production", "severity": "warning",
                     "title": "Oversized description",
                     "description": ("error timeout degraded " * 2000)},
        },
    ]


# ---------------------------------------------------------------------------
# 6. Duplicate alerts -- the identical payload sent twice (or more), one set
# per channel, to test each channel's own dedup mechanism specifically.
# ---------------------------------------------------------------------------
def build_duplicates():
    dup_fingerprint = uid("dup-fp-checkout-001")
    prometheus_dup = {
        "status": "firing",
        "labels": {"alertname": "DuplicateTest", "service": "dup-prom-svc", "severity": "warning", "environment": "production"},
        "annotations": {"summary": "duplicate delivery test"},
        "fingerprint": dup_fingerprint,
        "startsAt": "2026-08-03T12:00:00Z",
    }
    dup_message_id = uid("dup-email-test") + "@kaiops.test"
    email_dup = {
        "message_id": dup_message_id,
        "subject": "[SEV3] Duplicate delivery test",
        "from": "monitoring-alerts@kaiops.test",
        "body": "Service: dup-email-svc\nEnvironment: production\n\nduplicate delivery test",
        "received_at": "2026-08-03T12:00:00Z",
    }
    dup_key = f"{uid('TESTQDUP')}-1"
    jira_dup = {
        "webhookEvent": "jira:issue_created",
        "issue": {
            "key": dup_key,
            "fields": {
                "summary": "Duplicate delivery test", "description": "duplicate delivery test",
                "priority": {"name": "Medium"}, "status": {"name": "Open"},
                "project": {"key": "TESTQDUP"}, "labels": ["e2e-test", "duplicate"],
            },
        },
    }
    # Dynatrace/Azure/Splunk all use the same _provider_delivery_key TTL guard
    # (provider+alertName+application+environment+resource) -- one shared
    # example is enough to exercise it.
    dynatrace_dup = {
        "ProblemID": uid("dup-84322"), "ProblemTitle": "Duplicate delivery test",
        "ProblemSeverity": "CUSTOM_ALERT", "State": "OPEN",
        "ImpactedEntities": [{"name": "dup-host-01"}],
        "Tags": "environment:production, service:dup-dynatrace-svc",
    }
    return {
        "note": "Send each payload below TWICE in a row. Prometheus/vendor paths should show 'skipped'/'deduplicated' the second time; Jira relies on _is_kaiops_managed_jira_update()/_JIRA_SESSION_VERSIONS instead of a fingerprint.",
        "prometheus": {"endpoint": "POST /alerts/alertmanager", "payload": {"status": "firing", "alerts": [prometheus_dup]}},
        "email": {"note": "drop as two identical .json files into the landing-pad input dir", "payload": email_dup},
        "jira": {"endpoint": "POST /api/v1/alerts/jira?token=<JIRA_WEBHOOK_SECRET>", "payload": jira_dup},
        "dynatrace": {"endpoint": "POST /api/v1/alerts/dynatrace", "payload": dynatrace_dup},
    }


# ---------------------------------------------------------------------------
# 7. Poison messages -- payloads that pass HTTP-layer ingestion (or bypass it
# entirely) but are malformed at the message-bus level, to exercise
# common/rabbitmq.py's consume_forever() defenses directly: a message body
# that isn't valid JSON, or valid JSON missing the {"payload": {...}} envelope
# shape every consumer expects. These must be published DIRECTLY to
# RabbitMQ (bypassing monitoring-adapter, which would never itself produce
# a malformed envelope) -- see send_all.sh's `poison` mode for the exact
# curl commands against the RabbitMQ management API.
# ---------------------------------------------------------------------------
def build_poison_messages():
    return [
        {
            "case": "not_valid_json",
            "queue": "kaiops.context-agent.orchestration-events",
            "expect": "_collect_batch() logs a decode warning and acks+drops it; never occupies a batch slot",
            "raw_body": "{this is not json at all",
        },
        {
            "case": "valid_json_missing_payload_key",
            "queue": "kaiops.context-agent.orchestration-events",
            "expect": "decodes fine, but payload = decoded.get('payload') is None -> acked+dropped silently, no log line at all",
            "raw_body": '{"not_a_payload_key": {"alert": {}, "incident": {}}}',
        },
        {
            "case": "payload_present_but_not_a_dict",
            "queue": "kaiops.context-agent.orchestration-events",
            "expect": "same silent-drop path -- payload is a string/list instead of a dict",
            "raw_body": '{"payload": "this should have been an object"}',
        },
        {
            "case": "payload_dict_but_alert_or_incident_missing",
            "queue": "kaiops.context-agent.orchestration-events",
            "expect": "passes _collect_batch()'s shape check, but handle()'s Alert.model_validate(payload['alert']) raises -- exercises _handle_one()'s retry-then-DLQ path, NOT the silent-drop path",
            "raw_body": '{"payload": {"incident": {}}}',
        },
    ]


def main():
    prometheus = build_prometheus()
    email = build_email()
    jira = build_jira()
    logs_text = build_logs()
    invalid = build_invalid()
    duplicates = build_duplicates()
    poison = build_poison_messages()

    with open(os.path.join(OUT_DIR, "prometheus_alerts.json"), "w") as f:
        json.dump(prometheus, f, indent=2)

    with open(os.path.join(OUT_DIR, "email_alerts.json"), "w") as f:
        json.dump(email, f, indent=2)

    with open(os.path.join(OUT_DIR, "jira_alerts.json"), "w") as f:
        json.dump(jira, f, indent=2)

    with open(os.path.join(OUT_DIR, "log_alerts.jsonl"), "w") as f:
        f.write(logs_text)

    with open(os.path.join(OUT_DIR, "invalid_alerts.json"), "w") as f:
        json.dump(invalid, f, indent=2)

    with open(os.path.join(OUT_DIR, "duplicate_alerts.json"), "w") as f:
        json.dump(duplicates, f, indent=2)

    with open(os.path.join(OUT_DIR, "poison_messages.json"), "w") as f:
        json.dump(poison, f, indent=2)

    print("prometheus alerts:", len(prometheus["alerts"]))
    print("email alerts:", len(email))
    print("jira alerts:", len(jira))
    print("log lines:", len(logs_text.strip().splitlines()))
    print("invalid cases:", len(invalid))
    print("duplicate sets:", len(duplicates) - 1)
    print("poison message cases:", len(poison))


if __name__ == "__main__":
    main()
