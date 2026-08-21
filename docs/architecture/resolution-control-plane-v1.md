# Resolution Control Plane v1

## Decision ownership

`resolution-agent` is the only component that creates `kaims.resolution-control.v1`.
Downstream services consume this persisted decision and must not independently
infer whether a plan is watch-only, approvable, or executable.

| Disposition | Approval queue | Execution | Closure |
| --- | --- | --- | --- |
| `watch_only` | No | No | Automatic, with observation evidence |
| `investigate` | No | No | Manual investigation or escalation |
| `approval_required` | Yes | Only after approval of the immutable fingerprint | After validation |
| `execution_ready` | No | Policy-authorized durable workflow | After validation |

Contradictory inputs fail closed. In particular, a watch-only disposition with
mutating commands becomes `investigate` with a control-contract conflict.

## Durable path

1. Resolve evidence into a catalog-backed immutable execution plan.
2. Produce and persist one versioned control decision and lifecycle.
3. Route only `approval_required` decisions into the approval queue.
4. Bind approval to the plan fingerprint and an idempotency key.
5. Execute mutations through a durable workflow activity.
6. Validate recovery independently from executor success.
7. Close only validated recovery or explicit watch-only observation.

The implementation uses a guarded transition reducer, not independent status
derivation in each service. Remediation owns attempt outcomes through
`validating`; closure alone owns `recovered` and `closed`. The current envelope
is selected by lifecycle version rather than by whichever nested payload is
encountered first.

Business-state changes and closure broker events use the transactional outbox
in `20260819_resolution_outbox.sql`. This removes the failure window where an
action/projection was committed but its closure event was lost. A retry-safe
dispatcher preserves the event ID across delivery attempts.

Every event carries incident, recommendation, trace, correlation, causation,
plan fingerprint, lifecycle version, and control schema identifiers. Policy
decisions must record a decision ID, policy revision, result, and masked input.

## Migration constraints

- Existing `kaims.resolution-lifecycle.v4` events remain readable.
- Consumers prefer `kaims.resolution-control.v1` and use conservative legacy
  derivation only for events created before the control contract existed.
- No database rewrite is required for this slice because both contracts are
  stored in existing JSON event/projection payloads.
- The next migration should extract the control contract into a typed API/event
  model shared by Python and TypeScript, then remove legacy UI inference.

## Design references

- Temporal durable execution and activity retry semantics: https://docs.temporal.io/
- AWS safe retry/idempotent API guidance: https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/
- OPA policy distribution and auditable decision logs: https://www.openpolicyagent.org/docs/management-introduction
- OpenTelemetry messaging context propagation: https://opentelemetry.io/docs/specs/semconv/messaging/messaging-spans/
