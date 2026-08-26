# KaiMS branch recovery report

## Recovery identity

- Target recovery branch: `recovery/kaims-consolidated-main`
- Foundation: `6e524173ad0c752272b6c53518e0cc8108bf820d` (`kaiops/clean/wave9-consolidated`)
- Contaminated backup: `backup/contaminated-main-f11fcac` at `f11fcac6cc5de2c808a4274be15792892689e264`
- Baseline marker commit: `c200ad7` (`chore: establish consolidated recovery baseline`)
- Forbidden lineage checks: `44330b2`, `c11e6dd`, and `e5b0108` are not ancestors of the foundation.

The recovery uses `backend/`, `ai-workbench/`, and `frontend/react/` as canonical owners. The obsolete root `services/` tree is not tracked by the recovery branch. Pre-existing local runtime artifacts (`.env.azure-config.backup` and `ingested_alerts/`) are intentionally excluded from recovery commits.

## Port-assessment matrix

Status meanings: `ALREADY_PRESENT` is equivalent behavior in the consolidated owner; `SUPERSEDED` is a stronger consolidated design; `PORT_REQUIRED` identifies a verified gap; `REJECTED` is contaminated, unsafe, generated, or obsolete behavior.

| Source | Original file | Consolidated equivalent | Intended behavior | Status | Evidence | Test coverage / required test |
|---|---|---|---|---|---|---|
| `84f0ba2` | `.gitignore` | `.gitignore` | Ignore local runtime artifacts | SUPERSEDED | Consolidated ignore policy and canonical layout differ; recovery must not import branch-specific runtime paths. | Recovery hygiene/topology test required |
| `84f0ba2` | `database/migrations/20260826_audit_history_index.sql` | `backend/database/migrations/*`; `backend/src/common/common/database.py` | Index audit-history queries | ALREADY_PRESENT | `idx_audit_logs_resource_action_created`, tenant index, cloud audit indexes, and monitoring audit created-time index already exist. | Migration/schema validation |
| `84f0ba2` | `database/schema.sql` | `backend/database/schema.sql` | Declare audit index | ALREADY_PRESENT | Canonical schema declares audit tenant/action/resource indexes; runtime schema bootstrap declares the composite history index. | Migration/schema validation |
| `84f0ba2` | `docker-compose.yml` | `docker-compose.yml`, `deploy/docker/*` | Repair build contexts and service health wiring | SUPERSEDED | Consolidated Compose targets canonical backend/AI workbench sources and shared reproducible Dockerfiles. | Compose ownership/build-context gate required |
| `84f0ba2` | `frontend/react/src/App.jsx` | route modules plus legacy compatibility shell | Authenticate API calls; evidence-derived UI; block execution without evidence | SUPERSEDED | Canonical API client/session, extracted incident routes, governed evidence view, and server-owned execution policy exist. Porting the monolithic patch would violate the UI migration budget. | Auth, RCA, and architecture-budget tests |
| `84f0ba2` | `frontend/react/src/app/navigation.ts` | same | Separate service controls and navigation | SUPERSEDED | Consolidated navigation has Control Plane, Capabilities, Integrations, role restrictions, and canonical route ownership. | Navigation role/unit tests |
| `84f0ba2` | `frontend/react/src/features/administration/PlatformServiceControl.css` | `PlatformSettings.css` and control-plane route styles | Service-control presentation | REJECTED | The old standalone control panel would create a second control plane. | Control-plane route tests |
| `84f0ba2` | `frontend/react/src/features/administration/PlatformSettings.tsx` | same; cloud-ops routes | Backend-driven platform health and controls | SUPERSEDED | Consolidated platform/cloud operations routes use canonical APIs and role-scoped runtime state. | Backend truth-state and authorization tests required |
| `84f0ba2` | `frontend/react/src/features/incidents/IncidentCommand.tsx` | same | Deep-link incident lookup and explicit technical workspace | PORT_REQUIRED | Durable route exists, but recovery must prove targeted reload, missing-ID state, history navigation, and technical-cockpit separation. | New unit and Playwright navigation coverage required |
| `84f0ba2` | `frontend/react/src/routes/alerts/AlertsRoute.tsx` | same | Route linked alerts to durable incident | PORT_REQUIRED | Route runtime exposes `openIncident`; exact durable-ID/missing-ID behavior needs contract tests. | New alert-to-incident tests required |
| `84f0ba2` | `frontend/react/src/routes/approvals/ApprovalsRoute.tsx` | same | Link approval rows to incident detail | PORT_REQUIRED | Approval runtime has `open`, but exact `/incidents/:incidentId` behavior must be verified without opening the cockpit. | New approval-navigation tests required |
| `84f0ba2` | `frontend/react/src/routes/incidents/RcaPanel.tsx` | same plus `DecisionReadinessPanel.tsx` | Accurately describe evidence and prevent ungrounded readiness | SUPERSEDED | Consolidated evidence governance models freshness, provenance, contradictions, insufficiency, confidence ceilings, and readiness separately. | RCA evidence/governance tests |
| `84f0ba2` | `frontend/react/src/styles.css` | feature-scoped CSS | Disabled/error styling | SUPERSEDED | Consolidated feature routes own their styles; global contaminated UI rules must not be copied. | Visual/interaction unit tests |
| `84f0ba2` | `frontend/react/tests/e2e/live-regenerate-rca.spec.js` | Playwright suite | Verify grounded regeneration | PORT_REQUIRED | Governed backend lifecycle exists; exact version/snapshot and stale-response UI behavior needs E2E proof. | New governed regeneration test required |
| `84f0ba2` | `observability/prometheus.yml` | same plus `observability/*` | Remove invalid scrape targets | REJECTED | Do not import environment-specific target deletion; validate canonical health/build ownership instead. | Compose/health validation |
| `84f0ba2` | `scripts/close_stale_warning_incidents.py` | lifecycle/closure services | Bulk-close stale incidents | REJECTED | Ad-hoc closure bypasses consolidated validation evidence and governed closure lifecycle. | Closure safety tests |
| `84f0ba2` | `services/api-gateway/app.py` | `backend/src/api-gateway/app.py` | Platform health/control APIs and auth | SUPERSEDED | Consolidated gateway provides canonical authorization, audit queue, projections, and platform/cloud API routing. | Gateway auth/control contract tests |
| `84f0ba2` | `services/approval-service/app.py` | `backend/src/approval-service/app.py` | Bind approval to evidence/plan and reject stale requests | SUPERSEDED | Consolidated approval service integrates resolution lifecycle and policy metadata; remaining exact-binding assertions belong in tests, not copied handlers. | Stale/mismatched approval tests required |
| `84f0ba2` | `services/common/common/database.py` | `backend/src/common/common/database.py` | Audit indexes and governed records | SUPERSEDED | Consolidated models include tenant-aware audit, lifecycle, cloud, learning, and projection records. | Schema/migration tests |
| `84f0ba2` | `services/common/common/repository.py` | `backend/src/common/common/repository.py` | Deterministic tenant-scoped audit queries | ALREADY_PRESENT | Canonical repository filters tenant IDs and orders recommendation/audit records deterministically. | Tenant/order repository tests |
| `84f0ba2` | `services/context-agent/context_agent/connectors.py` | `ai-workbench/src/context-agent/context_agent/connectors.py` | Collect attributable evidence | SUPERSEDED | Consolidated context and investigation pipelines use persisted evidence packages rather than the older connector synthesis. | Evidence metadata/RAG validation tests |
| `84f0ba2` | `services/model-router/model_router/router.py` | `ai-workbench/src/model-router/model_router/router.py` | Safe fallback/model routing | SUPERSEDED | Canonical router redacts secrets and feeds governed model usage into the consolidated investigation. | Model-router/security tests |
| `84f0ba2` | `services/monitoring-adapter/app.py` | `backend/src/monitoring-adapter/app.py` | Surface processed evidence/RCA state | SUPERSEDED | Canonical adapter participates in consolidated ingestion/projection contracts. | API contract tests |
| `84f0ba2` | `services/resolution-agent/resolution_agent/graph.py` | `ai-workbench/src/resolution-agent/resolution_agent/*` | Abstain without evidence and reduce confidence | SUPERSEDED | Canonical evidence and confidence modules represent provenance/freshness/contradictions and impose missing/stale evidence ceilings. | Missing/conflicting evidence and label-not-cause tests |
| `84f0ba2` | `tests/test_context_resolution_flow.py` | backend/AI workbench test suites | Prove evidence propagation | SUPERSEDED | Consolidated workflow is materially different; tests must target canonical contracts rather than old service paths. | Recovery-specific lifecycle tests required |
| `1a635da` | `docker-compose.yml` | `docker-compose.yml` | Configure authentication mode | SUPERSEDED | Consolidated configuration and OIDC/local-development boundaries own auth settings. | Deployment environment validation |
| `1a635da` | `frontend/react/src/app/navigation.ts` | same | Isolate audit workspace | PORT_REQUIRED | `/audit` exists but currently shares `legacyTab: safety`; `/admin/settings` is not an explicit canonical route. | Audit/admin route isolation tests required |
| `1a635da` | `frontend/react/src/routes/audit/AuditRoute.css` | audit/gateway feature styles | Dedicated audit presentation | PORT_REQUIRED | Current audit route delegates to a combined gateway view; immutable tenant-scoped audit deserves an isolated route without duplicating storage. | Audit route tests required |
| `1a635da` | `frontend/react/src/routes/audit/AuditRoute.tsx` | same | Dedicated audit ledger | PORT_REQUIRED | Current route renders `GatewaySafetyView mode="audit"`; separation is incomplete. | Audit route isolation/pagination tests required |
| `1a635da` | `frontend/react/tests/e2e/navigation-routing.spec.js` | Playwright suite | Prove audit and auth routing | PORT_REQUIRED | Canonical router exists, but bootstrap-before-protection and audit/admin isolation need explicit E2E assertions. | New auth/navigation E2E tests required |
| `1a635da` | `services/api-gateway/api_gateway/modules/users/router.py` | `backend/src/api-gateway/api_gateway/modules/users/router.py` | Publish safe auth bootstrap configuration | SUPERSEDED | Consolidated user service binds access tokens to active server-side sessions and tests revoked sessions; OIDC client/config abstractions already exist. | Valid/expired/revoked/deep-link auth tests |
| `f11fcac` | `frontend/react/src/App.jsx` | route runtime, `router.tsx`, incident routes | Durable incident navigation | PORT_REQUIRED | `/incidents/:incidentId` exists and uses React Router, but all entry points and missing-ID behavior need one canonical helper and tests. | Summary, inbox, reload, back/forward, missing-ID tests required |

## Phase 2 conclusions

No application implementation from the contaminated commits should be cherry-picked. The only required work is narrow and must use consolidated owners:

1. Add one durable incident-navigation contract and apply it to summary, inbox, alert, audit, and approval entry points.
2. Separate `/audit` from gateway automation/safety and expose `/admin/settings` distinctly while retaining the consolidated two-role server authorization model.
3. Add recovery-focused tests around the already consolidated RCA, approval, remediation, rollback, closure, audit, and authentication contracts; change production behavior only where those tests reveal a real gap.
4. Extend CI with topology/ancestry, canonical-frontend, Compose ownership, critical Playwright, environment, health-check, and credential-manifest gates.

## Remaining gates and promotion

Phase 3A and 3B are implemented on the recovery branch with durable navigation, protected-session bootstrap, and isolated audit/admin routing. Phase 3C now enforces explicit evidence scope/provenance fields, adversarial RCA abstention and conflict behavior, generation-specific immutable context snapshots, recommendation-to-snapshot version binding, and stale-response rejection in the frontend.

Phase 3C validation evidence:

- Governed RCA, confidence, investigation, snapshot, and event-contract tests: 32 passed.
- Frontend ESLint, architecture budget (13,598/13,600), TypeScript, and unit suite: 105 passed across 24 files.
- Python compilation of every changed RCA/context module and test: passed.
- A standalone latest-Ruff probe reported pre-existing whole-file formatting debt in legacy modules; no lint rule or configuration was weakened. The canonical repository lint gate remains required in Phase 5.

Phase 3D binds the fingerprinted execution plan and approval receipt to the tenant, incident, RCA version, evidence snapshot, recommendation version, target, connector, and rollback plan. The service rejects stale recommendation identities, incident/tenant mismatches, altered plans, expired plans, missing readiness controls, and non-opaque credential values. Gateway authorization remains the source of approver identity and role. Approval/lifecycle/idempotency validation: 40 passed.

Phase 3E re-verifies the complete governance binding before remediation, rejects target/connector/rollback drift and invalid fingerprints, preserves duplicate-execution prevention, and requires rollback to reference both the persisted approval and an intact original execution contract. The derived rollback is independently fingerprinted and contract-bound. Closure additionally requires the original RCA, evidence snapshot, and recommendation bindings alongside independent validator observations and the stability window. Remediation/rollback/closure validation: 52 passed.

Phase 4/5 eliminates mixed-baseline regressions with a repository topology validator and makes that validator part of both backend and deployment CI. CI now requires the locked backend dependency set, Ruff, the complete backend suite, RAG/catalog/readiness validation, frontend ESLint/type/architecture/unit/build/bundle gates, critical authenticated incident Playwright journeys, dependency audits, resolved Compose configuration, canonical service and React image builds, and Kubernetes client dry-run. The topology gate rejects a second frontend, an obsolete root service tree, a competing Streamlit production UI, missing canonical build inputs, and literal credential-like values in Kubernetes manifests.

The recovery branch is not eligible for promotion until every mandatory backend, frontend, Playwright, Compose, Kubernetes, security, ancestry, and architecture gate passes. Promotion must occur through review of `recovery/kaims-consolidated-main`; `main` must not be force-pushed or replaced.
