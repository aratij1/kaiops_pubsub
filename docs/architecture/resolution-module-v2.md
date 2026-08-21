# KaiMS Resolution Module v2

The resolution path is an evidence-driven, durable workflow. It does not turn a single model response into an executable command.

## Runtime flow

1. Compile typed, immutable evidence from logs, telemetry, topology, code/change, data, tickets, and runbooks.
2. Maintain three to five falsifiable hypotheses and request the next highest-value read-only query.
3. Stop as conclusive only when deterministic confidence clears the threshold with independent corroboration; otherwise return `inconclusive`.
4. Select a versioned approved runbook and bind validated parameters, target, validation, rollback, connector, fingerprint, and idempotency key.
5. Apply deterministic policy. High/critical, production database, ambiguous, contradictory, or incomplete cases cannot use hands-off execution.
6. Persist immutable state transitions and execute through Temporal with bounded retries and target locking.
7. Validate recovery independently from executor success. A failed validation invokes only the rollback in the approved plan; unavailable or failed rollback escalates for manual intervention.
8. Close only after alert, availability, error-rate, latency, dependency, critical-alert, and stability-window checks pass. Diagnostic-only incidents may close as diagnostics, but never claim recovery.
9. Promote outcomes to reusable knowledge only after explicit human review and a successful independently validated result.

HOTL remains disabled by default (`RESOLUTION_HOTL_ENABLED=false`). Enabling it does not bypass the policy constraints, approved runbook requirement, immutable execution contract, rollback, audit trail, or independent closure validation.

## Durable states

`evidence_pending -> evidence_ready -> hypotheses_ready -> plan_selected -> policy_checked -> awaiting_approval|ready_to_execute -> executing -> validating -> resolved|rolled_back|escalated`

Transitions use deterministic idempotency keys so replayed events cannot create duplicate logical progress.
