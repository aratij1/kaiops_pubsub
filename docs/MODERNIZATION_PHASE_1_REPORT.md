# KaiOps modernization: Phase 1 report

Date: 2026-08-04 (Asia/Calcutta)

## Scope completed

- Added a strict TypeScript compilation boundary while retaining incremental JavaScript compatibility.
- Replaced the Vite entrypoint with a small typed `main.tsx` and `app/App.tsx`.
- Added React Router with stable URL paths and SPA fallback compatibility.
- Added one lazy route module for every existing page destination.
- Added typed centralized navigation and permission definitions.
- Added compatibility redirects: `/approval` -> `/approvals`, `/stream` -> `/alerts`, and `/summary` -> `/incidents`.
- Kept one legacy application instance mounted across route changes so in-memory access/refresh tokens and operational UI state survive navigation.
- Added Vitest, isolated unit-test discovery from Playwright, and added navigation/permission tests.
- Added explicit technical-debt entries for the two temporary compatibility boundaries.

This is the Phase 1 **routing and TypeScript foundation**, not the completion of all page extraction. `App.jsx` remains behind a documented lazy compatibility boundary. Each route now has a typed extraction target, but page content will move incrementally after shared query/session providers exist.

## Files reviewed

- Frontend entry, package, Vite, Playwright, nginx, navigation, onboarding, helpers, `App.jsx`, styles, and e2e specifications
- Backend service entrypoints and API gateway user/auth modules
- Common database, repository, bus, resilience, model, telemetry, and configuration modules
- MySQL schema and migrations
- Docker Compose deployment topology and runtime containers
- Monitoring adapter filesystem landing-pad/archive implementation

Full inventory: `docs/MODERNIZATION_PHASE_0_BASELINE.md`.

## Files created

- `frontend/react/tsconfig.json`
- `frontend/react/vitest.config.ts`
- `frontend/react/src/vite-env.d.ts`
- `frontend/react/src/main.tsx`
- `frontend/react/src/app/App.tsx`
- `frontend/react/src/app/providers.tsx`
- `frontend/react/src/app/router.tsx`
- `frontend/react/src/app/navigation.ts`
- `frontend/react/src/app/permissions.ts`
- `frontend/react/src/app/LegacyApplicationShell.tsx`
- `frontend/react/src/app/navigation.test.ts`
- 11 typed lazy modules under `frontend/react/src/routes/`
- `frontend/react/docs/TECHNICAL_DEBT.md`
- `docs/MODERNIZATION_PHASE_0_BASELINE.md`
- `docs/MODERNIZATION_PHASE_1_REPORT.md`

## Files modified

- `frontend/react/index.html`: typed entrypoint
- `frontend/react/package.json`: router, TypeScript, Vitest, typecheck/unit scripts
- `frontend/react/package-lock.json`: reproducible dependency lock
- `frontend/react/src/App.jsx`: typed JSDoc compatibility props and URL/tab synchronization
- `frontend/react/tests/e2e/discovery-layout.spec.js`: URL navigation assertions
- `frontend/react/tests/e2e/alert-stream-virtualized.spec.js`: align the test fixture with the production/test classifier and 150-row balanced-source contract

Pre-existing modifications in these files were preserved.

## Architecture decisions

1. BrowserRouter paths are additive; `/` remains Dashboard.
2. `LegacyApplicationShell` is the stable parent route and owns one lazy legacy app instance, avoiding authentication state loss between route modules.
3. The URL is authoritative for the top-level destination; local storage continues to own density, theme, selected flow, project, and filter preferences.
4. Lazy route marker modules establish extraction boundaries without duplicating or fabricating backend behavior.
5. TanStack Query, Zod, and React Hook Form are deferred to Phase 2 as required by the phase gate.
6. Existing backend RBAC remains the security boundary. Typed frontend permissions are navigation metadata, not authorization enforcement.

## Existing functionality preserved

- Login, refresh-token, logout, and in-memory token behavior
- Role-filtered navigation behavior
- Dashboard, alert stream, discovery, admin setup, accessibility, virtualized alert list, and existing API calls
- All FastAPI routes and response contracts
- RabbitMQ workflow and operational services
- MySQL schemas, migrations, repositories, pooling, and data
- nginx SPA fallback already supports direct route bookmarks

## API contracts affected

None. No backend route, request, response, authentication, event, or persistence contract changed.

## MySQL impact

None. No SQL, schema, migration, SQLAlchemy model, repository, connection, pool, or configuration changes were made. No PostgreSQL or pgvector dependency was introduced.

## Security implications

- Tokens remain in React memory and are not moved to browser storage.
- No credentials or payloads were added to code, logs, tests, or reports.
- Route visibility does not replace backend authorization.
- Unknown paths fail safely to Dashboard; legacy paths redirect without exposing state.

## Feature flags added

None. The router is a composition change with a direct entrypoint rollback; it does not alter backend or workflow behavior.

## Tests added or updated

- Three Vitest assertions cover unique navigation definitions, path/tab round trips, and L1 restricted destinations.
- Browser navigation now asserts `/alerts` and `/` URL behavior.
- The virtualization fixture now uses production-like alert names and all five supported source channels; it exercises the maximum 150-row balanced stream.

## Commands executed and results

```text
docker ... npm install --package-lock-only     PASS
docker ... npm ci                              PASS
npm run test:unit                              PASS: 3/3
npm run typecheck                              PASS
npm run build                                  PASS
npx playwright test                            PASS: 4 passed, 2 live-only skipped
git diff --check (Phase 0/1 paths)              PASS (line-ending warnings only)
```

The host does not expose `npm`; all Node work used the reproducible Node 20 container path.

## Build and performance measurements

Before the lock repair, a clean build could not start because package metadata was inconsistent. The last deployed baseline bundle was:

- Main JavaScript: 676.80 KB raw / 173.94 KB gzip

Phase 1 build:

- Typed router/vendor entry: 208.88 KB raw / 68.06 KB gzip
- Lazy legacy application: 558.52 KB raw / 135.76 KB gzip
- Each route marker chunk: approximately 0.05 KB
- CSS: 123.91 KB raw / 22.76 KB gzip

The initial entry is separated from the legacy application, but an authenticated page still needs both main chunks. Therefore Phase 1 does **not** claim a total JavaScript reduction. Actual reduction begins as page content and shared dependencies move out of the legacy chunk.

Runtime API/archive baselines remain recorded in the Phase 0 document; no backend performance path changed in Phase 1.

## Screenshots

Not applicable for Phase 1: no visual layout, color, typography, content, or interaction design was intentionally changed. Browser regressions and axe validation provide stronger evidence for this composition-only phase. Screenshots become required when Phase 3/5 changes visible components and page layout.

## Known limitations

- `App.jsx` remains 12,000+ lines and is compiled as a 558 KB lazy compatibility chunk.
- Route modules are typed extraction markers, not independent page implementations yet.
- Legacy sidebar/keyboard navigation and role maps coexist with typed metadata (TD-FE-002).
- No TanStack Query, Zod, React Hook Form, Storybook, or shared component library yet; these belong to subsequent gated phases.
- Direct routes preserve page selection, but selected records and section state are still legacy local state.
- Two live Playwright tests require `KAIOPS_LIVE_E2E=1` and were intentionally skipped.
- No test coverage percentage is available because coverage instrumentation is not configured.

## Rollback procedure

1. Change `index.html` from `/src/main.tsx` back to `/src/main.jsx`.
2. Remove `react-router-dom`, TypeScript/type packages, and Vitest from package metadata, then regenerate the lockfile.
3. Remove `src/app`, `src/routes`, `src/main.tsx`, `src/vite-env.d.ts`, `tsconfig.json`, and `vitest.config.ts`.
4. Revert only the `initialTab`/`onActiveTabChange` compatibility changes in `App.jsx` and the URL assertions.
5. Run the existing production build and Playwright suite.

No database, backend, message-bus, authentication data, or runtime workflow rollback is required.

## Recommended next phase

Begin Phase 2 with one read-only domain: Live Alerts. Add the query client and Zod boundary, migrate `/alerts/all` and `/landing-pad/recent` to typed cached queries, prove request deduplication/cancellation/stale-state behavior, then extract the Alerts route content. Do not migrate mutation-heavy approval or remediation flows until that read-only pilot passes.

