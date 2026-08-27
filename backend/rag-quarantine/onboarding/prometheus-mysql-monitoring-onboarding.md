kind: onboarding
title: Prometheus and MySQL monitoring onboarding readiness
tenant_scope: default
services: api-gateway, monitoring-adapter, mysql
owner_team: platform-ops
source_system: internal
source_ref: ONBOARDING-PROMETHEUS-MYSQL-LANDING-PAD
review_status: pending_review
corpus_classification: GENERATED_UNVERIFIED
content_version: 2
created_at: 2026-07-10T00:00:00Z
updated_at: 2026-08-28T00:00:00Z
last_reviewed: 2026-07-10T00:00:00Z
content_checksum: sha256:c2e661adaaff65a506b70328b376d2e2dd01dd1e1e7c381cc7bd50dd847e44bd

# Prometheus and MySQL monitoring onboarding readiness

## Purpose

Use this checklist to review the Prometheus-to-KaiMS alert ingestion path for
the `default` tenant. It is a review candidate, not evidence that a particular
deployment is currently connected or healthy.

## Repository-backed contract

- KaiMS services expose a Prometheus metrics endpoint at `/metrics` through the
  shared service setup.
- The monitoring adapter accepts Alertmanager payloads at
  `POST /alerts/alertmanager`.
- The canonical automatic alert channel is `raw-alerts`.
- The API gateway and monitoring adapter also expose
  `POST /api/v1/alerts/prometheus` for the provider-specific ingestion contract.
- The repository's default internal Prometheus URL is
  `http://prometheus:9090`; a deployed environment may override it.

These statements describe the checked-in application contract. Operators must
verify the deployed endpoints, authentication, transport provider, and routing
before accepting onboarding.

## Ownership to verify

- Proposed primary owner: `platform-ops`.
- Required reviewers: observability owner and database owner.
- Required escalation destination: the environment-specific SRE/on-call route.

The proposed owner and source reference come from the quarantined predecessor
and remain unverified until an accountable reviewer confirms them.

## Connectivity review

- [ ] Confirm the intended tenant ID and replace `default` if necessary.
- [ ] Confirm Prometheus reaches each approved service metrics endpoint.
- [ ] Confirm MySQL exporter exists, has least-privilege database access, and is
      healthy in the target environment.
- [ ] Confirm Alertmanager sends to the deployed monitoring-adapter base URL plus
      `/alerts/alertmanager` using the required authentication or signature.
- [ ] Confirm the configured event transport exposes the canonical `raw-alerts`
      channel to its intended consumers.
- [ ] Confirm retries, dead-letter handling, and observability are configured for
      failed alert publication.

## Safe validation

1. Capture current health and configuration without changing production state.
2. Submit a uniquely labelled synthetic warning alert through an approved test
   path; do not reuse a live production incident identifier.
3. Verify one accepted ingestion response and preserve its trace identifier.
4. Verify exactly one canonical alert and correlated incident are persisted for
   the test signal.
5. Verify the incident detail route displays source identity, linked evidence,
   and lifecycle state consistently.
6. Verify the synthetic signal resolves and does not create an executable
   remediation without the applicable policy and human approval.
7. Remove or expire test-only routing and data according to the environment's
   retention policy.

## Acceptance evidence

The reviewer must attach or reference:

- Prometheus target-health output for the approved service targets;
- MySQL exporter health and least-privilege verification;
- Alertmanager delivery evidence with secret values removed;
- the KaiMS trace ID, alert ID, and incident ID for the synthetic test;
- proof that duplicate delivery is handled idempotently;
- owner acceptance, escalation route, and review date.

## Failure and rollback

- If the webhook is rejected, stop the test and correct authentication or route
  configuration before retrying.
- If duplicate incidents or unexpected remediation are observed, disable the
  new alert route and preserve trace/audit data for investigation.
- Revert only the onboarding-specific routing change; do not disable shared
  monitoring or delete production incident history.
- Escalate immediately if the test exposes credentials, crosses tenant scope, or
  affects live alert delivery.

## Approval gate

This document must remain quarantined while `review_status` is
`pending_review`. Promotion requires verified tenant scope, completed acceptance
evidence, accountable reviewer identities and timestamps, an updated checksum,
and the classification required by the production RAG governance contract.
