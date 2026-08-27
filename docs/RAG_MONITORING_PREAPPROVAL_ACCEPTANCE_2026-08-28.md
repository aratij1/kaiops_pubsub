# Monitoring onboarding pre-approval acceptance

## Decision

The quarantined Prometheus/MySQL onboarding candidate is **not ready for
approval or production retrieval**. Local validation confirmed the core
telemetry, safe ingestion, authenticated incident, evidence/RCA, governed-plan,
and browser-navigation contracts. Credentialed staging evidence and accountable
approval remain outstanding, and the `raw-alerts` dead-letter queue is not
empty.

This record contains local development evidence only. It is not production or
staging evidence and does not authorize promotion.

## Environment

- Validation date: 2026-08-28 (Asia/Calcutta workstation date).
- Tenant label: `default`.
- Environment label used by the synthetic signal: `local`.
- Candidate:
  `backend/rag-quarantine/onboarding/prometheus-mysql-monitoring-onboarding.md`.
- Synthetic validation ID: `rag-onboarding-20260828-0210`.

## Passed checks

| Check | Result | Evidence |
| --- | --- | --- |
| Prometheus readiness | Pass | `GET http://localhost:9090/-/ready` returned HTTP 200. |
| Alertmanager readiness | Pass | `GET http://localhost:9093/-/ready` returned HTTP 200. |
| MySQL exporter endpoint | Pass | `GET http://localhost:9104/metrics` returned HTTP 200 with metric content. |
| Monitoring adapter readiness | Pass | `/healthz` and `/readyz` returned HTTP 200. |
| API gateway readiness | Pass | `/healthz` and `/readyz` returned HTTP 200. |
| Service metrics | Pass | Monitoring adapter and API gateway `/metrics` returned HTTP 200. |
| Prometheus targets | Pass | `mysql-exporter`, `kaiops-monitoring-adapter`, and `kaiops-api-gateway` targets reported `up`; the other inspected KaiMS service targets also reported `up`. |
| Alertmanager routing | Pass | Both checked-in live receivers targeted `http://monitoring-adapter:8000/alerts/alertmanager` with resolved notifications enabled. |
| Active raw-alert queue | Pass | `kaiops.alert-intelligence.raw-alerts` had zero ready and zero unacknowledged messages with eight consumers at inspection time. |
| Synthetic firing delivery | Pass | Webhook response reported one received, one ingested, and one queued alert. |
| Synthetic alert persistence | Pass | Alert ID `86ffe3d4-bdc3-4e29-86cb-7c52efb69dd8` was returned and could be read from the monitoring adapter. |
| Safety behavior | Pass | The signal was classified as non-actionable noise; processing stopped, no incident was linked, confidence remained 0%, and the fallback decision required approval with supervised execution. |
| Synthetic resolution | Pass | The resolved webhook reported one observed resolution and `investigation_started=false`. |
| Controlled incident admission | Pass | The canonical lifecycle probe produced alert `99879c05-e530-4621-9da9-c08b200a8c71` and exactly one incident `87feceaf-0f73-466f-a25b-a5172f621561`. |
| Context collection | Pass | The incident collected 13 evidence records from code, logs, and topology; context was complete and identified as `realtime_collection` with snapshot quality `0.7256`. |
| RCA persistence | Pass | Recommendation `f4e7fd49-31d8-55a5-b1ba-d33e35625e2e` was persisted and present in the UI-context projection. |
| Governed execution plan | Pass | The diagnostic plan was not execution-ready; execution remained blocked for missing telemetry/traces, inconclusive investigation, and missing executable rollback. No approval or execution was submitted. |
| Authenticated alert-detail browser journey | Pass | Playwright opened a live alert in the details cockpit with no page-level failure. |
| Authenticated inbox deep link | Pass | Playwright followed a Live Alerts action to the canonical `/incidents/{id}` route and rendered Unified Inbox. |

## Open findings

### 1. Low-information safety probe did not create an incident

The candidate checklist requires exactly one canonical alert and correlated
incident for an approved incident simulation. The warning probe produced one
alert but no incident. Its processed result used `alert-only-fallback`, with a
null incident ID and a recommendation explicitly stating that no linked
incident projection exists.

This is safe and appropriate for the deliberately low-information probe. The
separate repository-provided lifecycle probe subsequently validated the
incident path with exactly one incident and without enabling remediation.

### 2. Dead-letter queue is not empty

At inspection time, `kaiops.alert-intelligence.raw-alerts.dlq` contained two
ready messages. A requeue-safe inspection showed that both are valid
Prometheus `KaiOpsHighLatencyP95` alerts for `api-gateway`, failed on 2026-08-27
after four attempts, and carry the generic terminal error `handler_failed`.
Their alert IDs are `cf4c2002-f885-4d9b-a961-0b994576405c` and
`56ea0254-78a7-445b-af1d-591b75cf20e0`.

The historical alert-intelligence logs had rotated, and no matching durable
audit record exposed the original exception. The messages were requeued by the
inspection command and remain unmodified in the DLQ. Their disposition is
**retain, do not replay** until an operator can establish the failed dependency
or reproduce the original handler failure. Blind replay could create stale
incidents or downstream side effects.

### 3. Gateway processed-result read requires authentication as designed

The direct monitoring-adapter tenant-scoped processed-result read succeeded,
while the equivalent API-gateway request without credentials returned HTTP
401. The subsequent authenticated lifecycle and browser tests passed, confirming
that an authorized operator can open records through the supported public UI
and API routes.

### 4. Production-specific controls remain unverified

The local checks do not establish production authentication/signature policy,
MySQL exporter's least-privilege database grants, tenant isolation, external
alert delivery, production escalation ownership, or production rollback.

## Required next actions

1. Preserve the two retained dead-letter messages until the original handler
   failure can be reproduced or the responsible owner approves replay.
2. Repeat the connectivity, tenant-isolation, authentication/signature, and
   least-privilege checks in credentialed staging.
3. Run the live RCA browser assertion against the controlled alert if the
   staging policy expects a conclusive causal statement; the local diagnostic
   result correctly remained inconclusive because telemetry and traces were
   missing.
4. Have the observability owner, database owner, and RAG governance approver
   review the candidate and this evidence before any metadata is changed to
   `approved` or any file is moved under `backend/rag`.

## Safety note

No remediation was executed. No quarantined document was activated. The test
signal was explicitly resolved after observation, and existing dead-letter
messages were left untouched.
