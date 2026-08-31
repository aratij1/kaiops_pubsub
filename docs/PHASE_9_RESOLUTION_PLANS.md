# Phase 9 Resolution Plans

The Resolution Agent now exposes `kaims.remediation-plan.v1` as its canonical
remediation recommendation. The contract selects a registered capability and
contains target identity, evidence, blast radius, parameters, preconditions,
validation, rollback, risk, and an autonomy recommendation. It cannot contain
commands, scripts, shell, SQL, queries, or arbitrary URLs in capability
parameters.

## Fail-closed rules

- Unknown capabilities and connector/capability mismatches are invalid.
- A target is verified only when the execution catalog's blast-radius binding
  agrees with an affected resource and the target is a stable Digital Twin or
  provider resource identifier (`dt://`, `urn:`, `arn:`, `k8s://`, or Azure
  `/subscriptions/...`). Display names and inferred service names are not
  execution identities.
- Missing evidence, validation, required parameters, or exact rollback binding
  blocks validity.
- `AUTO_EXECUTE` additionally requires autonomous registry trust, no approval,
  confidence of at least 0.90, a verified target, and known blast radius.
- Legacy execution plans remain compatibility projections. An action without a
  single explicit registry binding produces `remediation_plan_status` with a
  blocking reason and no typed remediation plan.

The initial capability catalog intentionally grants no autonomous trust. Typed
plans can therefore be observed, recommended, or routed to HITL, but cannot
silently activate production autonomy.
