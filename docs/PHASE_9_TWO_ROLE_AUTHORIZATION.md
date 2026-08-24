# Phase 9 — Two-role authorization migration

KaiOps now uses two canonical operational roles:

- `ADMIN` manages users, onboarding, policy, configuration, and governance.
- `HITL_APPROVER` reviews, modifies, approves, rejects, and escalates operational work.

## Compatibility policy

Existing database and audit records are preserved. At authorization time,
`Administrator` maps to `ADMIN`, while `L2 Engineer` and `L3 Engineer` map to
`HITL_APPROVER`. `Executive` and `L1 Operator` remain valid historical/read
identities but receive no operational write permission until an administrator
explicitly assigns a canonical role. This prevents privilege escalation during
the migration.

The SQL migration adds the two canonical role rows idempotently. It does not
delete legacy roles or rewrite users, so rollback consists of reverting live
policy evaluation; historical identities remain intact.
