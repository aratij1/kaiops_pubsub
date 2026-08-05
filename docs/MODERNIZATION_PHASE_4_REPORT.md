# KaiOps modernization: Phase 4 report

Date: 2026-08-04 (Asia/Calcutta)

## Scope completed

Phase 4 reconciles navigation and routing around one typed registry used by:

- desktop sidebar and responsive mobile navigation
- lazy route generation and canonical URLs
- breadcrumbs and document titles
- role permission checks and restricted-route explanations
- keyboard shortcuts
- global navigation search
- contextual alert-to-incident-to-approval-to-closure navigation

Navigation is organized into Operations, Intelligence, Governance, and Platform. The standard menu no longer contains a legacy-labelled page. Old Approval, Stream, and Summary bookmarks redirect to their canonical routes. The persistent application shell retains selected records, filters, and component state; route-specific body scroll positions are saved and restored.

## Files reviewed

- modernization brief Phase 4 requirements
- typed router, navigation, permissions, and compatibility shell
- legacy sidebar, shortcut, role-tab, title, and active-tab definitions
- all existing route markers and browser tests
- responsive sidebar and theme styles

## Files created

- `frontend/react/src/routes/audit/AuditRoute.tsx`
- `frontend/react/src/routes/applications/ApplicationsRoute.tsx`
- `frontend/react/src/routes/integrations/IntegrationsRoute.tsx`
- `frontend/react/tests/e2e/navigation-routing.spec.js`
- `frontend/react/artifacts/README.md`
- `frontend/react/artifacts/phase4-authoritative-navigation.png`
- `docs/MODERNIZATION_PHASE_4_REPORT.md`

## Files modified

- `frontend/react/src/app/navigation.ts`
- `frontend/react/src/app/permissions.ts`
- `frontend/react/src/app/router.tsx`
- `frontend/react/src/app/LegacyApplicationShell.tsx`
- `frontend/react/src/app/navigation.test.ts`
- `frontend/react/src/App.jsx`
- `frontend/react/src/appHelpers.jsx`
- `frontend/react/src/onboardingConfig.js`
- `frontend/react/src/styles.css`
- `frontend/react/tests/e2e/discovery-layout.spec.js`
- `frontend/react/docs/TECHNICAL_DEBT.md`

## Architecture decisions

1. Every destination has a canonical ID, path, label, title, group, route module, icon key, search terms, allowed roles, legacy compatibility tab, and optional related destinations.
2. The router maps the registry to lazy components instead of duplicating canonical paths.
3. Role permission data lives on registry destinations; legacy role-tab lists and shortcut maps were removed.
4. Multiple canonical routes may temporarily select one legacy body tab. This compatibility boundary is explicit as TD-FE-005.
5. Executive Dashboard remains bookmark-compatible but is excluded from standard navigation because the mandated four-group information architecture does not include it. Authorized users can retain existing bookmarks.
6. Direct restricted URLs redirect to Dashboard with a visible role explanation. This complements hidden unauthorized menu items.
7. The legacy application remains mounted between route changes, preserving in-memory session, filters, selected alert/incident, and section state. The shell separately restores scroll by pathname.

## Existing functionality preserved

- current URLs plus redirects for `/approval`, `/approval-queue-legacy`, `/stream`, and `/summary`
- existing login, in-memory JWT, role normalization, and logout
- all legacy workspace bodies and operational workflows
- alert query cache, polling, source balancing, and 150-row virtualization cap
- themes, density, responsive behavior, health actions, and keyboard access
- browser back/forward behavior and bookmarked routes

## API contracts affected

None. No endpoint, request, response, authentication header, or backend behavior changed.

## MySQL impact

None. No schema, migration, SQL, repository, model, transaction, index, connection pool, or configuration changed. MySQL remains the only relational database; PostgreSQL and pgvector were not introduced.

## Security implications

- direct canonical destinations are checked against the same typed permission registry used by navigation
- restricted deep links do not expose the requested page body and provide a clear explanation after redirect
- unknown paths redirect to Dashboard
- no route is constructed from untrusted user input
- no credentials, tokens, payloads, or personal information are logged or persisted
- the existing React Router 6 advisories remain tracked under TD-FE-004

The frontend does not replace backend authorization; API endpoints must continue enforcing server-side RBAC.

## Feature flags added

None. Canonical routes preserve the legacy rendering boundary and require no persisted-data migration.

## Tests added

Navigation unit coverage now verifies:

- unique destination IDs and paths
- canonical route-to-legacy-tab mapping
- legacy bookmark redirects
- role filtering and permission explanations
- role-aware global navigation search
- breadcrumbs and contextual workflow relationships

Browser coverage verifies:

- legacy approval bookmark redirect
- canonical URLs, page titles, breadcrumbs, and active navigation state
- route-specific scroll restoration
- responsive mobile navigation
- Applications canonical navigation
- L1 direct Admin deep-link rejection and explanation
- all four desktop groups

## Commands executed and test results

```text
npm run typecheck                                                   PASS
npm run test:unit                                                   PASS: 14/14
npm run build                                                       PASS
npm run test:e2e                                                    PASS: 5 passed, 2 live-only skipped
npx playwright test navigation-routing accessibility               PASS: 3/3
npx playwright test discovery-layout                               PASS: 1/1
```

The first full browser run correctly exposed an obsolete test selector for the renamed canonical “Live Alerts” label. After updating the test to use semantic navigation, the full suite passed. The first breadcrumb assertion expected the CSS-rendered slash in DOM text; it was corrected to assert the two semantic labels.

## Build and performance measurements

Phase 3:

- router/query entry: 237.97 KB raw / 76.58 KB gzip
- legacy application: 619.64 KB raw / 150.03 KB gzip
- CSS: 125.21 KB raw / 23.22 KB gzip

Phase 4:

- router/query/navigation entry: 241.66 KB raw / 77.72 KB gzip
- legacy application with complete grouped navigation and route guard: 625.17 KB raw / 151.64 KB gzip
- CSS: 126.57 KB raw / 23.46 KB gzip
- Audit, Applications, and Integrations lazy markers: 0.05 KB raw / 0.07 KB gzip each

The phase adds 3.69 KB raw / 1.14 KB gzip to the shared entry, 5.53 KB raw / 1.61 KB gzip to the lazy legacy UI, and 1.36 KB raw / 0.24 KB gzip to CSS. Route transitions preserve the mounted application, avoiding refetches or state reconstruction. The large legacy chunk remains the primary frontend performance constraint.

## Screenshot

`frontend/react/artifacts/phase4-authoritative-navigation.png` (1,457,674 bytes) shows the authenticated grouped navigation, canonical breadcrumb, and unchanged operational workspace. It was visually inspected after capture.

## Known limitations

- Applications, Integrations, and Audit have independent URLs and route chunks but still render legacy Admin/Gateway Safety bodies (TD-FE-005).
- Executive Dashboard is bookmark-compatible but intentionally absent from the mandated standard menu.
- “Global search” currently consumes the registry through a tested search function; the visible cross-domain search command palette belongs to Phase 10.
- selected records and filters remain in legacy component memory rather than URL parameters, so a full browser reload cannot reconstruct them yet
- scroll restoration covers window scroll; independently scrolling legacy panels retain their own mounted DOM state
- the sidebar uses its existing bounded scroll region on short viewports
- `App.jsx` remains above 500 KB and must be decomposed route by route

## Rollback procedure

1. Restore explicit route entries in `router.tsx`.
2. Restore the five-item sidebar and legacy role/shortcut constants.
3. Remove breadcrumbs, mobile selector, contextual links, role-deep-link guard, title and scroll effects.
4. Remove Audit, Applications, and Integrations route markers and the new browser test.
5. Keep canonical redirect routes if bookmarked URLs have already been distributed; otherwise restore the prior three redirects.
6. Run type checking, unit tests, production build, and Playwright.

No backend, API, MySQL, message-bus, authentication-data, or persisted-business-data rollback is required.

## Recommended next phase

Proceed to Phase 5 progressive disclosure for the incident cockpit: sticky incident identity/actions, Overview/Evidence/RCA & Impact/Resolution/Approval/Execution/Audit Trail sections, selected-section-only rendering, lazy technical evidence, previous/next record controls, and elimination of unnecessary nested scrolling. Use the Phase 3 shared components and preserve the Phase 4 canonical navigation registry.
