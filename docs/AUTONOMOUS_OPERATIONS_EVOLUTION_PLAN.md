# KaiMS Autonomous Operations Evolution Plan

## 1. Repository assessment

KaiMS already has an event-driven microservice core, typed shared events, tenant isolation,
an investigation loop, governed execution plans, approval/remediation services, telemetry-based
closure validation, cloud-operation connectors, a React incident cockpit, and evaluation tests.
The safest path is incremental contract hardening and capability completion, not a rewrite.

## 2. Existing module map

| Domain | Current modules | Decision |
| --- | --- | --- |
| Ingestion and correlation | `monitoring-adapter`, `alert-intelligence`, RabbitMQ/Kafka adapters | KEEP / REFINE |
| Context and discovery | `context-agent`, `discovery-mcp` | KEEP / REFINE |
| Investigation and RCA | `resolution-agent/{graph,investigation,evidence,confidence}.py` | REFINE |
| Planning and policy | `common/orchestration`, approval service | KEEP / REFINE |
| Execution | remediation engine and connector plugins | KEEP / REFINE |
| Outcome validation | closure service validators and observations | KEEP / REFINE |
| Learning/evaluation | evaluation service, learning audit records | REFINE |
| Operator experience | React incident, approval, cloud-operation routes | REFINE |
| Legacy free-text projections | flat recommendation/command compatibility fields | DEPRECATE after typed consumers migrate |

## 3. Identified gaps

- Several Resolution Agent boundaries still use untyped dictionaries.
- Hypothesis states and non-conclusive outcomes are not canonical contracts.
- Runbook/change presence contributes to confidence without proving causality.
- Resolution options, impact, blast radius, learning, and AgentOps contracts are incomplete.
- Specialist routing, knowledge graph, source-code RCA, shadow promotion, and proactive operations
  need bounded implementations and persistence.
- UI capability exists but needs typed evidence factors, hypothesis tests, options, and live events.

## 4. Proposed target architecture

Preserve the current services. Introduce versioned contracts at their boundaries and evolve the
flow through normalize/correlate, context, bounded investigation, evidence judge, typed RCA,
ranked resolution options, governed execution plan, policy/approval, connector execution,
independent validation, rollback, and learning. Compatibility projections remain until every
consumer accepts the new contracts.

## 5. Files/modules to change

- Resolution graph, investigator, evidence compiler, confidence engine, and API.
- Shared orchestration contracts and repositories.
- Remediation policy/plugins and closure validation.
- Incident cockpit, evidence explorer, approval workflow, and onboarding routes.
- Focused backend, UI, security, integration, and evaluation tests.

## 6. New files/modules to create

- Versioned resolution intelligence contracts and specialist registry.
- Impact/blast-radius and resolution-option services.
- Skill, credential-broker, validation, rollback, memory, AgentOps, and evaluation contracts.
- Phase-specific migrations and evaluation fixtures.

## 7. Data model changes

Extend the existing investigation tables rather than replacing them. Persist canonical plans,
hypotheses, evidence relationships, resolution options, impact/blast radius, validation and
rollback outcomes, operator corrections, learning records, and agent execution traces with tenant,
incident, correlation, causation, schema-version, and idempotency fields.

## 8. API/event contract changes

Add versioned contracts while retaining current endpoints. Every new event includes tenant,
incident, correlation and causation identity. Non-conclusive RCA uses explicit outcomes such as
`INSUFFICIENT_EVIDENCE`, `CONFLICTING_EVIDENCE`, and `CONNECTOR_FAILURE`; it never carries an
asserted root cause.

## 9. Database migrations

Use additive, backward-compatible migrations. Backfill only deterministic values, keep old
columns during consumer migration, and add tenant-scoped indexes and immutable audit records.

## 10. UI changes

Incrementally extend the incident cockpit with investigation questions, hypotheses, supporting and
contradicting evidence, confidence factors/penalties, ranked resolution options, blast radius,
autonomy decision, execution progress, validation, rollback, and audit views.

## 11. Security implications

Authenticated tenant identity remains authoritative. Investigation tools are read-only and
allow-listed. Production mutations require registered skills, resource-scoped credential
references, policy, preflight, validation, audit, and approval where required. Model text never
becomes a command.

## 12. Test strategy

Each phase adds unit, contract, integration, security/failure, evaluation, and UI coverage. P0
tests prove weak/conflicting evidence cannot produce a root cause, tool failures are explicit,
confidence ignores severity, and investigation budgets stop safely.

## 13. Phased implementation plan

1. Resolution intelligence: typed investigation/hypothesis/RCA/evidence/options and calibrated confidence.
2. Safe remediation: capability registry, blast radius, credential broker, preflight/dry-run.
3. Outcome validation: domain validators, observation windows, rollback, false-closure prevention.
4. UX: onboarding/connections, command center, evidence explorer, options and HITL edits.
5. Learning/AgentOps: incident memory, evaluation data, calibration, shadow/autonomy progression.
6. Differentiators: source-code RCA, knowledge graph, evidence council, preventive operations.

Each phase is independently deployable and retains compatibility adapters until its consumers have
migrated.
