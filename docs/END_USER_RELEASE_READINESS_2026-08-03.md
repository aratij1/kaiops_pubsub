# KaiMS end-user release readiness

Date: 2026-08-03

## Release decision

**Code-ready; operational production approval remains conditional.** Automated backend, deterministic UI,
accessibility, dependency-security, build, bounded-load and strict durable-delivery gates are green. An unrestricted
production launch still requires the production-equivalent soak, disruption, tenant-isolation and recovery exercises
listed below; a controlled staging or pilot release is now appropriate.

## Test evidence

| Gate | Result | Evidence / interpretation |
|---|---:|---|
| Production UI build | PASS | Vite build completed; 676.82 kB JS (173.94 kB gzip), with a >500 kB chunk warning |
| Production dependency audit | PASS | `npm audit --omit=dev`: 0 vulnerabilities; unused vulnerable `xlsx` dependency removed |
| Full backend suite | PASS | 279 passed before the final corrected workflow expectation; corrected workflow suite then passed 3/3 |
| Hermetic configuration | PASS | Pytest settings no longer inherit credentials, database/bus modes or tuning values from the developer `.env` |
| Live browser: alert detail cockpit | PASS | Deployed Nginx UI and API stack |
| Live browser: RCA regeneration | PASS | Deployed stack; completion or explicit backend state shown |
| Deterministic browser: admin setup | PASS | Current guided setup, file input, Azure fields and adapter capability labels |
| Deterministic browser suite | PASS | Admin setup, discovery and accessibility: 3 passed; 2 live-only scenarios explicitly skipped in deterministic mode |
| Accessibility | PASS | axe found no serious or critical violations on login and the primary workspace |
| Bounded API stress | PASS | 500 requested, 500 accepted, 0 failed, concurrency 25, 16.34 alerts/sec |
| Post-stress service availability | PASS | Core services remained running; gateway/MySQL/RabbitMQ/Redis healthy |
| Monitoring pipeline sanity | PASS | Metric present (4764), Prometheus firing, Alertmanager present, gateway queue populated |
| Monitoring strict named lookup | PASS | Durable `/alerts/all` fallback found the named alert among 5,000 rows after load; metric, Prometheus and Alertmanager checks also passed |
| Context responsiveness | PASS after fix | Concurrent large RAG catalog + lightweight request: HTTP 200, lightweight latency 919 ms |

## Defects fixed during readiness testing

1. Removed a stray token that made `monitoring-adapter/app.py` syntactically invalid and prevented service startup.
2. Bounded landing-pad filenames to avoid `ENAMETOOLONG` and lost alerts.
3. Restored backward-compatible Alertmanager response fields (`ingested`, `alerts`) and failure reason semantics.
4. Restored merged live/archive landing-pad views when `include_archive=true`.
5. Moved the large synchronous RAG document projection off the context-agent event loop.
6. Updated browser acceptance journeys for the current guided setup, tabs, evidence governance and visible uncertainty.
7. Made backend tests independent from the repository `.env` and corrected current connector, model-router, RAG and embedding contracts.
8. Fixed Azure embedding HTTP injection/fallback behavior and prevented an unconfigured OpenAI fallback hop.
9. Added axe accessibility coverage and fixed invalid tablist semantics plus keyboard access to the scrollable alert table.
10. Removed the unused vulnerable `xlsx` package and verified the production dependency audit is clean.
11. Separated live-stack Playwright journeys from deterministic mocked acceptance tests.
12. Made strict pipeline verification fall back from the bounded recent feed to the durable database-backed alert feed.

## Remaining release blockers

1. Add latency percentile and resource measurements to stress tests. Acceptance count alone does not prove an SLO.
2. Run soak (hours), burst, broker restart, database restart, DLQ/replay, multi-tenant isolation, rollback and backup
   restore tests in a production-equivalent environment.
3. Run the two `KAIOPS_LIVE_E2E=1` browser journeys from an environment with network access to the deployed API on every release candidate.
4. Split/lazy-load the 18,000-line UI module. The production bundle warning and slow development transpilation make
   regression testing fragile and increase initial-load risk on weak client devices.

## End-user experience assessment

The current deployed UI supports login, application selection, live incident stream, detail cockpit, evidence/context,
RCA regeneration state, guided administration and approval/remediation visibility. It correctly exposes uncertainty
and suppresses an RCA when fixture evidence contradicts the proposed diagnosis. Keyboard access and critical/serious
axe findings are now clean. The main remaining experience risk is initial load and regression-test cost caused by the
monolithic frontend bundle.

## Production gate

Release only when all of the following are true:

- full backend suite is green in a sanitized test environment;
- all four browser journeys pass twice consecutively against built assets, plus accessibility checks;
- strict ingestion-to-durable-query verification passes after load;
- rollback, replay, broker/database disruption and tenant-isolation scenarios pass;
- target SLOs are defined and p95/p99 latency, error rate, CPU and memory remain within them during soak;
- migration backup/restore and application rollback are rehearsed;
- no real provider credentials are present in test runners or captured logs/artifacts.

## Rollback

The production-code changes are localized. Roll back the context-agent image to restore its prior route execution mode,
or the monitoring-adapter image to revert ingestion changes. The new database migration from the earlier Phase 1
increment is additive and should remain in place during application rollback; dropping tables is not required and must
be a separately approved maintenance action.
