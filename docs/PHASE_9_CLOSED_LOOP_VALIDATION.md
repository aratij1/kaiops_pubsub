# Phase 9 Closed-Loop Validation

Milestone 8 adds the canonical `kaims.validation-plan.v1` and
`kaims.closed-loop-decision.v1` contracts to the existing closure and rollback
workflow.

A validation plan binds every check to the immutable execution target and plan
fingerprint. It supports original alert state, service health, metrics, logs,
traces, SLOs, dependency health, and synthetic probes. At least one original
alert check and one independent recovery check are mandatory. Missing evidence
is never interpreted as success.

The lifecycle states are:

- `EXECUTION_SUCCEEDED_VALIDATION_PENDING`
- `VALIDATION_SUCCEEDED`
- `VALIDATION_FAILED`
- `ROLLED_BACK`
- `ESCALATED`

Only `VALIDATION_SUCCEEDED` authorizes closure. A successful executor response
therefore remains pending until required checks pass for the configured
stability window.

Failed validation selects only a registry-declared rollback capability. After a
successful rollback, KaiMS recollects evidence and requires fresh hypotheses;
rollback is not treated as incident recovery. Missing rollback support triggers
evidence recollection and ultimately HITL escalation. Autonomous validation is
bounded to one through three attempts, with two as the default.

## Backward compatibility and rollback

The previous `kaims.outcome-validation.v1` payload remains available while
consumers migrate. Closure reports now include both the old decision and the new
validation plan/closed-loop decision. Legacy plans without a canonical original
alert validator fail closed and request evidence recollection or HITL.

Disabling production connector execution leaves the validation contract active
but prevents mutation and rollback, preserving the prior fail-closed operating
mode.

## Remaining work

- Production deployments must onboard validator registry entries for every
  required telemetry signal.
- The legacy command-projection rollback endpoint remains for approved v2 plan
  compatibility; typed connector rollback is the target path for new plans.
- Evidence Graph and causal hypothesis regeneration are milestone 9.
