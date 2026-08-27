# Production readiness remediation for `36d4e5d`

## Baseline identity

- Repository: `ashneevai/kaims-latest`
- Implementation branch: `fix/recovery-production-readiness-36d4e5d`
- Pinned starting commit: `36d4e5d6a33158859e95ca2086a2cf4cb64bfba5`
- Consolidated foundation: `6e524173ad0c752272b6c53518e0cc8108bf820d`
- Foundation ancestry at the start of remediation: verified
- Canonical production owners: `backend/`, `ai-workbench/`, and `frontend/react/`
- Obsolete root `services/` tree: absent

The implementation branch was created directly from the pinned starting commit. It must
not merge or replace `main`, import the obsolete service tree, or acquire any contaminated
commit as an ancestor.

## Original verified findings

The pinned recovery branch retained the correct consolidated lineage and passed the
previously reported backend, recovery-topology, frontend unit, frontend static-analysis,
production-build, bundle-budget, hosted frontend, critical Playwright, dependency-security,
and deployment-contract checks. Hosted backend CI subsequently failed in strict RAG
metadata validation. Docker and Kubernetes jobs were skipped as downstream consequences
of that failed backend gate.

The production-readiness review identified these unresolved release blockers:

1. The RAG corpus contains production-ineligible documents with missing or malformed
   metadata. Tenant, ownership, review, and provenance values must be proven or the
   documents must be quarantined outside production retrieval.
2. Cloud connection discovery does not consistently bind the requested project to the
   connection's authoritative stored project.
3. Incident correlation ownership is inferred from bounded frontend data rather than
   acquired transactionally by the backend, and recurrence generations are not explicit.
4. Incident grouping, counts, and pagination are page-local rather than server-owned.
5. Internal context connectors can inherit uncontrolled environment proxies.
6. Critical CI does not execute focused correlation coverage.
7. The legacy frontend application shell is at its architecture ceiling and the shared
   CSS bundle lacks safe budget headroom.
8. Backend production dependencies are broadly constrained and are not yet installed
   from one canonical lock and verified export.

## Baseline verification state

The reported baseline evidence is:

- Backend tests: 734 passed.
- Recovery topology tests: 2 passed.
- Frontend unit tests: 106 passed.
- Frontend lint, TypeScript, architecture, production build, and bundle budget: passed.
- Ruff recovery ratchet: 1,740 findings, reduced from the inherited baseline, with no
  permission to weaken configuration or increase findings in touched files.
- Hosted RAG validation: 167 Markdown files scanned, 165 errors, 2 warnings.
- Hosted backend CI: failed at RAG metadata validation.
- Hosted Docker and Kubernetes jobs: skipped because their prerequisite backend job failed.
- Backend dependency lock: not present at this baseline.

These figures are baseline inputs, not final promotion evidence. Each will be replaced or
supplemented by exact results from this implementation branch after the relevant phase.

## Release-blocker branch observed baseline (2026-08-27)

- Branch: `fix/production-readiness-release-blockers-1011892`
- Exact starting commit: `1011892da62bedb69553df3c034f9f4b83363d66`
- Recovery parent `36d4e5d6a33158859e95ca2086a2cf4cb64bfba5`: verified ancestor.
- Consolidated foundation `6e524173ad0c752272b6c53518e0cc8108bf820d`: verified ancestor.
- Excluded ancestors: `44330b2`, `c11e6dd`, `e5b0108`, and `f11fcac` were each verified absent.
- Complete backend suite: **739 passed, 10 failed, 2 warnings** from 749 tests in 393.05 seconds.
- Ruff recovery ratchet: **blocked** by increases across 13 file/rule pairs.
- RAG metadata validation: **0 Markdown files scanned, 0 errors, 0 warnings**. This is not
  production readiness evidence because the active corpus is empty.
- Recovery topology: validator passed; topology tests **2 passed**.
- Frontend ESLint: passed.
- Frontend architecture budget: passed, with legacy `App.jsx` exactly at **13,600/13,600 lines**.
- Frontend TypeScript: failed with **6 diagnostics**: five duplicate/incompatible
  `connection_id` diagnostics and one invalid refresh click-handler diagnostic.
- Frontend unit tests: **106 passed** across 24 files.
- Frontend production build and bundle budget: passed. Global `index` CSS measured
  **49.96 KiB gzip**; `App` measured **116.56 KiB gzip** and `appHelpers` **49.75 KiB gzip**.
- Compose model: `docker compose config --quiet` passed.
- Kubernetes schema validation: **38 valid resources in 7 files; 0 invalid, 0 errors, 0 skipped**.
- Python frozen dependency lock: absent at this baseline.

The ten backend failures are the expected governed-RAG fixture/empty-corpus failures,
external-judge publish-state loss, and duplicate-correlation ownership failure. No test was
changed during baseline reproduction. An initial Ruff attempt in the plain Python container
could not execute because that image lacks Git; the recorded Ruff result above is from the
successful rerun in a container with Git and Ruff installed.

## Safety constraints

- Tenant, actor, role, project, and execution identity remain server-derived.
- Missing tenant scope or provenance fails closed.
- Quarantined and demo documents are excluded from production retrieval.
- Correlation remains tenant, project, environment, service, lifecycle, and time-window
  scoped; correlation IDs, fingerprints, and Jira keys are not canonical identity alone.
- Immutable incident, evidence, approval, remediation, rollback, validation, and closure
  history is preserved.
- Quality gates, test coverage, lint rules, bundle budgets, and architecture limits will
  not be relaxed.
- Local `.env.azure-config.backup`, `ingested_alerts/`, build output, traces, caches,
  credentials, and generated operational evidence are excluded from commits.

## Planned migrations and API changes

This section records the proposed direction only; later sections must identify the exact
implemented schema and contract after verification:

- A durable, indexed incident-correlation ownership and occurrence model with explicit
  generations and transactional acquisition.
- A server-owned canonical incident-group read model with cursor pagination and accurate
  tenant-scoped counts.
- Authoritative project binding for cloud connections and every discovery artifact.
- Strict RAG corpus classification, quarantine, creation-time validation, and tenant-safe
  retrieval.
- Explicit proxy policy for internal and external connector traffic.

## Promotion status

## Verified remediation evidence (2026-08-27)

The release-blocker work is implemented on
`fix/production-readiness-release-blockers-1011892`, starting at exact commit
`1011892da62bedb69553df3c034f9f4b83363d66`. Recovery ancestry and the absence of the
excluded contaminated commits remain verified.

### Reviewable implementation commits

1. `2ba15ffa5796ca83c428298a3b6811a2c90ef262` - frontend cloud connection contracts.
2. `fea204b23160d5e1681fe4cfa1bdd86750e9729a` - governed tenant-safe RAG lifecycle.
3. `52532682d926b8a43f8bac1756a1be65fdd7c3d1` - canonical incident correlation ownership.
4. `2a0e4e28f1ad2395f43b4b8fc8de9d0cac941b49` - durable lookup and unified pagination.
5. `8d4dd08d38e3eaf98b8b82d3fe040dce411a84a7` - project-scoped Jira and discovery.
6. `7c22e9f5d4792e9e71e3d20fbdf7e6352fb4b949` - Azure model-provider routing.
7. `d01757f5a8a5d5ff9f7cb70e354e117c563e10b2` - production-readiness boundary tests.
8. `3b3742329617ee92e23b8879a44927e7125e53c1` - frozen dependencies and architecture debt.
9. `66d3b21af0a3b5344496b46024e92fd0a24e689e` - release-blocking CI gates.

### Schema, backfill, and API evidence

- Added `backend/database/migrations/20260905_incident_correlation_backfill.sql`, the
  restartable `scripts/backfill_incident_correlations.py`, and the durable correlation
  ownership/occurrence/backfill ledger models.
- Fixture dry-run selected one incident and wrote zero rows. The first fixture upgrade
  acquired one owner and created one occurrence with zero unreconciled or duplicate owners;
  the repeat run reported one already-owned incident. An unscoped terminal incident is
  retained with `needs_scope_review=1` rather than discarded.
- Added direct incident lookup and server-owned incident grouping/feed cursor contracts.
  Frontend previous/next selection consumes server navigation instead of bounded page state.
- Added explicit project identity to cloud connection, discovery, Jira reuse, and artifact
  persistence paths, including stale-request ownership in the cloud resource UI.
- Added canonical provider selection and endpoint validation for native OpenAI, Azure OpenAI,
  legacy Azure configuration, and custom OpenAI-compatible endpoints.

### Quality and deployment results

- Backend: **777 passed, 0 failed, 2 warnings** in the complete suite.
- Ruff ratchet: passed; inherited baseline **1,763 findings**, branch **1,681 findings**;
  touched new files have no Ruff findings.
- Frontend ESLint, architecture, and TypeScript: passed. `App.jsx` is capped at
  **13,585/13,585 lines**, below the prior 13,600-line ceiling.
- Frontend unit tests: **112 passed across 26 files**.
- Critical Playwright boundary set: **32 passed**. The set covers deep-link reload,
  browser navigation, recurrence ownership, active-versus-terminal history, unified cursor
  pagination, cloud project races, missing incidents, and technical-workspace separation.
- Production bundle: global CSS **43.86 KiB gzip**, legacy application CSS
  **25.06 KiB gzip**, application JavaScript **116.66 KiB gzip**, and `appHelpers`
  **49.75 KiB gzip**. All bundle ceilings passed.
- Dependency reproducibility: `uv.lock` resolves **140 packages** including development
  audit tooling; `uv sync --frozen --extra dev` passed, the hash-pinned Docker projection
  matched the lock, and `pip-audit` found **no known vulnerabilities**.
- `docker compose config --quiet`: passed.
- Production image builds: canonical `api-gateway` backend and `ui` images built
  successfully; the backend installed only hash-verified locked requirements.
- Kubernetes: **38 valid resources in 7 files; 0 invalid, 0 errors, 0 skipped** under strict
  kubeconform validation.
- Recovery topology and embedded manifest credential scan: passed.

### RAG inventory and release blocker

- Active governed Markdown documents: **0**.
- Approved and production-retrievable documents: **0**.
- Tracked review drafts: **1,346**, all status `draft`; these remain outside production
  retrieval. No draft was promoted or assigned authoritative metadata by this remediation.
- Strict metadata validation passes over the empty active corpus, but the mandatory
  `--require-production-ready` gate fails because there is no approved retrievable document.

### CI release behavior and remaining external evidence

CI now installs Python from the frozen lock, verifies the Docker projection, runs Ruff,
strict and non-empty RAG gates, all backend tests, correlation/concurrency coverage, frontend
quality and critical Playwright suites, dependency audits, Compose/schema/secret validation,
MySQL migration dry-run/upgrade/idempotency checks, and production image builds. Docker and
Kubernetes reporting jobs use `always()` so an earlier failure cannot silently skip their
result.

Hosted CI, an authoritative RAG approval, credentialed staging checks, and a production
database backfill report are external promotion evidence and were not fabricated locally.
The local secret backup and generated `ingested_alerts/` runtime data remain untracked and
must never be included in a pull request.

**Not eligible for promotion.** The code remediation is complete, but production promotion
is blocked until an accountable reviewer approves at least one governed RAG document, the
non-empty RAG gate passes, the migration/backfill is dry-run and reconciled against the
target production clone, and hosted/staging checks pass. Promotion remains pull-request-only;
do not merge or replace `main` directly.
