# KaiOps modernization: Phase 0 baseline

Date: 2026-08-04 (Asia/Calcutta)

## Scope and constraints

This baseline records the repository before the TypeScript route-module work. React/Vite, FastAPI, Python 3.12, Pydantic, SQLAlchemy, MySQL, Redis, existing HTTP contracts, authentication behavior, and the current message-driven workflow remain compatibility constraints. PostgreSQL and pgvector are explicitly out of scope.

The worktree contained extensive pre-existing modifications. They are treated as user-owned and are not reverted. In particular, `App.jsx` had already been partially reduced by extracting helpers to `appHelpers.jsx`.

## 1. Current architecture map

```text
Browser
  -> nginx/Vite SPA (React 18, JavaScript, tab-state navigation)
  -> FastAPI API gateway
       -> monitoring adapter / onboarding / approval and other HTTP services
       -> MySQL through async SQLAlchemy repositories
       -> Redis for short-lived state and coordination

Alert sources
  -> monitoring adapter + filesystem landing pad
  -> deployment-selected message bus (RabbitMQ by default)
  -> alert intelligence
  -> orchestrator
  -> context agent + discovery MCP + knowledge documents
  -> resolution agent + model router
  -> approval service
  -> remediation engine
  -> closure service
  -> MySQL projections, audit, notifications and UI

Telemetry
  -> OpenTelemetry instrumentation + Prometheus
  -> Grafana dashboards and Alertmanager
```

Docker Compose declares 62 services including KaiOps, observability infrastructure, and two demonstration applications. At measurement time, 33 containers were running; 23 were KaiOps application/UI containers. Only four running containers declare Docker health checks, leaving significant readiness visibility gaps.

## 2. Route and navigation inventory

The frontend has no URL router at baseline. `App.jsx` owns an `activeTab` state, persists it in `kaiops.ui.preferences.v1`, and conditionally renders pages. Refresh/bookmark behavior therefore depends on local storage rather than the URL.

| Tab ID | Current label | Roles | Existing URL |
|---|---|---|---|
| `home` | Dashboard | all roles | `/` only |
| `stream` | Alert Ingestion Stream | all roles | `/` only |
| `copilot` | Copilot Studio | L2/L3/admin/executive | `/` only |
| `executive` | Executive Dashboard | L3/admin/executive | `/` only |
| `admin` | Admin Center | administrator | `/` only |
| `trace` | Agent Flow | L2/L3/admin/executive | `/` only |
| `safety` | Gateway Safety | L2/L3/admin/executive | `/` only |
| `rag` | Message Bus | L2/L3/admin/executive | `/` only |
| `closed` | Closed Tickets | L2/L3/admin/executive | `/` only |
| `summary` | Incident Metadata Explorer | L2/L3/admin/executive | `/` only |
| `approval` | Approval Queue (Legacy) / Human Approval | L2/L3/admin/executive | `/` only |

The full tab list and the five-item sidebar are separate definitions. Role permissions live in `onboardingConfig.js`; keyboard shortcuts and valid-tab metadata live in `appHelpers.jsx`. This duplication is the primary navigation drift risk.

## 3. Frontend dependency and state map

- React 18.3 and ReactDOM 18.3
- Vite 5.4 and the React plugin
- TanStack Virtual for long alert lists
- Playwright and axe-core for browser/accessibility tests
- No TypeScript, URL router, TanStack Query, Zod, React Hook Form, Storybook, Vitest, or component-test runner at baseline
- Server state is stored manually across many `useState` values and loaded through a shared `fetchJson` helper
- 69 `fetchJson` call sites are present in `App.jsx`
- Two visible-data polling loops run every 60 seconds; a third interval is a stuck-request watchdog
- No `EventSource` or WebSocket implementation was found
- Authentication tokens are held in React memory; UI preferences, not tokens, are stored in local storage

Relevant source sizes at baseline:

| File | Lines/bytes |
|---|---:|
| `App.jsx` | 12,506 lines / 612,921 bytes |
| `appHelpers.jsx` | 6,902 lines / 309,316 bytes |
| `styles.css` | 7,334 lines / 143,185 bytes |

The deployed production bundle contained a 676,797-byte main JavaScript asset (173,940 bytes gzip in the last successful production build).

## 4. Backend service inventory

| Domain | Services and responsibilities |
|---|---|
| Edge/API | `api-gateway` (90 direct routes), authentication/RBAC, aggregation and proxying |
| Intake | `monitoring-adapter` (63 routes), monitoring ingestion, Jira/email/log intake, landing pad and archive; `monitoring-ingestion-worker` |
| Intelligence | `alert-intelligence`, classification/deduplication/correlation |
| Orchestration | `orchestrator`, workflow selection and context dispatch |
| Context | `context-agent` (17 routes), `discovery-service`, `discovery-mcp` |
| AI | `model-router`, `resolution-agent`, `evaluation-service` |
| Decision/action | `approval-service`, `remediation-engine`, `closure-service`, `notification-service` |
| Onboarding | `application-onboarding`, `metrics-validation-agent`, `rule-generation-agent`, `prometheus-config-service`, `validation-agent`, `dashboard-generator`, `audit-service` |

There are 198 directly decorated FastAPI operations in the inspected `app.py` entrypoints. Router modules included by the API gateway add further operations.

## 5. Message-bus usage map

The common layer implements RabbitMQ, Kafka, and Azure Service Bus producers/consumers. Deployment configuration selects the provider at startup; RabbitMQ is the default and Kafka is disabled by default. Business services still import provider-specific implementations through common service wiring, so the abstraction is incomplete.

Primary incident topics:

```text
raw-alerts
  -> enriched-alerts
  -> orchestration-events
  -> context-events
  -> resolution-events
  -> approval-events
  -> remediation-events
  -> closure-events / projections and notifications
```

Onboarding uses a separate chain from `application.onboard.requested` through discovery, metrics validation, rule generation, Prometheus update, validation, and dashboard creation. Each RabbitMQ service/topic consumer has its own durable queue and DLQ.

Queue baseline: five ready messages in `kaiops.orchestrator.enriched-alerts.dlq`; all other inspected queues had zero ready/unacknowledged messages. Queue age is not exported by the current CLI baseline and remains a measurement gap.

## 6. MySQL persistence map

MySQL 8.4 is the configured primary database through `mysql+aiomysql`. SQLAlchemy uses async sessions, `pool_pre_ping`, configurable pool size/overflow/timeout/recycle, and a database circuit breaker.

Core persistence groups:

- Incidents: `alerts`, `incidents`, `incident_events`, `incident_projections`, `canonical_tickets`, `ingestion_events`
- Decisions/actions: `approvals`, `actions`, `pending_workflows`, `agent_work_items`
- Intelligence: `rca_reports`, `knowledge_base`, `context_knowledge`, `evaluation_records`
- Identity/audit: `roles`, `users`, `user_sessions`, `audit_logs`
- Applications/onboarding: applications, environments, labels, monitoring profiles, Prometheus/rule/dashboard/history records, `onboarding_state`
- Integrations: monitoring integrations, credentials, webhooks, mappings, connection health, received/normalized alerts and connection audit
- External correlation: `jira_ticket_links`, connector definitions

The authoritative schema and migrations remain MySQL. Phase 1 makes no schema, migration, repository, connection, or engine changes.

## 7. Authentication flow

1. Browser posts username/password/device to `/api-gateway/auth/login`.
2. API gateway validates the user against MySQL and returns access and refresh JWTs plus role data.
3. Tokens remain in React memory; authenticated calls attach a bearer token.
4. On access expiry, the UI calls `/api-gateway/auth/refresh` and retries.
5. Logout calls the backend and clears in-memory tokens.
6. Backend validates JWT signatures and enforces permission dependencies; frontend tab visibility is an additional usability control, not the security boundary.

Development defaults exist in Compose for users, passwords, and the JWT secret. Production OIDC and insecure-secret startup enforcement are not implemented at baseline.

## 8. Archive-storage flow

The monitoring adapter writes raw/normalized landing-pad files under `backend/ingested_alerts`. File watchers claim inputs, ingest them, and move replayed/failed files. A background archive sweeper recursively moves aged processed/failed JSON files into source/date archive directories.

The live `/landing-pad/recent` path uses bounded in-memory/input snapshots when `include_archive=false`. With `include_archive=true`, it scans archive files. The interactive UI was already changed to avoid the archive flag, but archive APIs still walk the filesystem.

Measured latency:

- `/landing-pad/recent?limit=100`: 0.518s, 208,180 bytes
- `/landing-pad/recent?limit=200&include_archive=true`: 16.153s, 486,808 bytes

## 9. Current incident workflow

1. Prometheus/Alertmanager, Jira, email, log, telemetry, or landing-pad input is normalized by the monitoring adapter.
2. Alert/audit state is persisted and `raw-alerts` is published.
3. Alert intelligence classifies, deduplicates, correlates, and publishes `enriched-alerts`.
4. Orchestrator selects immediate or continuous/context-knowledge behavior and publishes `orchestration-events`.
5. Context agent reuses tenant-scoped context knowledge when valid or performs discovery/RAG, persists context, and publishes `context-events`.
6. Resolution agent invokes the model router, persists RCA/impact/recommendation, and publishes `resolution-events`.
7. Approval service records a decision and publishes `approval-events` when execution is authorized.
8. Remediation engine applies safety/idempotency controls, executes the selected plugin, persists action state, and publishes `remediation-events`.
9. Closure service validates the outcome and updates incident projections/closure state.
10. Audit and notification consumers observe relevant events throughout the flow.

## 10. Baseline measurements and validation

| Measurement | Baseline |
|---|---:|
| UI HTML | 0.846s / 418 bytes |
| API health | 0.085s |
| `/alerts/all?limit=200` | 2.667s / 552,895 bytes |
| Live landing-pad query | 0.518s |
| Archive-inclusive query | 16.153s |
| Main deployed JS | 676,797 bytes |
| Frontend API call sites | 69 |
| Live polling | two 60-second loops |
| Python test files/functions | 61 / 309 |
| Playwright specs/tests | 6 / 6 |
| Coverage configuration | absent |
| Running containers | 33 |
| Running KaiOps app containers | 23 |
| RabbitMQ ready/unacknowledged | 5 / 0 |

Main dashboard render time, browser request/duplicate count, long-list frame rate, backend CPU/memory, MySQL query percentiles, queue age, and test coverage percentage are not instrumented in the current baseline. They must be added before claiming improvements in those dimensions.

Baseline build result: **failed before compilation** because `package.json` and `package-lock.json` are out of sync for TanStack Virtual. The host also lacks `npm` on PATH; containerized Node is the reproducible build path. No lint, TypeScript check, unit-test, or Storybook scripts exist yet.

## Architecture decisions for Phase 1

1. Add strict TypeScript and React Router without rewriting legacy page content.
2. Introduce a small `app/App.tsx`, providers, authoritative navigation metadata, and lazy route modules.
3. Keep `App.jsx` as an explicitly documented compatibility boundary while pages are extracted incrementally.
4. Route modules select the existing tab through a typed legacy adapter, preserving behavior and APIs.
5. Preserve `/` as Dashboard and add stable paths for existing destinations; redirect the legacy approval path.
6. Do not introduce TanStack Query/Zod/forms until Phase 1 routing compiles and browser behavior passes.
7. Do not change backend code or MySQL in Phase 1.

## File-level phased implementation plan

### Phase 1

- Add `tsconfig*.json` and TypeScript/Vite declarations.
- Replace the entrypoint with `main.tsx`.
- Add `src/app/{App,router,navigation,permissions,providers}.tsx/ts`.
- Add lazy modules under `src/routes/*` using a documented legacy adapter.
- Add redirects for legacy tab names and tests for navigation metadata.
- Keep `src/App.jsx` and helper modules until individual page extraction reaches parity.

### Phase 2-5

- Add TanStack Query/Zod API domains and migrate one read-only page at a time.
- Establish one accessible component system after a bundle/accessibility spike; do not mix systems.
- Create tokens/shared components and Storybook.
- Extract long pages into task sections while retaining the legacy adapter as rollback.

### Phase 6-10

- Add role-aware queries/views, alert master-detail, incident/approval sections, AI evidence presentation, search/my-work typed adapters, and feature flags for missing APIs.

### Phase 11-19

- Pilot Temporal behind a workflow flag; standardize the deployment-selected bus; document consolidation candidates; add object-storage metadata in MySQL; pilot SSE; add OIDC; expand OpenTelemetry; add Azure Container Apps assets.

### Phase 20-22

- Complete WCAG/responsive verification, performance profiling, degraded states, visual regression, recovery/load/security testing, and rollback drills.

## Risks, dependencies, and rollback

- **Dirty worktree:** isolate new files and minimal entry/App edits; never revert unrelated changes.
- **Router/auth lifetime:** keep one legacy application instance under the route adapter so navigation does not discard in-memory JWTs.
- **Bookmark compatibility:** `/` remains valid; new paths are additive; unknown paths redirect to `/`.
- **Permission drift:** one navigation definition becomes authoritative, but backend RBAC remains the security boundary.
- **Bundle regression:** route modules are lazy; measure output after each extraction.
- **Lockfile drift:** regenerate the lockfile through containerized npm and require `npm ci` to pass.
- **Rollback:** restore `main.jsx` as the Vite entrypoint and remove the new TypeScript/router files and dependencies. No backend, API, MySQL, or persisted-data rollback is required for Phase 1.

