# Orchestration Policy: Hybrid Rules + AI

This document defines how KaiMS decides orchestration steps using a hybrid model:

- Rules control safety, approvals, and deterministic fallback.
- AI planner suggests workflow selection when enabled.
- Rules always have final authority.

## Why Hybrid

- Pure rule-based orchestration is predictable but brittle as scenarios grow.
- Pure AI orchestration adapts faster but can be non-deterministic.
- Hybrid combines reliability, auditability, and adaptive decision support.

## Decision Contract

The orchestrator decision now exposes:

- `requires_approval`: final gate for human approval.
- `risk_tier`: `high` | `medium` | `low` derived from alert severity.
- `execution_mode`: `human-approval` | `guided-auto` | `auto-execute`.
- `policy_reason`: concise explanation of why the mode was selected.

## Rule Layer (Authoritative)

### Risk Tier Mapping

- `critical` severity -> `high` risk tier.
- `high` severity -> `high` risk tier.
- `warning` severity -> `medium` risk tier.
- `info` severity -> `low` risk tier.

### Mandatory Approval Severities

Configured by `ORCHESTRATION_APPROVAL_SEVERITIES` (default: `high,critical`).

If severity is in this set:

- `requires_approval = true`
- `execution_mode = human-approval`

### Confidence Bands

- Guided threshold: `CONFIDENCE_GUIDED_EXECUTE_THRESHOLD` (default: `0.75`)
- Auto threshold: `CONFIDENCE_AUTO_EXECUTE_THRESHOLD` (default: `0.90`)

Behavior for non-mandatory severities:

- confidence `< guided threshold`:
  - `requires_approval = true`
  - `execution_mode = human-approval`
- confidence `>= guided threshold` and `< auto threshold`:
  - `requires_approval = false`
  - `execution_mode = guided-auto`
- confidence `>= auto threshold`:
  - `requires_approval = false`
  - `execution_mode = auto-execute`

If confidence is absent, KaiMS defaults to:

- `requires_approval = false`
- `execution_mode = guided-auto`

This preserves continuity while avoiding blind auto-execution without a score.

## AI Planner Layer (Advisory)

Controlled by `ORCHESTRATION_LLM_PLANNER_ENABLED`.

When enabled, the planner may suggest one of:

- `critical-auto-remediation`
- `guided-remediation`
- `triage-only`

Guardrails:

- Unsupported planner output is ignored.
- Workflow falls back to deterministic severity routing.
- Approval and execution mode still come from rule policy.

## Recommended Defaults for Enterprise

- `ORCHESTRATION_APPROVAL_SEVERITIES=high,critical`
- `CONFIDENCE_GUIDED_EXECUTE_THRESHOLD=0.75`
- `CONFIDENCE_AUTO_EXECUTE_THRESHOLD=0.90`
- `ORCHESTRATION_LLM_PLANNER_ENABLED=true` for decision support only

## Operational Guidance

- Keep severe incidents (`high`, `critical`) behind human approval.
- Allow autonomous remediation only for low-risk and high-confidence recommendations.
- Log and monitor distribution of `execution_mode` over time.
- Tune thresholds per environment after post-incident review.
