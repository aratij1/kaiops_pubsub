# KaiMS incident-management enhancement assessment

Date: 2026-08-03

## Outcome and scope

KaiMS already has a substantial event-driven incident pipeline. This increment adds the missing shared Phase 1
contract foundation and deterministic ticket triage without changing the current production route or the user-edited
monitoring/UI modules. Later phases are not represented as complete: several require external systems, credentials,
tenant policy decisions, and deployment-level validation.

## Proposed component flow

```text
authenticated sources -> landing pad -> schema/redaction/idempotency -> canonical alert/ticket
  -> rules-first triage/correlation -> orchestrator -> evidence-only context package
  -> scored RCA -> code analysis -> resolution plan -> external policy gateway
  -> approval/autonomy decision -> allow-listed executor -> validation/rollback
  -> closure -> learning events and immutable audit projection
```

Agents can recommend, but the independently deployed policy gateway owns authorization and kill switches. Executors
accept only catalogued action identifiers and typed parameters; they do not accept model-produced shell text.

## Gap analysis and phased plan

| Requirement | Existing capability | Missing capability | Affected modules / proposal | Risk or dependency | Phase |
|---|---|---|---|---|---|
| Canonical intake | `RawAlert`, landing-pad normalization, file/email/log/Jira/monitoring paths | Complete versioned ticket schema and durable source-neutral receipt | `common/incident_contracts.py`; migrate `canonical_tickets`, `ingestion_events` | Adapter-by-adapter rollout | 1 |
| Multi-channel connectors | Prometheus/generic monitoring, email, Jira admission, logs, JSON/file ingestion | ServiceNow adapter, generic CSV contract, unified connector CRUD/test/health API, durable retry/DLQ | connector SPI in monitoring adapter; `connector_definitions` | Real endpoints and secret store | 1 |
| Triage | Alert severity, in-memory dedup/correlation, team label | P1-P4 ticket output, explainable priority/SLA/noise decisions | `alert_intelligence/triage.py`, persist through repository | Historical calibration data | 1 |
| Audit/security | Gateway safety, RBAC, incident event store, redaction helpers | Immutable/WORM sink, OIDC production validation, ABAC across every service, retention jobs | audit service, auth policy, deployment configuration | IdP/KMS/WORM provider | 1/5 |
| Context | Context agent, tools, RAG evidence and provenance | Enforce one common `ContextPackage` at all boundaries and explicit missing-context gates | shared contract added; adapt context agent and repository | CMDB/Git/deployment credentials | 2 |
| Correlation/RCA | Enterprise alert correlation, context and resolution agents | Durable cross-source ticket graph; deterministic hypothesis score with contradictions | alert intelligence, resolution graph, repository | Ground-truth incident corpus | 2 |
| Code analysis | Context code review and bounded reviewed sources | Dedicated Git provider, injection boundary, typed diagnosis/patch/PR approval workflow | new code-analysis service/topic | GitHub Enterprise access | 3 |
| Remediation | Approval, action catalog/plugins, remediation and closure validation | Complete typed plan, external policy decision receipt, global/domain kill switches, rollback orchestration | policy gateway plus remediation/closure services | Change windows and target APIs | 4 |
| Autonomy | Execution modes and approval path | Policy per action/environment/service, automatic demotion and success ledger | autonomy policy tables and policy gateway | Governance thresholds | 5 |
| Capacity | Owner-team recommendation | Availability, schedule, skills, workload, separation-of-duties scoring | assignment service/UI | HR/on-call integrations | 5 |
| UI | Incident views, approval and pipeline details | Unified contract-driven uncertainty, connectors, autonomy and KPI screens | decompose `App.jsx` behind stable APIs | Current file has user edits | 1-5 |
| Observability | OTel, Prometheus, health endpoints | Accuracy labels, cost/autonomy/unsafe-action KPIs and SLO dashboards | telemetry, audit projections, Grafana | Ground-truth labels | 1-5 |

## Database and event migrations

Implemented migration `20260803_incident_management_foundation.sql` adds canonical tickets, durable ingestion receipts,
connector definitions, replay uniqueness, queue/correlation indexes, and validation constraints. Before production,
run it with the existing ordered migration mechanism; rollback is to stop writers, export the three tables, then drop
them in reverse dependency order only after confirming no rollout consumer uses them.

Planned migrations:

1. Phase 2: context packages, evidence objects, hypothesis scores, contradiction links, ticket-correlation edges.
2. Phase 3: repository installations, analysis runs, patch/PR proposals and evidence links (never token values).
3. Phase 4: policy decisions, typed remediation plans, execution attempts, validations and rollback attempts.
4. Phase 5: scoped autonomy policies, action-class success ledger/demotions, assignments, KPI aggregates and retention.

The event taxonomy now includes all requested topics. `EventEnvelopeV1` contains event/type/schema, correlation and
causation IDs, incident/source/time, payload, and trace metadata. Producers and consumers should dual-write/read the
legacy `AgentEventContractV1` and new envelope during a compatibility window before removing the old contract.

## File-by-file implementation plan

- `common/incident_contracts.py`: authoritative versioned contracts; expand with RCA/code/remediation schemas.
- `alert_intelligence/triage.py`: rules-first triage; next add durable duplicate/correlation repository interface.
- `monitoring-adapter`: map each connector to `CanonicalAlert`; enforce auth, payload limit, redaction and receipt write.
- `common/repository.py`: add commands/queries for tickets, receipts, context and policy decisions after decomposition.
- `context-agent`: emit only validated context packages and reject claims without evidence IDs.
- `resolution-agent`: deterministic hypothesis scoring followed by optional approved-model assistance.
- `approval-service` / `remediation-engine` / `closure-service`: require signed policy decision, validation and rollback.
- `api-gateway` and UI: connector management, uncertainty and audit APIs/panels after extracting stable UI modules.
- tests: add real-container connector and end-to-end scenarios as each production path is wired.

## Security and risk controls

The new schemas forbid unexpected fields, bound confidence/priority, require decision rationale, and reject AI
decisions without an approved provider identity and evidence. This does not by itself authorize execution. Remaining
critical controls are policy-service separation, signed decisions, secret-store references, per-tenant authorization,
WORM audit delivery, retention enforcement and deployment-level TLS/storage encryption verification.

Repository, ticket and log text must be tagged as untrusted evidence, stripped from system/tool instructions, size
bounded, and never interpolated into commands. A model output may select a candidate typed action, but only policy and
the executor's allow-list may authorize it.

## Deployment and rollback

1. Back up the database and apply the Phase 1 migration in staging.
2. Deploy shared contract code, then triage consumers in shadow mode; dual-write legacy and canonical records.
3. Compare ticket severity/correlation against labeled outcomes and alert on schema/DLQ failures.
4. Enable canonical reads tenant by tenant. Keep remediation autonomy unchanged.
5. Roll back application images first if errors rise; legacy reads remain valid. Database tables are additive and can
   remain. Destructive schema rollback is a separate, approved maintenance operation.

## Traceability matrix

| Requirement | Code / schema | Current tests | Status |
|---|---|---|---|
| Canonical alert/ticket | `common/incident_contracts.py`, Phase 1 migration | `test_incident_contracts_and_triage.py` | Foundation implemented; adapters not all wired |
| Explainable P1-P4/SLA/noise/team triage | `alert_intelligence/triage.py` | P1 and noise rule tests | Implemented library; persistence/API pending |
| AI confidence/rationale/evidence | `AuditMetadata`, `CanonicalTicket` validators | negative validation tests | Implemented at new contract boundary |
| Versioned event envelope/topics | `EventEnvelopeV1`, `common/topics.py` | strict-envelope test plus legacy event tests | Implemented; producer adoption pending |
| Durable replay protection/DLQ state | `ingestion_events` unique key/status | migration constraints only | Runtime repository and integration test pending |
| Connector configuration/health | `connector_definitions`; existing monitoring APIs | existing monitoring/onboarding tests | Unified API and ServiceNow pending |
| Context evidence/provenance | `ContextPackage`; existing context agent | existing context tests | Contract implemented; boundary adoption pending |
| RCA/code/remediation/governance/UI/KPIs | existing services plus plan above | existing focused tests | Partially existing; acceptance not yet met |

## Test results and limitations

The host has no usable Python/pytest installation and the existing remediation image lacks pytest, so the requested
targeted pytest suite could not run there. A no-network import and behavior smoke check in that image passed for P1
triage, escalation, evidence, non-AI provenance, ticket serialization and event-envelope validation. The full suite
must still run in a service image with the repository's development extras before merge. No production connector or
remediation claim is made by this increment.

The mandatory ten scenarios remain release gates. Existing tests cover parts of the alert chain, approvals,
remediation/closure, RabbitMQ hardening and event contracts, but they are not equivalent to real, non-mocked
end-to-end proof for all ten scenarios.
