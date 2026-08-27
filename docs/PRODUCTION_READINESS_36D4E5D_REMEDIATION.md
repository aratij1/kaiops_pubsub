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

**Not eligible for promotion.** The mandatory remediation phases and their clean-checkout,
Compose, Kubernetes, security, hosted CI, and credentialed staging evidence have not yet
completed. Promotion remains pull-request-only after every required gate reports success.

