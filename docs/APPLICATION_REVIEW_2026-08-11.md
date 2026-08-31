# KaiMS end-to-end application review — 2026-08-11

## Executive result

The platform has a coherent event-driven design, an authenticated API gateway, typed React API boundaries, durable MySQL state, and meaningful CI quality gates. The current branch is not release-clean: legacy hotspot budgets and the repository-wide Python lint gate fail, and some persisted operational state is not tenant-keyed.

This review fixed the highest-risk defect found in the active Project Management workflow: alert-derived projects and their suppression records were shared across tenants. The authenticated tenant is now propagated through the gateway, alert reads are filtered at the database query, and suppression markers are tenant-specific. The default tenant alone retains compatibility with legacy unscoped markers.

## Findings

| Severity | Area | Finding | Status / required action |
|---|---|---|---|
| Critical | Data isolation | Alert-derived project inventory previously read alerts across every tenant and used a global suppression marker. | Fixed and locally validated. Add a multi-tenant integration test to CI. |
| High | Data model | `onboarding_state` uses only project and provider as its primary key and has no first-class `tenant_id`. Other onboarding-state workflows can still collide across tenants. | Open. Add a tenant column, composite key/index, migration/backfill, and tenant-required repository APIs. |
| High | Build governance | Architecture budgets fail for `App.jsx`, monitoring adapter, and API gateway. | Open. Extract feature routers/modules; do not increase budgets. |
| High | Code quality | Repository-wide Ruff reports 934 violations; therefore the configured CI lint job cannot pass on this tree. | Open. Establish a checked-in baseline or fix by service, then enforce zero new violations on changed files. |
| High | Authentication | Several legacy read APIs intentionally accept no token; invalid optional tokens degrade to the default tenant. This is unsafe for tenant-sensitive data. | Open. Require authentication for business data and reserve anonymous access for health/readiness only. |
| Medium | API contracts | Several gateway routes use untyped dictionaries and permissive frontend passthrough schemas, weakening change detection and generated OpenAPI value. | Open. Introduce request/response models per feature router and contract tests. |
| Medium | UI architecture | `App.jsx` remains a very large compatibility shell alongside extracted TypeScript routes, increasing duplicated state and navigation drift risk. | Open. Continue strangler extraction and remove legacy implementations once route parity tests pass. |
| Medium | UX | Destructive project actions use browser confirmation and sequential bulk requests with no per-row outcome summary. | Open. Use the design-system confirmation dialog and return/display partial-success results. |
| Medium | Dependency governance | CI runs Python and npm audits, but this local review did not produce a clean dependency-audit result. Broad lower bounds also reduce reproducibility. | Open. Generate/lock deploy dependencies and retain automated vulnerability updates. |
| Medium | Test environment | The checked-in local virtual environment lacks an OpenTelemetry instrumentation dependency required by the test bootstrap. | Open. Recreate it from the declared dev dependencies or standardize tests on the service container. |

## Changes made

- Added optional tenant filtering to `IncidentRepository.list_alerts` without changing existing callers.
- Propagated the authenticated tenant through `GET/DELETE /alerts/applications`.
- Made observed-project suppression tenant-specific with default-tenant legacy compatibility.
- Corrected the authoritative navigation unit test after Administration became a first-class group.
- Kept observed-project deletion non-destructive: alert history is preserved.

## Verification evidence

- Frontend ESLint: passed.
- Frontend TypeScript: passed.
- Frontend unit tests: 23 passed across 6 files.
- Changed Python modules: byte-compilation passed in the service image.
- API gateway and monitoring-adapter images: built successfully.
- Local UI and API gateway: healthy after restart.
- Tenant-scoped monitoring inventory: returned persisted project data locally.
- Azure: unchanged.

## Recommended delivery order

1. Migrate all onboarding state to a first-class tenant key and add isolation tests.
2. Require authentication on tenant-sensitive reads and reject invalid tokens.
3. Extract monitoring onboarding/inventory and gateway project routers until architecture budgets pass.
4. Burn down Ruff failures service-by-service and enforce changed-file cleanliness immediately.
5. Replace permissive dictionary contracts with versioned Pydantic/Zod schemas.
6. Complete destructive-action UX, accessibility, partial-failure reporting, and browser E2E coverage.
