# Cloud operations Phase 4 — governed execution and recovery

Date: 2026-08-21 (Asia/Calcutta)

## Outcome

Phase 4 extends immutable Phase 3 plans into a fail-closed execution workflow. Approval is bound to the exact plan checksum, execution is protected by a durable idempotency lease, and every adapter action produces post-action validation evidence. Rollback uses only the action embedded in the approved plan.

## Delivered

- Immutable approval decisions bound to tenant, plan ID, and SHA-256 checksum
- Fresh passing-simulation requirement after approval
- Durable execution leases keyed by the plan checksum
- Duplicate execution response reuse
- Provider adapter contracts for execute, validate, and rollback
- Enabled simulator adapter; real providers continue to fail closed
- Persisted execution, validation, error, and rollback evidence
- Reverse-order rollback orchestration
- Administrator-only API gateway routes
- Cockpit approval, execution, evidence, and rollback controls
- MySQL migration for approval and execution records

## Execution gate order

1. Resolve the tenant-scoped immutable plan.
2. Verify checksum-bound approval when required.
3. Require the latest simulation verdict to be `passed`.
4. Acquire or reuse the durable checksum lease.
5. Resolve exactly one enabled provider adapter for all targets.
6. Execute the approved actions.
7. Run post-action validation and persist evidence.
8. If requested, run only the approved rollback actions in reverse order and validate again.

No model-generated or free-form command is accepted by the execution endpoint.

## Database changes

Migration `20260827_cloud_execution_phase4.sql` creates `cloud_plan_approvals` and `cloud_plan_executions`.

## Verification

- Python compilation: passed
- Focused cloud operations tests: 7 passed
- Frontend typecheck: passed
- Focused frontend unit tests: 8 passed

## Rollback

Remove the Phase 4 routes and cockpit controls, then drop `cloud_plan_executions` followed by `cloud_plan_approvals` if Phase 4 audit data is no longer required. Phase 1–3 connection, discovery, onboarding, plan, and simulation data remain valid.

## Recommended Phase 5

Add real provider adapters behind explicit feature flags, short-lived credential brokerage, lease recovery/watchdogs, policy-as-code evaluation, maintenance windows, and multi-step compensation workflows. Keep each provider disabled until its permissions, dry-run behavior, rollback, and validation contracts pass conformance tests.
