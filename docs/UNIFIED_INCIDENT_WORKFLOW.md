# Unified Incident Discovery and Resolution

## Runtime flow

```text
Logs / Email / Prometheus / Datadog / New Relic / Grafana / Jira
  -> source adapters
  -> durable landing pad
  -> raw-alerts
  -> normalize + deduplicate + correlate
  -> Discovery Agent
  -> deterministic severity policy
  -> create or update qualified Jira incident
  -> Jira webhook
  -> Context Agent
  -> Resolution Agent
  -> policy and approval
  -> remediation
  -> recovery validation
  -> update and close Jira
```

KaiOps uses a two-stage admission model. Lightweight deterministic rules suppress
noise before expensive reasoning. Qualified events then receive AI discovery and
deterministic severity validation. This preserves the existing low-latency adapter
architecture while ensuring that Jira contains structured, explained incident
decisions rather than raw log lines.

## System ownership

- The alert landing pad owns immutable source payloads and replay/audit references.
- `raw-alerts` transports normalized `RawAlert` events; retry and dead-letter
  queues provide failure isolation.
- Alert Intelligence owns deduplication, correlation and `IncidentCandidate`.
- The deterministic policy owns final severity. An LLM recommendation cannot
  bypass this policy.
- Jira is the golden record only for qualified incidents. A structured Jira issue
  property contains the candidate, policy decision and KaiOps ownership markers.
- Context, resolution, approval, remediation and validation services append their
  evidence and decisions to the incident and audit stream.

## Identity and idempotency

Every boundary preserves `event_id`, `source_event_id`, `trace_id`,
`incident_id`, `jira_key`, and an idempotency key. A stable fingerprint groups
repeated signals. Before issue creation, KaiOps checks both its local ticket link
and the matching fingerprint label in Jira. Agent updates use an idempotent Jira
issue property.

KaiOps writes `managed_by_kaiops`, `kaiops_incident_id`, `event_origin=kaiops`,
and the `[kaiops-managed-update]` comment marker. Jira webhooks carrying that
managed comment are acknowledged but not republished, preventing input/output
loops. Human or external Jira changes remain valid input events.

## Qualification and evidence

Only recurring or high-value actionable conditions enter Jira. Suppressed and
informational observations remain visible in the live log stream and landing-pad
audit records. Candidates retain source evidence URIs, confidence, model identity,
reasoning, similar incident references, initial hypothesis, and business and
technical impact.

## Closure invariant

An incident can close only after remediation has recorded its action and approver,
and validation confirms recovery using health checks plus the relevant logs and
metrics. Failed validation returns the incident to investigation and preserves all
attempt evidence.
