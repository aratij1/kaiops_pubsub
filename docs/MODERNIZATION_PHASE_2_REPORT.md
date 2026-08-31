# KaiOps modernization: Phase 2 report

Date: 2026-08-04 (Asia/Calcutta)

## Scope completed

Phase 2 introduced a typed server-state acquisition pilot for Live Alerts and the live landing-pad stream:

- TanStack Query provider and centrally configured query client
- Query-key factory for alert lists and the non-archive landing-pad window
- Zod schemas for alert row and response-envelope validation
- Typed, abortable alert and landing-pad services
- Request caching and concurrent-request deduplication
- Controlled retry policy with no retry for contract-validation failures
- Query cancellation propagated to the underlying HTTP request
- Correlation-safe validation diagnostics that never log response payloads
- Existing foreground refresh, background refresh, fallback, source balancing, and degraded-state behavior preserved

## Files reviewed

- `frontend/react/src/App.jsx` alert/landing state, loaders, polling, mutation refreshes, row patches, and visibility behavior
- `frontend/react/src/appHelpers.jsx` request helper, source normalization, source caps, and landing-row mapping
- API gateway `/alerts/all` and `/landing-pad/recent` proxy contracts
- Monitoring adapter alert and landing-pad response implementations
- Existing query provider, routing boundary, browser tests, and technical-debt register

## Files created

- `frontend/react/src/app/queryClient.ts`
- `frontend/react/src/services/queryKeys.ts`
- `frontend/react/src/services/apiClient.ts`
- `frontend/react/src/services/alerts.ts`
- `frontend/react/src/schemas/alerts.ts`
- `frontend/react/src/services/alerts.test.ts`
- `docs/MODERNIZATION_PHASE_2_REPORT.md`

## Files modified

- `frontend/react/package.json`
- `frontend/react/package-lock.json`
- `frontend/react/src/app/providers.tsx`
- `frontend/react/src/App.jsx`
- `frontend/react/docs/TECHNICAL_DEBT.md`

## Architecture decisions

1. TanStack Query owns network acquisition, cache lifetime, deduplication, retry and cancellation for the pilot endpoints.
2. Zod validation occurs before data reaches source balancing or UI components.
3. Both existing response forms remain supported: `{ data: { rows } }` and `{ rows }`.
4. Unknown extra row fields are preserved with `.passthrough()` to maintain backend compatibility; known operational fields are type-checked.
5. Validation failures do not retry and enter the existing error/degraded UI path.
6. Background fetches may reuse data for 45 seconds; explicit foreground actions use `staleTime: 0` and fetch current data.
7. Archive traversal remains impossible through the typed landing-pad service because it never accepts or sends `include_archive=true`.
8. A temporary projection from validated query data into legacy local UI state is documented as TD-FE-003. This preserves synchronous action patches until Alerts/Incidents extraction.

## Existing functionality preserved

- Alert source balancing and per-source cap
- Landing-pad fallback if the primary alert endpoint fails
- Manual refresh and 60-second background refresh
- Hidden-tab polling suspension
- Existing acknowledgement, incident transition, severity override and closure row patches
- All existing authentication, API, and workflow behavior
- Current empty, partial-data and timeout UI behavior

## API contracts affected

None. The frontend now verifies existing contracts but sends the same paths and query parameters.

## MySQL impact

None. No schema, SQL, migration, repository, model, pool, transaction or configuration changes were made. MySQL remains the only relational database. No PostgreSQL or pgvector dependency was introduced.

## Security implications

- No token or credential storage changes
- Alert read endpoints retain existing authentication policy
- Validation logs contain only the endpoint path and issue count
- Response payloads, alert contents, tokens and personal data are not logged
- Cancellation and bounded timeouts limit abandoned requests

## Feature flags added

None. The pilot preserves the existing endpoint and UI behavior and can be rolled back at the frontend boundary without a runtime data migration.

## Tests added

Seven frontend unit tests now pass, including four Phase 2 tests:

- Wrapped and direct response validation
- Malformed-response rejection
- Sensitive-payload exclusion from validation logs
- Concurrent request deduplication
- Query cancellation propagated to `fetch`
- Initial authenticated discovery flow performs exactly one `/alerts/all` request

The complete Playwright suite also passes.

## Commands executed and results

```text
docker ... npm install --package-lock-only   PASS
docker ... npm ci                            PASS
npm run test:unit                            PASS: 7/7
npm run typecheck                            PASS
npm run build                                PASS
npx playwright test                          PASS: 4 passed, 2 live-only skipped
npx playwright test discovery-layout        PASS; `/alerts/all` count = 1
```

Two intermediate type checks identified overly narrow generic Zod input typing. The generic boundary was corrected to accept `unknown` input while preserving typed output; subsequent strict type checking passed.

## Build results and measurements

Phase 1:

- Router/vendor entry: 208.88 KB raw / 68.06 KB gzip
- Legacy application: 558.52 KB raw / 135.76 KB gzip

Phase 2:

- Router/query entry: 237.97 KB raw / 76.57 KB gzip
- Legacy application with typed alert services and Zod: 615.53 KB raw / 148.70 KB gzip
- CSS unchanged: 123.91 KB raw / 22.76 KB gzip

Phase 2 adds correctness and resilience but does not reduce the bundle. Zod and the query client currently cross the legacy compatibility boundary. Page extraction and shared dependency chunking are required before claiming a load-time improvement.

Runtime endpoint performance was not changed by this frontend-only phase. Phase 0 remains the backend latency baseline.

## Screenshots

Not applicable. No visual layout, typography, status color, copy, or interaction design was intentionally changed. The full browser suite and accessibility test validate compatibility.

## Known limitations

- Alert query results are temporarily projected into legacy local state (TD-FE-003).
- Mutations still patch local rows and trigger existing refresh functions instead of directly updating/invalidation-only query cache behavior.
- The Alerts route marker does not yet render an independently extracted page.
- Stale-data timestamps/notices are not yet visible in the UI.
- Pagination and infinite queries are not justified for the capped 150-row operational stream and were not added.
- Existing polling remains until the SSE phase.
- Bundle size increased; route extraction is required.
- The typed schema intentionally validates only stable known fields and preserves additional backend fields.

## Rollback procedure

1. Restore the alert and landing-pad loaders in `App.jsx` to the previous `fetchJson` calls.
2. Remove `QueryClientProvider` from `app/providers.tsx`.
3. Remove `src/app/queryClient.ts`, `src/services/*` Phase 2 files, `src/schemas/alerts.ts`, and their tests.
4. Remove `@tanstack/react-query` and `zod` from package metadata and regenerate the lockfile.
5. Remove TD-FE-003.
6. Run unit tests, type checking, production build and Playwright.

No backend, MySQL, message-bus, authentication, or persisted-data rollback is required.

## Recommended next work

Continue Phase 2 by extracting the Alerts route so components render directly from query selectors, then:

1. Replace local action patches with `setQueryData` and explicit invalidation.
2. Add visible last-updated and stale-data indicators.
3. Add typed pagination only for historical views, not the bounded live stream.
4. Migrate one complex form to React Hook Form + Zod after the read-only extraction is stable.
5. Measure duplicate request count and time-to-actionable content in an instrumented browser run.
