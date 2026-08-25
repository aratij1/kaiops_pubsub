# Frontend technical-debt register

## TD-FE-001: Legacy application compatibility boundary

- **Introduced:** Phase 1, 2026-08-04
- **Boundary:** `src/app/LegacyApplicationShell.tsx` dynamically imports `src/App.jsx`.
- **Reason:** preserve the in-memory JWT session, API contracts, workflow state, and existing page behavior while URL routes and TypeScript modules are introduced incrementally.
- **Risk:** route chunks are currently markers; the large legacy application chunk is still required for every authenticated page.
- **Removal criteria:** every page owns its typed route component and shared session/query providers have moved above the route outlet.
- **Rollback:** point `index.html` back to `/src/main.jsx` and remove the TypeScript/router files and dependencies.

## TD-FE-002: Duplicate permission/navigation metadata

- **Introduced:** Phase 1, 2026-08-04
- **Resolved:** Phase 4, 2026-08-04
- **Boundary:** typed navigation and permissions coexist with legacy definitions in `App.jsx`, `appHelpers.jsx`, and `onboardingConfig.js`.
- **Reason:** changing the legacy sidebar and keyboard behavior in the routing foundation would expand the compatibility surface before route tests exist.
- **Risk:** labels or permissions can drift.
- **Removal criteria:** sidebar, breadcrumbs, keyboard shortcuts, titles, and permission checks all consume `src/app/navigation.ts` and `src/app/permissions.ts`.
- **Resolution:** the sidebar, mobile navigation, router, breadcrumbs, titles, keyboard shortcuts, role checks, contextual links, and navigation search now consume the typed registry. The duplicate role/tab and shortcut definitions were removed from legacy JavaScript.

## TD-FE-003: Query-cache to legacy-state projection

- **Introduced:** Phase 2, 2026-08-04
- **Boundary:** `App.jsx` uses typed TanStack Query acquisition for alerts and landing-pad rows, then projects validated rows into legacy local UI state.
- **Reason:** acknowledgement, closure, severity overrides, and incident transitions still patch the shared legacy alert state synchronously. Removing it before the Alerts and Incident routes are extracted would change operational behavior.
- **Risk:** query data and the temporary projection can differ between a local action patch and the next invalidation/refetch.
- **Mitigation:** every existing mutation path retains its explicit refresh or row patch; network requests, caching, cancellation, retries, and validation are owned only by TanStack Query.
- **Removal criteria:** Alerts and Incident routes render from query selectors, and mutations update/invalidate the query cache directly.

## TD-FE-004: React Router 6 security upgrade boundary

- **Introduced:** Phase 3, 2026-08-04
- **Boundary:** the lockfile is at React Router DOM 6.30.4, the newest non-breaking resolution available to the current `^6.30.1` range.
- **Reason:** npm reports two moderate advisories whose offered full remediation crosses to React Router 7. Moving major versions changes data-router behavior and requires a dedicated compatibility phase.
- **Current exposure:** KaiOps does not hydrate server-rendered router errors and does not navigate to user-supplied destinations. Route resolution is restricted to the static navigation registry, reducing applicability of the reported SSR constructor-injection and arbitrary redirect paths.
- **Mitigation:** do not introduce user-controlled `Link`/`navigate` destinations; retain route allowlisting and browser regression coverage. There are no high or critical production dependency findings.
- **Removal criteria:** migrate to a patched React Router 7 release, execute the route/auth regression suite, and confirm deep-link and error-boundary compatibility.

## TD-FE-005: Platform and audit route compatibility tabs

- **Introduced:** Phase 4, 2026-08-04
- **Boundary:** `/applications` and `/integrations` currently select the Admin compatibility tab; `/audit` currently selects Gateway Safety. Their canonical URLs, titles, navigation state, and route chunks are independent, but their page bodies still come from the legacy tab.
- **Reason:** the authoritative information architecture must precede extracting three substantial legacy workspaces.
- **Risk:** the canonical title can be more specific than the legacy page body until extraction.
- **Mitigation:** explicit route-marker comments, browser coverage, and no fabricated API behavior.
- **Removal criteria:** extract typed Applications, Integrations, and Audit route components and remove their legacy-tab mappings.

## TD-FE-006: Incident subsection stored in compatibility state

- **Introduced:** Phase 5, 2026-08-04
- **Boundary:** the selected Overview/Evidence/RCA/Resolution/Approval/Execution/Audit section is held in the mounted legacy cockpit state rather than a nested route or URL search parameter.
- **Reason:** progressive disclosure was introduced without remounting the legacy application or changing alert/incident API behavior.
- **Risk:** route changes and previous/next records preserve the section, but a full browser reload returns to Overview.
- **Mitigation:** section state remains stable across normal application navigation; browser tests cover record-to-record preservation.
- **Removal criteria:** extract the Incidents route and encode the selected section and record identity in its typed route/search schema.

## TD-FE-007: Alert bulk-action contract gap

- **Introduced:** Phase 7, 2026-08-04
- **Boundary:** the ingestion UI cannot bulk acknowledge, assign, suppress, or close alerts because no atomic, idempotent, role-authorized bulk API contract exists.
- **Reason:** composing per-record mutations client-side could partially succeed, duplicate execution, or report a misleading overall result.
- **Mitigation:** the UI clearly states the limitation and does not render fake successful controls. Single-record operational workflows remain available through the incident cockpit.
- **Removal criteria:** add backend bulk mutation contracts with per-record outcomes, authorization, idempotency keys, audit correlation, and retry semantics; then add confirmation and partial-failure UI.

## TD-FE-008: Emergency-stop contract gap

- **Introduced:** Phase 8, 2026-08-04
- **Boundary:** the execution workspace exposes emergency stop as unavailable because the backend has no cancellation contract for a remediation that has already started.
- **Reason:** a client-only stop control would imply safety that does not exist and could leave remote execution running.
- **Mitigation:** dangerous production actions require an exact typed confirmation; execution remains role-gated and audited through the existing API; the unavailable control explains the limitation.
- **Removal criteria:** add an authenticated, idempotent cancellation API with executor acknowledgement, terminal-state reconciliation, audit correlation, and browser coverage before enabling the control.

## TD-FE-009: Collaboration and notification-preference contract gap

- **Introduced:** Phase 10, 2026-08-04
- **Boundary:** operational alert/approval/resolution signals are visible, but notes, mentions, watchers, subscriptions, channel preferences, quiet hours, maintenance windows, grouping, and reminders cannot be changed.
- **Reason:** the repository has notification delivery but no authenticated per-user persistence and retrieval contract for these settings or collaboration records.
- **Mitigation:** controls remain disabled, explain the dependency, and never claim local-only success.
- **Removal criteria:** add tenant- and user-scoped MySQL contracts, authorization, audit events, delivery reconciliation, and browser/integration tests; then enable these controls.
