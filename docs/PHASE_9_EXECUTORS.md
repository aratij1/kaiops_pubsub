# Phase 9 Governed Executors

Milestone 7 introduces deterministic connector-control-plane executors for
Kubernetes, Ansible, Terraform, database diagnostics, and custom APIs. The
existing governed Jenkins executor is retained. Each executor implements
`dry_run`, `precheck`, `execute`, `validate`, and `rollback` where the registered
capability supports rollback.

Executors accept only a typed remediation plan, a stable verified Digital Twin
or provider resource ID, an opaque `secret_ref`, and capability parameters that
match the registry. Command-, script-, shell-, query-, and SQL-shaped inputs are
rejected. Requests use fixed capability routes rather than model-generated URLs
or commands.

Operational controls include bounded timeouts, at most three attempts,
exponential retry for transport/5xx failures, an in-process circuit breaker,
idempotent result reuse, and a structured audit record for every result. HTTP
success alone is not treated as remediation validation; the separate
`validate` phase remains mandatory for closure.

## Connection profile requirement

Live execution remains disabled until an onboarded connection profile supplies
an `executor_endpoint` and provider-backed `secret_ref`. Missing configuration
returns the backward-compatible `SKIPPED` result. Connector endpoints must
implement:

`POST /v1/capabilities/{registered_capability}/{phase}`

where phase is `dry_run`, `precheck`, `execute`, `validate`, or `rollback`.

## Rollback

Removal is backward compatible: unset `executor_endpoint` to return to the
previous fail-closed skipped behavior. Read-only database diagnostics explicitly
do not roll back. Mutating capabilities use only their registry-declared rollback
capability; an executor never improvises a recovery command.

## Remaining placeholders

- Production connector control-plane deployments and credentials must still be
  onboarded per environment.
- Jenkins retains its existing specialized implementation and will be migrated
  to the common envelope after compatibility consumers are updated.
- Validation orchestration across telemetry sources is milestone 8.
