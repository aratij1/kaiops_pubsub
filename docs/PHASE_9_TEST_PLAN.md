# Phase 9 Test Plan

## Release gates

Every change must pass Python lint and tests, frontend lint/type/architecture/unit checks, the production UI bundle budget, dependency audits, service/UI image builds, Kubernetes client validation, governed catalog checksums, RAG metadata validation, and `scripts/validate_phase9_readiness.py`.

## Mandatory scenario matrix

| Scenario | Required evidence |
|---|---|
| Kubernetes pod failure / bad deployment | Correlated alert, deterministic target, capability plan, approval where required, validation and rollback result |
| Database exhaustion / replica issue | Read-only diagnostic first, database evidence, no invented SQL, HITL for failover |
| Kafka lag / dependency outage / VM saturation / 5xx spike | Source telemetry, topology scope, bounded hypothesis, safe capability or escalation |
| Expired credential / connector failure | Fail-closed connection result, secret reference only, actionable operator error |
| Ambiguous or incorrect RCA / missing telemetry | Alternative hypotheses, explicit gaps, no confirmed claim, evidence request path |
| Failed remediation / validation / rollback | Durable terminal state, bounded retry, rollback or escalation, audit trail |
| Duplicate event | Idempotent consumer and no duplicate remediation |
| HITL reject / modify | Immutable decision record and exact-plan binding |
| Autonomous safe remediation | Trusted capability, eligible environment, verified target, policy pass, validation success |

Unit tests own deterministic contracts and policies. Integration tests own persistence, APIs, broker idempotency, and service boundaries. Playwright owns authenticated critical journeys, responsive layout, keyboard access, and WCAG checks. Manual load testing is gated on measured acceptance, p95, and p99—not request count alone.

Unavailable external systems must be reported as skipped/blocked integration evidence, never simulated as a passing production connection.
