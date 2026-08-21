# Cloud operations Phase 5 — provider governance and operational recovery

Date: 2026-08-21 (Asia/Calcutta)

## Outcome

Phase 5 adds the governance boundary required before enabling provider execution: explicit adapter flags, scoped execution policies, maintenance windows, short-lived credential sessions, expired-lease recovery, and durable compensation evidence.

## Delivered

- Independent execution feature flags for simulator, AWS, Azure, and GCP
- AWS, Azure, and GCP execution disabled by default
- Tenant/project/environment policy records with provider, action, risk, rollback, and window constraints
- Time-bounded maintenance windows
- Internal credential-reference brokerage with short expiry and immediate revocation
- No credential value or reference returned through execution APIs
- Tenant-scoped expired-lease reconciliation
- Ordered compensation evidence for each rollback step
- Administrator gateway routes and cockpit governance controls
- MySQL migration for governance, windows, credential sessions, and compensation

## Fail-closed behavior

Execution is rejected when the provider flag is disabled, no scoped policy exists, provider/action/risk violates policy, rollback is missing, no required maintenance window is active, no validated write-capable connection exists, approval is absent, or the latest simulation is not passing.

Only the simulator adapter has an enabled conformance implementation. Registering a real provider connection does not enable mutation.

## Verification

- Python compilation: passed
- Focused cloud operations tests: 7 passed
- Frontend typecheck: passed
- Focused frontend tests: 8 passed

## Database changes

Migration `20260828_cloud_governance_phase5.sql` creates:

- `cloud_execution_policies`
- `cloud_maintenance_windows`
- `cloud_credential_sessions`
- `cloud_compensations`

## Recommended Phase 6

Implement one real provider pilot with a least-privilege role, external secret broker, provider-specific conformance suite, canary scope, rate limits, kill switch, and operational dashboards. Azure is the natural first pilot for this deployment, but its mutation flag must remain disabled until credentials and sandbox infrastructure are explicitly supplied and certified.
