# KaiOps release candidate — 2026-08-20

## Included changes

- Updated the operations UI navigation and incident-detail handoff, removed duplicate navigation, and stabilized route rendering.
- Fixed visible legacy character-encoding artifacts in the React UI.
- Added fixed sizing for changing health/user labels to prevent header layout shift.
- Preserved verified tenant identity from alerts into created incidents and local workflow envelopes.
- Enforced tenant-scoped learning reports, signed audit verification, immutable approval-plan binding, safe remediation, rollback contracts, and monotonic terminal incident status.
- Bounded landing-pad archive paths for deep Windows/CI workspaces.

## Validation evidence

- Frontend production build and bundle budget: passed after the final UI changes.
- Backend full run: 573 passed, with two dependency deprecation warnings.
- Tenant contract selection: 40 passed across identity, repository isolation, approvals, learning reports, and gateway safety.
- Azure parameter template validation: passed in structural/template mode.
- Migration and remediation rollback contracts: 6 passed.
- Mojibake scan of maintained source/docs (excluding generated RAG, ingested-alert, and test-result trees): clean.
- Playwright: the final all-spec run passed 44 active tests, skipped 3 conditional tests, and found one duplicate Approval heading. That UI defect was fixed, rebuilt, and its extracted-route test passed. All 45 active tests therefore pass across the final full run plus the post-build verification. The 65-second-per-page stability gate passed with CLS about 0.0003, zero root replacements, and zero animations.
- Local Docker migrations: all 27 applied. The approval plan-binding and tenant-capacity migrations were made idempotent and MySQL 8.4-compatible after the preflight exposed unsupported `ADD COLUMN IF NOT EXISTS` syntax.
- Local Docker stack: running; UI, API gateway, MySQL, RabbitMQ, Redis, remediation engine, resolution agent, Temporal, worker, and Jenkins report healthy where health checks are defined.
- Azure VM production: the complete application build and all three approved migrations were deployed to `kaims-dev`; post-deployment container, endpoint, restart, schema, tenant, UI-asset, and recent-log checks passed. Rollback image metadata and database backups are recorded in the Azure validation evidence.

## Worktree review

The release worktree is intentionally not ready for a bulk commit. The 2026-08-20 re-audit found 178 tracked files changed and 7,369 untracked files. Of the untracked entries, 7,030 are under `backend/rag/_review`, 253 are local runtime files, and 14 are generated test artifacts; another 48 tracked files are in generated-test-output paths. Review and curate these groups separately; do not stage the repository wholesale. See `2026-08-20-worktree-curation.md`.

The three migration candidates (`20260821` through `20260823`) passed local application and integrity prechecks. Their exact checksums and production approval conditions are recorded in `2026-08-20-migration-approval.md`. This is technical approval evidence, not authorization to mutate production.

## External production gates

Azure CLI is not installed on the validation host, and no production Azure or real customer identity context was available. Consequently, Bicep compilation, deployment validation/what-if, Key Vault resolution, network reachability, production migrations, revision traffic rollback, and two-real-identity tenant verification remain blocked. These are mandatory pre-production checks, not waived tests.

## Final results

- Complete backend suite: 573 passed.
- Complete Playwright suite: 45 active scenarios passed across the final full run and one post-build verification; 3 conditional scenarios skipped.
- Azure tenant/subscription/resource group: pending.
- Production tenant identities used: pending.
- Release decision: **NO-GO until all pending and external gates pass.**
