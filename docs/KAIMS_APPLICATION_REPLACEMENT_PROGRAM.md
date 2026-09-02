# KaiMS application replacement program

Status: executable migration plan  
Baseline branch: `fix/canonical-context-rca-vertical-slice-e30250c`  
Baseline commit: `34deee2479dfcd6ca90b9e166327e27f167d69ff`

## Decision

KaiMS will be replaced incrementally behind stable, versioned contracts. The running
application and durable data remain available while each end-to-end capability is
migrated. A big-bang rewrite is rejected because it would simultaneously replace
399 HTTP routes, 29 deployable services, queue consumers, lifecycle state, and the
operator interface without a trustworthy comparison oracle.

The replacement is complete only when the legacy shell and duplicate lifecycle
projections have no runtime consumers. Visual redesign alone is not a completed
migration.

## Audited baseline

| Area | Size / finding |
| --- | --- |
| Backend source | 145 files, about 51,418 code lines |
| AI workbench | 32 files, about 14,263 code lines |
| React source | 163 files, about 30,286 code lines |
| Backend tests | 149 files, about 18,242 code lines |
| Browser tests | 27 files, about 2,297 code lines |
| API surface | 399 FastAPI route declarations |
| Runtime topology | 29 Compose services |
| Largest UI hotspot | `App.jsx`, about 13,096 lines |
| Largest persistence hotspot | `common/repository.py`, about 9,764 lines |
| Duplicate authority | incident status, orchestration metadata, resolution lifecycle, events, and UI reducers |

## Root causes of recurring failures

1. **Multiple truth projections.** Alert, incident, context, RCA, approval, and
   remediation records can independently appear current. The UI has historically
   assembled them client-side, allowing incompatible versions to be shown together.
2. **Weak aggregate contracts.** Large untyped dictionaries cross service and UI
   boundaries. Required identity and version bindings are discovered late.
3. **Distributed lifecycle writes.** Several services initiate state transitions;
   the shared reducer validates part of the lifecycle but is not the sole writer.
4. **Planning is mistaken for execution.** Evidence requirements and connector jobs
   can be created without a durable worker successfully collecting evidence and
   regenerating a bound RCA.
5. **Legacy shell ownership.** Extracted routes still receive most data and actions
   from `App.jsx`; route isolation is therefore visual rather than architectural.
6. **Connector capability ambiguity.** A configured connector, a healthy connector,
   and a connector capable of the requested operation are not consistently separated.
7. **Deployment drift.** Compose, Kubernetes, Azure, and cached local images can run
   different service sets and contracts.

## Target deployable architecture

The source remains modular, but production ownership is reduced to five domains:

1. **Platform API/BFF** — authentication, authorization, operator read models, and
   command submission. No browser orchestration.
2. **Signal intake** — adapters, normalization, deduplication, correlation, and one
   canonical incident identity.
3. **Incident workflow** — the only lifecycle writer; durable evidence collection,
   RCA versioning, approval binding, validation, and recovery coordination.
4. **Integration execution** — least-privileged connectors and remediation workers.
   Every operation is typed, capability-checked, idempotent, and fail-closed.
5. **Intelligence** — model routing, evidence retrieval, grounded analysis, and
   evaluation. AI output is a proposal until bound to accepted evidence.

## Canonical incident contract

Every operator view reads one immutable revision of an incident workspace. It binds:

- incident identity and lifecycle revision;
- latest context snapshot and the snapshot bound to the displayed RCA;
- accepted, rejected, stale, conflicting, and unresolved evidence identities;
- RCA version, grounding decision, citations, hypotheses, and limitations;
- impact assertions and their evidence citations;
- typed resolution plan, policy decision, approval fingerprint, and executor capability;
- execution attempts, rollback state, validation observations, and recovery outcome;
- human tasks with server-assigned identity and audit history.

Scores are computed once by the backend from explicit numerator/denominator sets.
The API returns both sets and the calculation reason. The browser formats scores; it
does not infer evidence membership or readiness.

Commands use optimistic concurrency (`expected_revision`) and idempotency keys. A
command result returns the new workspace revision or a conflict that can be safely
refetched.

## Operator experience

The replacement UI has a stable information hierarchy:

1. incident summary, state, owner, elapsed time, and next required action;
2. authoritative scores with definitions and blockers;
3. task-focused tabs: Summary, Evidence, Analysis, Resolution, Activity, Technical;
4. one primary action per state;
5. provenance beside every assertion, with telemetry, human evidence, and AI
   inference visually distinct;
6. unavailable information stays unavailable and includes a recovery action;
7. background work exposes durable state, last attempt, retry time, and owner.

## Migration phases

### Phase 0 — executable baseline and contract boundary

- Freeze the audited service/route inventory.
- Preserve all current user data and uncommitted repair work.
- Establish the canonical incident command workspace as the compatibility boundary.
- Add contract tests at Python, gateway, TypeScript, and browser layers.

Exit: the same incident revision is visible through the repository, gateway, and UI.

### Phase 1 — incident read model

- Replace dictionary-shaped command payloads with typed versioned models.
- Move all evidence and readiness calculations to the backend.
- Return explicit source/bound/latest snapshot identities and inconsistency blockers.
- Make `/incidents/:id` depend only on this contract.

Exit: the browser performs no evidence counting, RCA binding, or lifecycle inference.

### Phase 2 — durable investigation workflow

- Make the workflow coordinator the only incident lifecycle writer.
- Execute evidence plans through durable jobs with leases, retries, and dead letters.
- Regenerate RCA only from a successfully persisted context snapshot.
- Deduplicate requirements by incident, RCA version, category, and query fingerprint.

Exit: a missing evidence category progresses through observable states and produces
one new bound RCA revision or one actionable human task.

### Phase 3 — grounded RCA and impact

- Introduce typed claims, citations, contradictions, and falsification tests.
- Prevent model text from being accepted as evidence.
- Require independent evidence for causal and impact claims.
- Allow governed human amendment without replacing immutable model output.

Exit: every displayed claim resolves to accepted evidence or is labelled hypothesis.

### Phase 4 — governed resolution

- Generate only catalog-backed typed operations.
- Bind plan, policy, approval, credentials, executor capability, and rollback.
- Remove prose-to-command inference and demo success fallbacks.

Exit: execution cannot start with a stale RCA, stale approval, unsupported operation,
or missing rollback where policy requires one.

### Phase 5 — recovery and learning

- Persist pre-state, post-state, validation targets, observation windows, and outcome.
- Roll back failed validation where the approved plan permits it.
- Create knowledge drafts from the immutable incident record; require governance
  approval before production retrieval.

Exit: recovered status requires measured evidence and an auditable decision history.

### Phase 6 — remaining product surfaces

- Replace inbox, applications, connections, knowledge, approvals, audit, and platform
  health routes with route-owned data adapters and components.
- Retire the legacy application shell, compatibility routes, and duplicate selectors.

Exit: `App.jsx` and `appHelpers.jsx` have no runtime imports.

### Phase 7 — deployment cutover

- Align Compose, Kubernetes, and Azure inventories from one generated manifest.
- Add hermetic signal-to-recovery tests, migration rehearsals, rollback, SLOs, and
  architecture drift checks.

Exit: a clean environment and an upgraded environment pass the same release suite.

## Quality gates for every phase

- Python compile, Ruff, Pyright, migration checksum, and focused/full Pytest.
- TypeScript strict check, ESLint, unit tests, accessibility tests, and production build.
- Contract compatibility tests for one preceding version.
- Tenant isolation, authorization, idempotency, concurrency, and audit tests.
- Failure injection for database, broker, connector, model, and executor outages.
- Docker health checks and fresh-image verification; no cached-image release proof.
- No volume deletion, no fabricated evidence, and no readiness-gate bypass.

## Definition of “error free”

No non-trivial distributed application can truthfully be guaranteed error free. For
this program, release-ready means all specified contracts and tests pass, known
failures degrade safely, state is recoverable, telemetry identifies the failing
boundary, and rollback is rehearsed. Unknown defects remain possible and are handled
through observability, isolation, and reversible delivery.
