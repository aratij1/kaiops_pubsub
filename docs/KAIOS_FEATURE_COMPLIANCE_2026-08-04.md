# KaiOps Feature Compliance Review — 2026-08-04

## Architecture summary

KaiOps is a React/Vite application behind nginx and an authenticated FastAPI API gateway. Python services use MySQL through the shared SQLAlchemy repository, RabbitMQ/Kafka-compatible event publishers, and a Temporal pilot for the long-running context → resolution → approval path. Monitoring Adapter owns multi-source intake and landing-pad normalization; Alert Intelligence owns deterministic triage and incident discovery; Context and Resolution agents assemble evidence and recommendations; Approval, Remediation, Validation, and Closure services complete the governed workflow. Redis is short-lived coordination/cache only. No PostgreSQL or pgvector dependency is used.

## Compliance matrix

Status is based on connected implementation evidence, not class or UI presence alone.

| Requirement | Backend | Frontend | Database | Workflow | Tests | Status | Gap | Action |
|---|---|---|---|---|---|---|---|---|
| Ticket normalization and deterministic triage | `alert_intelligence/triage.py`, incident contracts | Alert stream/cockpit | Alert/incident JSON payloads plus `human_corrections` | Alert Intelligence consumer | triage and gateway governance tests | Partial | Configurable policy administration and full feedback-driven evaluation remain | Expanded factor policy and added tenant-scoped correction persistence/API/UI/audit |
| Category, subcategory, severity, priority, SLA, ownership, explanation | Deterministic triage | Explanation partially visible | Incident payload | Enriched alert path | triage tests | Partial | No configurable policy administration; explanation not consistently surfaced | Extend cockpit triage decision and override experience |
| Deterministic and semantic deduplication/correlation | Monitoring dedup, discovery embeddings, Jira reuse | Grouping explanation in alert stream | dedupe keys/correlation IDs | centralized intake and Alert Intelligence | Jira, ingestion, triage tests | Partial | Cross-application negative cases and persisted correlation decision need stronger coverage | Add decision persistence and scenarios |
| Prometheus/Alertmanager ingestion | Strict adapters and landing pad | Ingestion stream | received/normalized alert tables | raw-alerts → enriched-alerts | ingestion tests | Complete | — | Preserve |
| Email, logs, Jira, files, REST, queues | Existing source adapters/loaders | Multi-source stream | normalized/received records | centralized intake | source/email/log/Jira tests | Partial | ServiceNow, CloudWatch, Kubernetes and generic ITSM contracts not all verified | Add feature-flagged adapters using existing connector registry |
| Malformed-event quarantine and safe retry | Landing-pad failed state and file recovery | Failed intake counter | file/object metadata | retry/replay scripts | landing-pad/replay tests | Partial | No complete failed-event inspection/retry UX | Connect existing failed records to Alerts route |
| Idempotent ingestion | fingerprints, bounded delivery cache, DB dedupe keys | occurrences shown | unique/dedupe fields | consumers hardened | concurrency/replay tests | Partial | Semantic retry scenarios incomplete | Add integration cases |
| Mode 02 context knowledge | ContextKnowledgeRecord and cache-aside strategy | Evidence/RCA views | `context_knowledge` | context-events | `test_context_knowledge_strategy.py` | Complete | — | Preserve |
| Mode 01 fresh discovery fallback | Context agent + discovery MCP | Evidence trust classifications | evidence in workflow payload | context-events | context flow/tool tests | Partial | Authorization/freshness metadata is not uniform for every evidence item | Normalize evidence contract |
| RCA and impact | Resolution agent structured analysis | RCA & Impact redesign | RCA report/payload | resolution-events | context-resolution tests | Partial | Alternative hypotheses and deterministic-vs-AI classification are not uniformly persisted | Extend RCA contract/tests |
| Code analysis and insights | Discovery MCP code/log search | Technical RCA retrieval trace | workflow payload only | context flow | discovery tests | Disconnected | No governed CodeAnalysis entity/API, proposed patch validation, or PR workflow | Implement behind feature flag |
| Remediation plan and execution | Execution plan, plugins, allowlist, idempotency | guarded Execution UI | actions | remediation-events | safety/idempotency tests | Partial | No truthful backend dry-run, emergency stop, or automatic rollback | Implement safety state machine behind flags |
| Recovery validation and closure | validation/closure services | cockpit audit/execution | incident projection/events | validation/closure events | remediation closure tests | Partial | Rollback not executed when validation fails | Add compensation workflow and independent checks |
| HITL approval | approve/reject/modify | Approval queue/cockpit | approvals | approval-events | approval tests | Partial | delegate/expire/cancel/emergency-stop and stale-state prevention incomplete | Extend existing Approval model/service |
| Assignment/capacity | support-tier hint and user project assignments | no complete capacity view | no workload/skill history entity | disconnected | no capacity suite | Missing | Recommendation, alternatives, limits, history absent | Priority 3 implementation |
| Authentication/RBAC | gateway policy, OIDC/local sessions | role-aware navigation/actions | users/roles/sessions | gateway enforced | auth/tenant tests | Partial | Some legacy read routes intentionally open; v1 surface not uniform | Route-by-route policy audit |
| Audit | gateway and domain audit records | Audit route/timeline | audit_logs/events | domain events | audit-related tests | Partial | Not every correction/replay/assignment is audited | Add domain audit writes |
| MySQL-only persistence | shared SQLAlchemy + migrations | n/a | MySQL types/migrations | all services | mysql-only tests | Complete | — | Preserve; no PostgreSQL |
| `/api/v1/*` unified surface | Existing domain routes through gateway | existing route clients | n/a | connected legacy routes | contract tests | Partial | Required v1 aliases are not uniformly present | Add non-breaking aliases after domain completion |
| DLQ inspection and replay | replay script/consumer hardening | no complete operator view | broker/file state | dead-letter handling | replay tests | Disconnected | Safe UI workflow absent | Connect to existing diagnostics/audit surface |
| End-to-end and production validation | backend and Playwright suites | built/deployed | MySQL stack | Docker Compose | broad but incomplete | Not tested | Full requested scenario matrix has not yet run | Execute staged suites after implementation |

## Duplicate or disconnected implementations

- Legacy `App.jsx` still owns several domain workflows while extracted route components own their list surfaces. Continue decomposition; do not add parallel pages.
- Temporal covers only the pilot workflow; RabbitMQ remains authoritative elsewhere. Expand only after compensation/rollback semantics are real.
- Severity overrides remain policy hints, but cockpit-originated changes now also create governed `human_corrections` and audit records. Automated evaluation/learning from those records is not yet connected.
- Code search exists in Discovery MCP, but no audited incident-to-change lifecycle exists.
- Support-tier labels exist, but capacity-based assignment does not.

## File-level implementation plan

1. Priority 1: extend existing triage policy and explanation; add MySQL human/correlation decision records; expose gateway endpoints; connect cockpit overrides; normalize evidence metadata; connect quarantine retry.
2. Priority 2: extend existing approval and remediation contracts; add feature-flagged dry-run, cancellation/emergency stop, compensation and rollback; create governed code-analysis records and proposed-patch workflow.
3. Priority 3: add assignment recommendation/history entities and repository methods; expose recommendations in the incident cockpit and existing personal-work area.
4. Add only MySQL-compatible migrations, non-breaking API routes/aliases, existing topics, RBAC rules, and audit events.

## Database impact

Reuse JSON payloads where they are already authoritative. New relational entities are justified for governed mutable history: human corrections, correlation decisions, code analyses, validation/rollback attempts, and assignment recommendations/history. All migrations must be additive and MySQL compatible.

## API and security impact

New mutation routes require authenticated role checks, tenant scoping, structured Pydantic input, correlation/idempotency keys, stale-version checks, reason fields, audit writes, and secret redaction. Risky code-change, live execution, emergency-stop, and automatic-rollback paths remain feature flagged until their integration tests pass.

## Test plan

Add focused unit and API tests with MySQL integration and end-to-end coverage for the 15 mandated scenarios: cross-channel duplicates, correlation and isolation, missing/stale/conflicting context, incorrect recommendation feedback, production safety, rollback, duplicate approval/execution, connector failure, replay, and capacity exhaustion. Run Python compile, targeted pytest, full backend pytest, TypeScript, Vitest, Playwright, production builds, and Docker health/API smoke tests.
