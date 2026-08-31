# Context processing strategies

KaiOps supports three context strategies. `auto` is the default.

## Auto (default)

Continuous mode uses a durable cache-aside workflow:

1. Build a tenant-scoped alert-family signature and a separate subject
   fingerprint containing application, project, cluster, namespace,
   deployment/version and resource identity.
2. Look for a snapshot in `context_knowledge` whose subject, per-source
   freshness, provenance, relevance, completeness and conflict gates pass.
3. On a hit, attach the new alert and incident IDs and continue without
   rerunning discovery. Previous resolution reuse is evaluated independently.
4. On a new family or failed gate, use the alert semantics to select the
   smallest useful connector set, run it in parallel within a global budget,
   and persist the result.
5. Normalize every evidence row into `kaiops.context.v2`, then write an
   immutable per-incident record to `context_snapshots`.
6. When resolution completes, attach the RCA, impact, recommended action,
   confidence and evidence metadata to the same knowledge record. A recurring
   alert receives this as `metadata.prior_resolution`.

Every returned context includes:

- `metadata.context_strategy`
- `metadata.context_reused`
- `metadata.context_knowledge_id`
- original alert/incident provenance when reused
- collection time, reuse count and deterministic signature

The outer snapshot lifetime defaults to one hour. Operational evidence has
shorter source-specific TTLs, so a cached package can be refreshed even while
reviewed runbook knowledge remains valid.

## Immediate

Immediate mode forces a fresh collection but still uses the alert-aware source
plan. It bypasses cache reuse; it does not query unrelated evidence systems.
The resulting governed package refreshes durable knowledge so a later alert in
Auto mode can reuse it when every scope and quality gate still passes.

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

- Knowledge never crosses tenant, service, environment or subject boundaries.
- An exact alert type within the tenant/service/environment boundary is
  required; fuzzy matching is not used for bypassing discovery.
- Unqualified, incomplete or malformed snapshots trigger fresh discovery.
- Deployment, namespace, cluster, project or resource changes invalidate blind
  reuse. Ephemeral pod names do not invalidate otherwise identical context.
- Empty connectors remain explicit `no_data`; they never emit demonstration
  facts or fabricated citations.
- Apply `backend/database/migrations/20260804_context_knowledge_strategy.sql`
  and `backend/database/migrations/20260819_context_snapshots_v2.sql` before
  enabling this release in an existing environment.

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
- `kaiops_context_quality_score`
- `kaiops_context_reuse_decisions_total`
- `kaiops_context_source_results_total`

Start or refresh the monitoring stack with:

```text
docker compose up -d context-agent resolution-agent prometheus grafana
```
