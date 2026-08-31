# KaiMS Phase 9 Gap Analysis

Date: 2026-08-24  
Baseline: `df335b6` (`fix/kaims-resolution-production-readiness`) after fetching `origin`  
Method: static inspection of service code, shared contracts, SQL schema/migrations, React routes, tests, Compose configuration, and existing architecture/release reports. A filename or class alone was not treated as a working capability.

## Classification

- `EXISTS_AND_REUSE`: implemented with a usable contract and tests or an exercised runtime path.
- `EXISTS_NEEDS_EXTENSION`: useful implementation exists but does not meet the Phase 9 production contract.
- `PLACEHOLDER`: interface, simulated result, sample/default data, or fail-closed seam exists without a production integration.
- `MISSING`: no cohesive implementation was found.
- `DEPRECATED`: retained for compatibility but should not drive new behavior.

## Executive finding

KaiMS is not a blank prototype. It already has a substantial incident lifecycle, tenant-aware persistence, evidence-bearing RCA contracts, guarded execution plans, approval binding, idempotency controls, rollback/validation seams, onboarding APIs, and a React operations UI. Phase 9 should extend these foundations rather than introduce a parallel platform.

The largest structural gaps are a canonical operational digital twin, a provider-neutral connector hub and secret-provider abstraction, a complete capability registry, a unified evidence/change graph, the two-role authorization migration, and end-to-end readiness coverage across the requested technology matrix. Several current integrations are deliberately configuration-gated or simulated and must not be represented as production-ready.

## Capability matrix

| Capability | Classification | Evidence and actual state | Required increment |
| --- | --- | --- | --- |
| Application onboarding | `EXISTS_NEEDS_EXTENSION` | `backend/src/application-onboarding/app.py`, monitoring onboarding contracts, persisted onboarding migrations, and frontend onboarding utilities exist. | Evolve to a resumable 12-step project wizard, readiness gates, connector-driven discovery, and production autonomy blocking. |
| Discovery service | `EXISTS_NEEDS_EXTENSION` | Both `discovery-service` and `discovery-mcp` exist; discovery evidence is persisted and distinguishes missing evidence. | Normalize discovered assets into stable resource identities and verified relationships; expose provenance and last verification. |
| Operational digital twin | `MISSING` | Cloud resource records and discovery reports exist, but the requested canonical resource hierarchy and relationship vocabulary are not implemented as one model. | Add normalized resources/relationships, deterministic identity, tenant/project scoping, provenance, confidence, evidence, and verification timestamps. |
| Monitoring adapter | `EXISTS_AND_REUSE` | Real alert intake, monitoring-source onboarding, dedup/event flow, and connector credential references exist with tests. | Add uniform ConnectorPlugin-backed telemetry methods and coverage/readiness calculations. |
| Alert intelligence | `EXISTS_AND_REUSE` | Correlation, incident persistence, event handoff, and tests exist. | Feed graph identity/change correlation into grouping and measure noise-reduction quality. |
| Context and RAG | `EXISTS_NEEDS_EXTENSION` | Context service, governed RAG corpus, discovery evidence, provenance labels, and knowledge lifecycle are implemented. | Introduce KnowledgeSource records, source freshness policies, graph linkage, and broader deterministic collectors. |
| Orchestrator | `EXISTS_NEEDS_EXTENSION` | Workflow decisions, state contracts, policy seams, and Temporal integration exist. | Orchestrate the full Observe-to-Learn lifecycle using versioned canonical events and bounded retry/escalation. |
| Resolution agent | `EXISTS_NEEDS_EXTENSION` | Evidence-grounded recommendations, hypothesis persistence, contradicting evidence, execution-plan compilation, and confidence handling exist. | Make capability selection the only remediation output; remove residual command-shaped compatibility paths and require digital-twin target resolution. |
| Evidence graph / causal RCA | `EXISTS_NEEDS_EXTENSION` | Investigation steps and multiple hypotheses with supporting/contradicting evidence are persisted in `common/repository.py`; the incident UI exposes evidence quality. | Create an explicit graph model/API, causal paths, data gaps, topology/change edges, and source drill-down. |
| Change intelligence | `PLACEHOLDER` | RAG change/deployment documents and some connector/change seams exist, but no canonical `ChangeEvent` collection and scored topology/time/resource correlation pipeline was found. | Add collectors, canonical events, correlation scoring, persistence, API, and UI. |
| Approval service | `EXISTS_AND_REUSE` | Tenant-scoped approvals, plan/checksum binding, authorization scope, reviewer capacity, and tests exist. | Adopt the two-role model and the complete decision-centric approval projection. |
| Remediation safety | `EXISTS_AND_REUSE` | `safe_remediation.py` enforces registered capability, scoped credential, target identity, preflight evidence, dry-run evidence, and verified blast radius. Approval-plan binding and idempotency tests exist. | Centralize risk formula/configuration and enforce all Phase 9 HITL gates consistently across legacy and cloud paths. |
| Capability registry | `EXISTS_NEEDS_EXTENSION` | `CapabilitySpec` and execution-plan capability identities exist; remediation plugins expose bounded operations. | Add a durable/queryable registry with JSON schemas, permissions, environment limits, blast-radius ceilings, approval level, validation, rollback, and trust tier. |
| Remediation executors | `EXISTS_NEEDS_EXTENSION` | Jenkins and other strategy plugins, execution contracts, precheck/dry-run/idempotency/rollback seams, and tests exist. Missing configuration fails closed. | Complete real Kubernetes, Ansible, Jenkins, Terraform, database diagnostic, and API executors with retry, timeout, circuit breaker, validation, and audit parity. |
| Arbitrary command prevention | `EXISTS_NEEDS_EXTENSION` | Safe execution planning and registered-operation checks exist, but command-shaped legacy/runbook translation remains in `execution_plan.py`. | Quarantine legacy translation to recommendation-only compatibility; autonomous paths must accept registry capability IDs and typed parameters only. |
| Closed-loop validation | `EXISTS_NEEDS_EXTENSION` | Closure/validation services, validation evidence, rollback contracts, lifecycle states, and tests exist. | Standardize the requested validation states, multi-signal ValidationPlan, bounded autonomous attempts, recollection, and escalation. |
| Learning | `EXISTS_AND_REUSE` | Learning contracts require validation evidence for recovered outcomes and implement evidence thresholds for autonomy promotion. | Persist the complete Incident Learning Record and rank future plans without automatic one-shot promotion. |
| Secret references | `EXISTS_AND_REUSE` | Schema and runtime contracts use `secret_ref`/credential references; remediation refuses missing injected credentials. | Retain this invariant and prohibit secrets in connector payloads and logs. |
| SecretProvider abstraction | `MISSING` | Environment injection and reference conventions exist, but no unified local/AWS/Azure/GCP/Vault provider interface was found. | Add provider protocol, resolver registry, metadata-only API, caching/rotation rules, and provider tests. |
| Connector hub | `MISSING` | Provider-specific monitoring, discovery, cloud-operation, and remediation code exists in separate services. | Create `backend/src/connector-hub`, a common ConnectorPlugin contract, dynamic metadata/capabilities, and backwards-compatible adapters. |
| Production connector breadth | `PLACEHOLDER` | Some providers have real paths; many requested providers are represented only by UI choices, generic endpoints, configuration seams, or `NotImplementedError` paths. | Implement and integration-test providers incrementally; label each connection as connected, failed, insufficient permission, unavailable secret, or pending. |
| Event contracts | `EXISTS_NEEDS_EXTENSION` | Canonical topics, event models, envelope JSON schema, correlation/causation fields, and idempotency tests exist. | Require the complete v1 envelope at every boundary, add consumer inbox/DLQ/replay conformance, and prevent duplicate execution globally. |
| Audit and notification | `EXISTS_AND_REUSE` | Dedicated services and lifecycle audit/event paths exist. | Extend connector, policy, graph, validation, and learning events; ensure redaction and tenant isolation. |
| Role model | `DEPRECATED` | Application logic still authorizes Administrator, Executive, L1, L2, and L3 roles throughout gateway and closure paths. | Introduce `ADMIN` and `HITL_APPROVER`, map legacy roles during migration, then remove legacy roles from new authorization decisions. |
| Incident workspace | `EXISTS_NEEDS_EXTENSION` | Incident, RCA, resolution, evidence, execution, and verification components exist, but remain split across routes/panels. | Compose one lifecycle workspace with story, impact, graph, changes, hypotheses, plan, governance, execution, validation, and learning. |
| Operations Copilot | `EXISTS_NEEDS_EXTENSION` | A Copilot route exists and warns users to verify output. | Ground answers in graph/evidence APIs, expose provenance and safety explanations, and keep all execution behind normal policy/approval APIs. |
| Readiness dashboard | `PLACEHOLDER` | Some onboarding/readiness concepts and UI summaries exist, but no complete real-signal operational/autonomy score across all required dimensions was found. | Define explainable scoring, missing-data behavior, hard production gates, and recommendations. |
| KaiMS observability | `EXISTS_NEEDS_EXTENSION` | OpenTelemetry collector/config and service telemetry utilities exist; observability services are optional profiles. | Standardize lifecycle traces and the requested LLM, connector, queue, RCA, approval, automation, validation, MTTR, and false-automation metrics. |
| Frontend design system | `EXISTS_NEEDS_EXTENSION` | Reusable components and Storybook stories exist under `components/design-system`, not the requested canonical directory; legacy global CSS and hardcoded styling remain. | Consolidate under `frontend/react/src/design-system`, add complete tokens/themes/patterns, and migrate screens incrementally. |
| Brand configuration | `MISSING` | User-visible KaiMS/KaiOps naming and styling remain mixed. | Add centralized brand metadata/tokens and document user-visible rename vs internal compatibility identifiers. |
| Navigation/command center | `EXISTS_NEEDS_EXTENSION` | Route-based operations UI exists. | Hide internal service architecture, apply the target IA, add real-data command center and global Ctrl/Cmd+K navigation. |
| Accessibility/responsive quality | `EXISTS_NEEDS_EXTENSION` | Accessibility and responsive Playwright coverage exists, but current test artifacts show prior failures and do not cover all Phase 9 states/pages. | Enforce WCAG 2.2 AA, reduced motion, keyboard/focus, and loading/empty/error/success/denied/partial states in CI. |
| Required scenario suite | `EXISTS_NEEDS_EXTENSION` | Strong unit coverage exists for incident, approval, remediation safety, idempotency, rollback, monitoring onboarding, and unified workflow. | Add the complete Kubernetes/database/Kafka/VM/dependency/credential/ambiguous-RCA/HITL/autonomy E2E matrix. |

## Confirmed placeholders and compatibility risks

1. `backend/src/cloud-operations/app.py` deliberately catches `NotImplementedError`; unsupported provider operations are not real integrations.
2. Connector executors fail closed when endpoint, job, target, or injected secret is absent. This is a safety seam, not evidence that each named provider works.
3. Generic onboarding URLs and provider selections do not prove connection, permission, discovery, or remediation support.
4. Sample/demo flows, mocked test responses, dry-run output, and simulation endpoints must never be counted as live execution or telemetry.
5. Legacy L1/L2/L3 and Executive roles are active authorization inputs, so the requested two-role model is not complete.
6. Existing `KaiOps` backend identifiers, Compose project/image names, topic names, and database values should remain `INTERNAL_KEEP` until an explicit migration proves renaming is safe.

## Reuse boundaries

The following should be extended in place: tenant repositories and migrations, incident projections/timeline, canonical topic module, evidence and hypothesis persistence, guarded execution contracts, approval-plan binding, idempotency and rollback logic, learning promotion thresholds, monitoring ingestion, gateway authentication/audit, and existing React incident components.

New services or modules should integrate through those contracts. They must not introduce a second incident store, a parallel approval system, browser-held credentials, LLM-authored executable commands, or success states that bypass validation.

## Recommended milestone 2

Implement the canonical models and event-contract increment together:

1. Add stable, tenant-scoped Operational Digital Twin resource and relationship models plus additive SQL migrations.
2. Add the normalized ownership, SLO, monitoring, change, knowledge, connection, and remediation metadata contracts.
3. Upgrade the canonical envelope with strict validation while retaining adapters for legacy events.
4. Add repository, identity, provenance, idempotency, migration, and compatibility tests.
5. Publish architecture and migration documentation before wiring connectors or changing the UI.

## Milestone 1 verification

- Remote refs fetched successfully from `https://github.com/aratij1/kaiops_pubsub.git`.
- Latest active feature baseline confirmed at `df335b6`.
- Lean images rebuilt from the current source.
- KaiMS UI readiness passed at `http://127.0.0.1:8501`.
- A transient Temporal health gate initially skipped four services; after Temporal became healthy, API gateway, orchestrator, resolution agent, and remediation engine started successfully.
- No schema, API, event, or runtime behavior was changed in this milestone.

