# Context processing strategies

KaiOps supports three context strategies. `auto` is the default.

## Auto (default)

Continuous mode uses a durable cache-aside workflow:

1. Build a tenant-scoped alert-type signature from alert source, alert name,
   service, environment, category and alert family. Volatile deployment labels
   such as application, project and namespace do not create a new alert type.
2. Look for a complete, resolution-qualified snapshot in `context_knowledge`.
3. On a hit, attach the new alert and incident IDs to the stored context and
   continue to RCA without rerunning every discovery connector.
4. On a new type, unqualified result or invalid snapshot, run complete context discovery
   and persist the resulting context for the next occurrence.
5. When resolution completes, attach the RCA, impact, recommended action,
   confidence and evidence metadata to the same knowledge record. A recurring
   alert receives this as `metadata.prior_resolution`.

Every returned context includes:

- `metadata.context_strategy`
- `metadata.context_reused`
- `metadata.context_knowledge_id`
- original alert/incident provenance when reused
- collection time, reuse count and deterministic signature

Approved knowledge does not expire by time by default. Set a positive
`CONTEXT_KNOWLEDGE_TTL_SECONDS` only when topology policy requires forced
refreshes. Completeness and RCA quality gates still trigger refreshes.

## Immediate

Immediate mode always runs complete context discovery. It still refreshes the
durable knowledge snapshot, allowing a later alert in Continuous mode to reuse
the newly collected evidence.

Set Immediate mode globally with:

```text
CONTEXT_STRATEGY=immediate
```

Or override it for one orchestration event:

```json
{
  "decision": {
    "context_strategy": "immediate"
  }
}
```

Direct `POST /collect` callers can set top-level `context_strategy` to
`immediate` or `continuous`.

## Safety and invalidation

- Knowledge never crosses tenant, service or environment boundaries.
- An exact alert type within the tenant/service/environment boundary is
  required; fuzzy matching is not used for bypassing discovery.
- Unqualified, incomplete or malformed snapshots trigger fresh discovery.
- Changes to deployment, live metrics and severity remain represented by the
  new alert. Use Immediate mode when current infrastructure evidence is
  mandatory, such as after a major deployment or topology change.
- Apply `backend/database/migrations/20260804_context_knowledge_strategy.sql`
  before enabling this release in an existing environment.

`GET /context/strategy` through the API gateway reports the effective default,
supported modes, TTL and matching scope.

## Docker telemetry monitoring

The Docker Compose stack includes Prometheus, Alertmanager and a provisioned
Grafana dashboard for this workflow.

- Grafana: `http://localhost:3000`
- Prometheus: `http://localhost:9090`
- Dashboard: **KaiOps / KaiOps Context Knowledge Telemetry**
- Default local Grafana credentials: `admin` / `admin`; set
  `GRAFANA_ADMIN_USER` and `GRAFANA_ADMIN_PASSWORD` outside local development.

The dashboard monitors cache hit ratio, request outcomes, p95 fresh/reused
latency, repository operations, RCA attachment and context/resolution target
health. Prometheus alerts cover discovery failures, repository errors, low hit
ratio, slow fresh/reused paths and missing RCA knowledge records.

Relevant metrics:

- `kaiops_context_strategy_requests_total`
- `kaiops_context_strategy_duration_seconds`
- `kaiops_context_knowledge_operations_total`
- `kaiops_context_knowledge_reuse_count`

Start or refresh the monitoring stack with:

```text
docker compose up -d context-agent resolution-agent prometheus grafana
```
