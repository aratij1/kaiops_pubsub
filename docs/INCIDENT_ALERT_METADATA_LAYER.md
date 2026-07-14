# Incident And Alert Metadata Layer (Bus Agnostic)

This document defines a production-ready metadata layer for incident and alert management in KaiMS.

It is transport-neutral and works with either Kafka or RabbitMQ.

## Goals

- Standardize metadata across all services and agents.
- Preserve full lineage and auditability.
- Support high-volume querying and analytics.
- Keep event transport independent from domain metadata.

## Canonical Event Envelope (v1)

Each published event should use this top-level shape.

```json
{
  "event_id": "uuid",
  "event_type": "incident.workflow.selected",
  "schema_version": "1.0",
  "produced_at": "2026-07-08T10:20:30Z",
  "identity": {
    "incident_id": "uuid",
    "alert_id": "uuid",
    "trace_id": "trace-123",
    "correlation_id": "corr-abc",
    "causation_id": "event-xyz",
    "parent_event_id": "uuid"
  },
  "scope": {
    "tenant_id": "default",
    "service": "payments-api",
    "environment": "prod",
    "region": "ap-south-1",
    "team": "sre-payments"
  },
  "state": {
    "severity": "high",
    "status": "investigating",
    "owner": "oncall-payments"
  },
  "policy": {
    "risk_tier": "high",
    "execution_mode": "human-approval",
    "requires_approval": true,
    "policy_version": "policy-v1",
    "policy_reason": "severity in mandatory approval set"
  },
  "ai": {
    "confidence": 0.82,
    "model_provider": "openai",
    "model_name": "gpt-5",
    "fallback_reason": "none"
  },
  "transport": {
    "provider": "rabbitmq",
    "channel": "orchestration-events",
    "partition": null,
    "offset": null,
    "delivery_tag": "12345"
  },
  "idempotency": {
    "idempotency_key": "incident.workflow.selected:uuid",
    "fingerprint": "hash"
  },
  "payload": {}
}
```

## Required Metadata Domains

1. Identity and lineage
- `incident_id`, `alert_id`, `trace_id`, `correlation_id`, `causation_id`, `parent_event_id`

2. Scope
- `tenant_id`, `service`, `environment`, `region`, `team`

3. Operational state
- `severity`, `status`, `owner`, `created_at`, `updated_at`

4. Policy and governance
- `risk_tier`, `execution_mode`, `requires_approval`, `policy_version`, `policy_reason`

5. AI decision metadata
- `confidence`, `model_provider`, `model_name`, `fallback_reason`

6. Transport metadata (bus neutral)
- `provider` (`kafka` or `rabbitmq`), `channel` (topic/queue/routing channel)
- `partition`, `offset` for Kafka when available
- `delivery_tag` for RabbitMQ when available

7. Idempotency and dedup
- `idempotency_key`, `fingerprint`

## Kafka vs RabbitMQ Mapping

- Kafka:
  - `transport.provider = kafka`
  - `transport.channel = topic`
  - `transport.partition` and `transport.offset` should be populated
  - ordering key should be `service` or `incident_id`

- RabbitMQ:
  - `transport.provider = rabbitmq`
  - `transport.channel = exchange/routing-topic semantic channel`
  - `transport.partition` and `transport.offset` remain null
  - `transport.delivery_tag` can be populated by consumers

## Storage Model

Use two layers:

1. Event store (append-only)
- One row per state transition or agent step.
- Never update historical event rows.

2. Current projection table
- One row per incident for fast dashboard/API reads.
- Updated by projection workers from the event store.

For existing databases, apply [backend/database/migrations/20260708_incident_projection_backfill.sql](backend/database/migrations/20260708_incident_projection_backfill.sql) once to seed projections from historical `incidents` rows.

## Scalability Guardrails

- Partition event data by time and tenant/environment where needed.
- Index by `incident_id`, `alert_id`, `trace_id`, `service`, `status`, `created_at`.
- Keep high-cardinality free-form labels in `payload` JSON and avoid global indexes on them.
- Apply TTL/retention by tier (hot/warm/cold).
- Enforce schema-version checks at ingest boundaries.

## Existing KaiMS Alignment

KaiMS already has:

- Dynamic message bus routing and provider tracking in orchestrator decisions.
- Policy metadata fields (`risk_tier`, `execution_mode`, `policy_version`, `policy_reason`).
- Agent work item tracking for timeline/status.

This spec formalizes those fields into a stable cross-service metadata contract.
