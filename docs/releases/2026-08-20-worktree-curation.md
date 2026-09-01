# Dirty worktree curation — 2026-08-20

Branch: `fix/kaims-resolution-production-readiness`

No files were staged, committed, deleted, or pushed during this review.

## Inventory

| Group | Tracked | Untracked | Disposition |
|---|---:|---:|---|
| `backend/rag/_review` | 0 | 7,030 | Exclude by default; curate separately if any output is a release asset. |
| Local `.runtime` | 0 | 253 | Exclude; local state. |
| Generated test-output paths | 48 | 14 | Do not stage as a group. Revert tracked generated output only after confirming it contains no intended baselines. |
| Backend source/tests outside review output | 55 | 36 | Review as backend/migration wave. |
| Frontend source/tests outside generated output | 51 | 19 | Review as UI/E2E wave. |
| AI workbench | 6 | 7 | Review with backend contracts. |
| Deployment | 4 | 0 | Review only after immutable production image references are supplied. |
| Documentation | 2 | 8 | Review as release-evidence wave. |
| Scripts | 6 | 2 | Review with the feature or deployment gate they support. |
| Other tracked files | 6 | 0 | Review individually. |

Pre-documentation snapshot: 7,547 porcelain status entries (178 tracked, 7,369 untracked). This manifest and the migration approval record add two intentional untracked documentation files after that snapshot.

## Proposed review and staging waves

1. Database migrations, backend contract changes, and their focused tests.
2. Remaining backend/AI-workbench behavior and full-suite tests.
3. Frontend routes/styles and Playwright specifications; omit result directories.
4. Azure/Bicep and operational scripts after production parameters use immutable images and real secret references.
5. Release documentation and evidence.
6. Deliberately selected RAG catalog inputs only; never bulk-add `_review` output.

For every wave, inspect `git diff --check`, the exact staged file list, and `git diff --cached` before committing. Do not use `git add .` or `git add -A` on this worktree.

## Current release blockers

- Azure CLI is absent, so account identity, Bicep compilation, deployment validation/what-if, Key Vault access, network reachability, and revision rollback cannot be evidenced here.
- Production parameter validation correctly fails because all application images are not immutable and at least one `REPLACE` placeholder remains.
- Production duplicate prechecks, migration dry-run/application, restore-point verification, and real-identity tenant isolation require authorized Azure access.
