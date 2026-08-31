# Context Intelligence v2

## Goal

Give Resolution exactly one bounded, auditable context package containing
current facts, explicit gaps and immutable provenance. Context collection must
not invent connector data, repeat expensive discovery without cause, or reuse
evidence across a changed execution target.

## Control flow

```text
orchestration event
  -> validate tenant + service + target scope
  -> acquire alert-family single-flight lease
  -> inspect cached context family
      -> scope, freshness, provenance, relevance and conflict gates pass
          -> reuse context; independently gate prior resolution
      -> any gate fails
          -> adaptive connector plan
          -> bounded parallel collection
          -> normalize + redact + deduplicate evidence
          -> score context package
  -> atomically persist incident event + immutable snapshot + outbox row
  -> publish deterministic context event
  -> Resolution consumes the exact persisted package
```

## Correctness rules

1. Connector adapters may return only source data, configured API results or
   normalized alert metadata. Empty is valid; synthetic examples are not.
2. Alert-family identity is stable across pod churn. Subject identity includes
   application, project, cluster, namespace, deployment, version and resource
   identifiers. A changed subject triggers collection rather than blind reuse.
3. Context and remediation reuse are independent decisions. A sound topology
   snapshot can be reused without trusting a weak historical RCA.
4. Every evidence row has a deterministic identifier, observed/retrieved time,
   source-specific TTL, relevance, confidence, URI, content digest, redaction
   flag and W3C PROV-inspired entity/activity/agent metadata.
5. Retrieval time is never silently treated as a provider observation time.
   Missing timestamps are marked as inferred and receive reduced freshness and
   provenance credit for time-sensitive sources.
6. RAG search is exploratory, but admission to an incident package is strict:
   service-tagged knowledge must clear a minimum match score; untagged documents
   need materially stronger semantic and metadata evidence. Accepted RAG rows
   are labeled `historical_knowledge`, never current observations.
7. Logs, metrics and database observations expire after five minutes;
   deployments/changes after fifteen; topology/tickets after thirty; source
   code after six hours; reviewed knowledge after one day.
8. High/critical alerts require identity, an operational signal, and causal or
   actionable evidence. Missing or stale required evidence is explicit and
   makes the package non-reusable.
9. Simultaneous requests for one tenant/alert family are coalesced with an
   in-process lock and a MySQL named lease. The waiter rechecks the durable
   cache after acquiring the lease.
10. Context event IDs and snapshot IDs are deterministic. Broker failure leaves
   a committed outbox row for retry; redelivery cannot create a second snapshot
   or downstream event.

## Storage and APIs

- `context_knowledge` is the mutable cache-aside family index.
- `context_snapshots` is the immutable record of the package consumed by each
  incident and contains both subject and content fingerprints.
- `resolution_outbox` is the existing generic transactional event handoff.
- `GET /context/strategy` exposes the active quality and freshness policy.
- `GET /context/snapshots/{incident_id}` returns the latest immutable package.

The implementation follows source-specific freshness rather than an infinite
global cache, OpenTelemetry-style correlation of operational evidence, and a
minimal W3C PROV entity/activity/agent chain. See the official
[Azure cache-aside guidance](https://learn.microsoft.com/en-us/azure/architecture/patterns/cache-aside),
[OpenTelemetry logging specification](https://opentelemetry.io/docs/specs/otel/logs/),
[W3C PROV-O recommendation](https://www.w3.org/TR/prov-o/), and
[RFC 9111 freshness model](https://www.rfc-editor.org/rfc/rfc9111.html).

## Rollout

1. Apply `20260819_context_snapshots_v2.sql`.
2. Deploy context-agent, then API gateway.
3. Verify `/readyz`, `/context/strategy`, context quality metrics and outbox
   backlog before increasing worker replicas.
4. Keep `CONTEXT_STRATEGY=auto`. Use `realtime` only for controlled forced
   refresh and `historical` for read-only investigations.
