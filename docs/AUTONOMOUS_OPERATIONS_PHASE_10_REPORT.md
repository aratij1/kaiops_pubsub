# Autonomous Operations Phase 10 — Durable Draft Review Delivery

Date: 2026-08-21 (Asia/Calcutta)

## Outcome

Phase 10 completes the extended autonomous-operations roadmap with a durable, idempotent workflow
for creating review-only pull requests. The workflow remains provider-neutral and has no live SCM
connection, merge, deployment, branch-deletion, or patch-application capability.

## Delivered

- A dedicated `draft_pull_request_outbox` table and additive migration.
- Deterministic idempotency binding across tenant, proposal, and provider connection.
- Bounded delivery batches and configurable retry limits capped at five attempts.
- Exponential retry delays capped at five minutes, followed by a terminal dead-letter state.
- Durable provider response metadata for reconciliation by tenant and idempotency key.
- Audit records for successful creation, scheduled retries, and dead-letter transitions.
- Audit payload redaction: proposal diffs, authorization details, provenance, and provider errors are
  excluded from audit records.
- A workflow processor that reuses all Phase 9 authorization, provenance, tenant, repository, exact
  revision, and draft-only checks before provider invocation.

## Safety properties

- Duplicate enqueue requests return the existing job and do not create a second provider call.
- An idempotency key cannot be rebound to a different tenant or proposal.
- Terminal jobs are never selected for another delivery attempt.
- Reconciliation cannot read across tenant boundaries.
- Retry exhaustion is explicit and auditable.
- The provider protocol exposes draft creation only; no merge or deployment operation exists.
- No live provider adapter or worker endpoint is enabled by default.

## Migration

Apply `20260901_draft_pr_outbox.sql` before enabling a separately configured worker.

## Roadmap status

The extended ten-phase implementation is complete. Production enablement should be handled as a
separate release-readiness track covering an explicit SCM adapter, secret management, worker
leasing/concurrency, operational dashboards, migration rollout, and controlled canary validation.
