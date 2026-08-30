# Governed Resolution Handoff Report

## Scope and baseline

This branch repairs the alert-to-closure lifecycle from pinned source commit
`71e3f57945966168fe54d76c36792abcb54deb39` on
`fix/incident-context-resolution-contract-5196514`. The implementation branch is
`fix/governed-resolution-handoff-71e3f579`; it must be reviewed and promoted without
rewriting the source branch or `main`.

## Original defects and resulting lifecycle

The original UI used execution readiness to open the catalog, kept catalog selection
in React state, and could join approvals, remediation, or closure to a newer analysis
using incident identity alone. Evidence provenance and confidence were also rendered
inconsistently across projections.

The repaired lifecycle is:

`alert -> incident -> immutable context snapshot -> bounded RCA -> immutable governed
plan -> signed approval readiness -> exact-plan approval -> remediation action ->
validation -> closure`.

The backend remains authoritative. The browser may request selection or regeneration,
but cannot create fingerprints, assert readiness, approve from local state, or attach
legacy actions to the current lifecycle.

## Canonical readiness states

- `contextReady`: exact unexpired snapshot, matching tenant/project/incident/alert,
  verified integrity, and canonical evidence.
- `rcaReady`: context ready, conclusive grounded investigation, accepted evidence,
  and no unresolved gaps or conflicts.
- `resolutionReady`: RCA ready plus a persisted immutable plan bound to the exact RCA
  and recommendation with a valid fingerprint.
- `approvalReady`: resolution ready plus a signed matching backend readiness receipt
  whose policy, target, connector, credentials, rollback, validation, evidence, and
  authorization checks pass.
- `executionReady`: approval ready plus an unexpired, non-revoked approval for the exact
  plan and valid executor/idempotency/concurrency controls.
- `validationReady`: exact remediation action completed and required post-state checks
  are available.
- `closureReady`: validation is durably successful and bound to that remediation.

## Immutable binding matrix

| Stage | Required immutable identities |
| --- | --- |
| Context | tenant, project, incident, alert, analysis request, snapshot, fingerprint |
| RCA | context identities, investigation ID, RCA version, accepted evidence |
| Resolution | RCA identities, recommendation version, plan ID, fingerprint |
| Approval | resolution identities, approval ID, approver, expiry, signed readiness |
| Remediation | approval identities, action ID, target, connector, idempotency key |
| Validation | remediation identities, observation/checksum, validator |
| Closure | validation identities, closure kind, report ID |

## Ownership, persistence, and migrations

- Context agent owns immutable context snapshots and evidence/source contracts.
- Resolution agent owns bounded RCA and catalog-derived plan content.
- The common repository owns atomic persistence, supersession, projection updates,
  audit records, and transactional outbox publication.
- Approval service owns signed readiness and immutable operator decisions.
- Remediation engine owns exact-plan action records and idempotency.
- Closure service owns validation and closure reports bound to the action.

Additive migrations:

- `backend/database/migrations/20260908_governed_resolution_plans.sql`
- `backend/database/migrations/20260909_lifecycle_version_bindings.sql`

Catalog selection creates a UUID plan ID and canonical fingerprint, records the exact
tenant and lifecycle identities, retains superseded versions, updates the projection
only after persistence succeeds, and emits audit/outbox records in the transaction.
Its deterministic idempotency key covers tenant, incident, RCA version,
recommendation, option, and context fingerprint. Stale or cross-tenant requests fail
closed with HTTP 409/authorization errors.

## API, projection, and frontend behavior

`/resolution-catalog/select` returns the persisted canonical plan rather than an
ephemeral dictionary. The processed incident response hydrates only the plan,
approval, remediation, validation, and closure records matching the current immutable
chain. Unbound legacy records are historical and cannot affect readiness.

The frontend refreshes the processed projection after selection and verifies plan and
recommendation identities before navigating. All approval surfaces use the shared
eligibility selector and show backend blockers. Expired context contracts expose a
one-click fresh-context regeneration action. Zero accepted RCA evidence is rendered
as `Ungrounded` with zero diagnostic confidence; stale recommendation confidence is
not revived.

## Evidence and RAG governance

Evidence requires a real connector/source identity, timestamps, observation window,
freshness, provenance, citation, and epistemic role. Missing or synthetic citations
cannot ground RCA or unlock approval. Connector failures remain explicit non-evidence
states.

Production RAG validation currently passes with one approved retrievable runtime
document at `backend/rag/remediations/36cde899-750b-46ff-ae03-e57ea90a4ad9.md`.
That directory is intentionally untracked and the validator warns that `remediations`
is an unknown RAG section. Promotion therefore still requires a deliberate decision:
either define the governed section in source and preserve the approved document in an
authorized store, or keep release readiness dependent on runtime provisioning. No
approval metadata was fabricated.

## Verification evidence (2026-08-30)

- Governed backend lifecycle suite: 52 passed.
- Frontend quality: ESLint passed; architecture budget passed; TypeScript passed;
  133 unit tests passed.
- Focused frontend lifecycle suites: 25 passed; focused confidence suites: 13 passed.
- Playwright incident handoff/approval suite: 7 passed.
- Production build and bundle budget: passed.
- Execution catalog: 29 actions, 11 connectors, 9 playbooks; passed.
- Execution checksums, Phase 9 readiness, recovery topology: passed.
- Strict/production RAG metadata: passed with the runtime-section warning above.
- `docker compose config --quiet`: passed.
- `git diff --check`: passed.
- Ruff recovery ratchet: blocked. The branch initially added one `F821`; that runtime
  defect was fixed by using `timezone.utc`. Remaining ratchet failures are E501/B008
  and import-order count increases in previously modified files and must be reduced
  before promotion.
- Full backend `pytest`, migration upgrade against a representative old schema, all
  owned image builds, Kubernetes dry-run, full Playwright suite, and secret scan have
  not yet been completed in this Phase 10 run and must not be reported as passed.

## Remaining risks and promotion procedure

1. Clear the Ruff regression ratchet without weakening its baseline.
2. Validate both additive migrations against a captured pre-migration schema and
   prove exact-plan indexes/constraints.
3. Run full backend pytest, every owned image build, Kubernetes client dry-run, full
   Playwright, dependency/secret scans, and repository artifact checks.
4. Resolve the runtime-only RAG section warning and document authoritative storage.
5. Re-run all gates from a clean checkout of this branch.
6. Push this branch, open a pull request into the intended integration branch, require
   review of migrations/security/readiness semantics, and use a normal merge. Do not
   force-push, replace `main`, or bypass failed checks.

