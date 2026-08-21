# KaiOps resolution lifecycle v4

## Decision

RCA, approval, remediation, recovery validation, and closure must exchange one versioned lifecycle envelope. Services may append evidence and attempts, but must not independently reinterpret another service's state.

The authoritative identity is:

`tenant_id + incident_id + recommendation_id + plan_fingerprint`

Approval is valid only for that identity. Every execution attempt and closure report must carry it unchanged.

## Lifecycle states

| State | Owner | Meaning | Permitted next states |
|---|---|---|---|
| `analyzing` | resolution-agent | Evidence and RCA are being assembled. | `diagnostic_only`, `awaiting_approval`, `ready_to_execute` |
| `diagnostic_only` | resolution-agent | No reviewed mutating capability exists. | `closed` by closure after durable diagnostic evidence, or `analyzing` after evidence/catalog change |
| `awaiting_approval` | approval-service | The exact plan fingerprint needs a human decision. | `ready_to_execute`, `rejected`, `analyzing` |
| `ready_to_execute` | approval-service/remediation-engine | Approval or HOTL policy is bound to the current plan. | `executing`, `blocked_retryable` |
| `executing` | remediation-engine | A concrete attempt is active. | `validating`, `failed_retryable`, `failed_terminal`, `rolled_back` |
| `blocked_retryable` | remediation-engine | Automatic execution stopped, but HITL, a new plan, or a new attempt may continue. | `awaiting_approval`, `ready_to_execute`, `analyzing` |
| `validating` | closure-service | Post-checks are running against the executed plan and target. | `recovered`, `failed_retryable`, `rolled_back` |
| `recovered` | closure-service | Required recovery checks passed. | `closed` |
| `rolled_back` | remediation-engine/closure-service | Compensation completed and must be validated. | `validating`, `failed_terminal` |
| `failed_retryable` | owning service | Attempt failed without exhausting governed retry/rollback. | `ready_to_execute`, `executing`, `rolled_back`, `analyzing` |
| `failed_terminal` | owning service | Manual intervention or escalation is required. | `analyzing` only through an explicit operator reopen action |
| `rejected` | approval-service | The current plan was rejected. | `analyzing` |
| `closed` | closure-service | The workflow is terminal and closure evidence is durable. `closure_kind=recovery` requires validated recovery; `closure_kind=diagnostic` records completed analysis without a recovery claim. | none |

`policy-blocked` is an outcome reason, not a lifecycle state. It maps to `blocked_retryable` when human review or replanning is permitted, otherwise `failed_terminal`.

## Resolution envelope

Every lifecycle event carries:

```json
{
  "schema_version": "kaims.resolution-lifecycle.v4",
  "tenant_id": "default",
  "incident_id": "uuid",
  "recommendation_id": "uuid",
  "plan_fingerprint": "sha256:...",
  "state": "awaiting_approval",
  "state_version": 4,
  "reason_code": "human_approval_required",
  "retryable": true,
  "supersedes": {"recommendation_id": "uuid", "plan_fingerprint": "sha256:..."},
  "approval": {"id": null, "decision": "pending", "plan_fingerprint": "sha256:..."},
  "execution": {"attempt": 0, "action_id": null, "status": "not_started"},
  "validation": {"required_checks": [], "results": [], "passed": false},
  "updated_at": "RFC3339 timestamp"
}
```

`state_version` is monotonically increasing per incident. Consumers reject older versions for current-state projection but retain them in audit history.

The shared reducer enforces this graph and the actor allowed on each edge. A
same-state replay is idempotent and does not increment `state_version`.
Mutating commands can supply both `expected_version` and the approved
`plan_fingerprint`; stale or plan-swapped requests fail before dispatch.

## Service responsibilities

### Resolution/RCA

- Produce RCA and the model proposal separately from the governed plan.
- Publish exactly one canonical `execution_plan` with a fingerprint.
- Never label a catalog-ready plan diagnostic-only because the model proposal was diagnostic.
- On regeneration, create a new recommendation and explicitly supersede the prior recommendation/plan.
- Set the initial lifecycle state from the governed plan: `diagnostic_only`, `awaiting_approval`, or `ready_to_execute`.

### Remediation

- Accept only an approval/policy decision bound to the current recommendation and plan fingerprint.
- Allocate an immutable attempt number and idempotency key per plan/attempt.
- Record policy decisions as reason codes; do not turn retryable HOTL-to-HITL handoff into a terminal incident failure.
- Publish `executing` before dispatch and one explicit attempt outcome afterward.
- Never reuse an action from a superseded recommendation as the current action.
- Pass the approved plan, execution contract, target identity, and observed executor result to closure.

### Closure

- Validate the exact executed plan fingerprint and action ID.
- Consume both structured validation commands and queries through one normalized validation contract.
- Require at least one authoritative recovery check for mutating execution.
- Distinguish execution success from recovery success.
- Own `recovered` and `closed`; remediation cannot close an incident.
- A diagnostic closure may transition `diagnostic_only -> closed`, but must set
  `closure_kind=diagnostic`, `health_restored=false`, and
  `alerts_cleared=false`. It must never be counted as validated recovery.
- On failed validation, emit `failed_retryable` or request rollback. Never close based only on executor exit code.
- Persist the incident projection and broker event in one transaction through
  the resolution outbox. Broker delivery is retried with the same event ID.
- Startup terminal-action reconciliation defaults to `preview`. `apply` may
  replay only diagnostic completion evidence or the complete signed recovery
  contract; a bare `succeeded` executor status is classified `revalidate`.

## Projection and UI rules

- The repository stores the latest accepted lifecycle envelope as the incident projection.
- Summary and detail views consume the same projected `state`; neither derives lifecycle state from approval/action fields.
- Historical blocks, actions, and approvals remain visible in the timeline but cannot control a superseding plan.
- UI actions are derived from `permitted_actions` supplied by the lifecycle projection, not reconstructed from labels.

## Migration

1. Add the shared v4 model and transition reducer without removing existing fields.
2. Make resolution-agent publish the envelope and canonical plan identity.
3. Make remediation consume/advance it and classify existing `policy-blocked + awaiting_approval` as `blocked_retryable`.
4. Make closure consume/advance it and normalize `validation_commands`, `queries`, and HTTP health checks.
5. Project v4 state through metadata and processed-result APIs.
6. Switch UI summary/detail/gates to projected state and `permitted_actions`.
7. Remove legacy state derivation after stored active incidents are backfilled.

## Recovery and reconciliation controls

- `CLOSURE_RECONCILIATION_MODE=preview|apply` (default `preview`).
- `CLOSURE_RECONCILIATION_BATCH_SIZE` bounds the startup assessment.
- `GET /reconciliation/terminal-actions` returns a read-only, sanitized preview.
- `resolution_outbox` atomically records lifecycle events with projection
  changes; the dispatcher marks an event published only after broker
  acceptance and retries failures with bounded exponential backoff.
- `resolution_inbox` is included in the additive migration for consumer-side
  deduplication. Consumers should migrate one at a time before legacy broker
  deduplication is removed.

## Required release tests

- Diagnostic RCA becomes executable after catalog onboarding/regeneration.
- A policy-blocked automatic attempt continues through HITL approval.
- A superseded block never controls the new recommendation.
- Approval for plan A cannot execute plan B.
- Duplicate submission does not execute twice.
- Executor success plus failed recovery check does not close the incident.
- Successful rollback enters validation before closure.
- Summary, detail, Jira projection, and audit timeline show one consistent state.
- A complete live incident proceeds alert -> RCA -> approval/HOTL -> execute -> validate -> close.
