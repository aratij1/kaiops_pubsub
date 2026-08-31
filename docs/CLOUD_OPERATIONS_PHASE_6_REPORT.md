# Cloud operations Phase 6 — Azure canary pilot foundation

Date: 2026-08-21 (Asia/Calcutta)

## Outcome

Phase 6 introduces a conformance-tested Azure Container Apps revision adapter boundary while keeping live Azure mutation disabled. The pilot cannot execute unless every independent enablement control is satisfied and a certified managed executor is injected.

## Controls

- `CLOUD_EXECUTION_AZURE_ENABLED` defaults to `false`
- `CLOUD_AZURE_KILL_SWITCH_ENGAGED` defaults to `true`
- `CLOUD_AZURE_CANARY_RESOURCE_IDS` defaults to an empty allowlist
- `CLOUD_AZURE_RATE_LIMIT_PER_MINUTE` defaults to two attempts
- Only `restart_container_app_revision` is declared as a write capability
- Only `restore_container_app_revision` is accepted as rollback
- Connections require a `managed-identity://` or `vault://` reference
- Missing managed executor configuration fails closed

The capability manifest documents the least-privilege Azure Container Apps read, revision-read, and revision-restart permissions required by the pilot.

## Delivered

- Azure pilot connector and injected executor contract
- Structural identity-reference validation
- Kill switch, exact canary allowlist, and process-local rate limiting
- Provider capability and operational-status endpoint
- Authenticated API gateway status route
- Cockpit provider readiness cards
- Conformance tests for kill switch, canary rejection, rate limiting, rollback, and credential-reference validation

## Certification still required

Live enablement requires an external managed executor, Azure sandbox subscription, least-privilege role assignment, canary resource IDs, credential-broker integration, successful dry-run and rollback exercises, audit review, and operator sign-off. None were inferred or enabled by this phase.

## Verification

- Python compilation: passed
- Azure and cloud operations conformance tests: 9 passed
- Frontend typecheck: passed
- Focused frontend tests: 8 passed

## Recommended Phase 7

Build the external Azure managed executor in a sandbox, add signed request/result envelopes and durable distributed rate limiting, run destructive canary and rollback drills, export provider SLO metrics, and produce a formal enablement checklist. Keep the production kill switch engaged until certification is complete.
