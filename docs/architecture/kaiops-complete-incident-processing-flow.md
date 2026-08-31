# KaiOps Complete Incident Processing Flow

Open `kaiops-complete-incident-processing-flow.svg` for the corrected flow diagram.

## Corrected Runtime Flow

1. Third-party monitoring tools send alerts to the Landing Pad.
2. Monitoring Adapter normalizes the alert into the canonical alert envelope.
3. Message Bus publishes `raw-alerts`.
4. Alert Intelligence consumes `raw-alerts`.
5. Alert Intelligence performs severity classification, deduplication, incident correlation, and enriched alert projection.
6. Message Bus publishes `enriched-alerts`.
7. Orchestrator consumes `enriched-alerts`.
8. Orchestrator reads workflow routing policy, cloud/runtime config, service profile, connector profile, `playbooks.json`, `action_catalog.json`, and execution policy.
9. Message Bus publishes `orchestration-events`.
10. Context Agent consumes `orchestration-events`.
11. Context Agent checks the document index, runs semantic search, retrieves ranked documents, queries configured connectors, and merges evidence.
12. Message Bus publishes `context-events`.
13. Resolution Agent consumes `context-events`.
14. Resolution Agent generates RCA, impact analysis, recommended action, confidence, grounding score, hallucination risk, and an editable remediation plan.
15. Message Bus publishes `resolution-events`.
16. Approval Service consumes `resolution-events` when human approval is required.
17. L2/L3/Admin reviews and can edit commands, scripts, queries, connection details, rollback plan, and validation checks.
18. Message Bus publishes `approval-events`.
19. Remediation Engine consumes `approval-events`.
20. Remediation Engine validates policy, connector executor, secret reference, dry-run requirement, blast radius, and rollback plan.
21. Remediation Engine executes only when a real executor and approved connection profile exist; otherwise it preserves the plan and marks execution skipped.
22. Message Bus publishes `remediation-events`.
23. Closure Service consumes `remediation-events`.
24. Closure Service runs post-checks, updates incident projection, audit trail, action logs, and cockpit timeline.
25. Message Bus publishes `closure-events`.
26. Notifications/Reports send final resolution status to Email, Teams, dashboard, and audit views.

## Message Topics

| Topic | Producer | Consumer | Payload |
| --- | --- | --- | --- |
| `raw-alerts` | Monitoring Adapter | Alert Intelligence | Canonical alert envelope, trace id, labels, annotations, source metadata |
| `enriched-alerts` | Alert Intelligence | Orchestrator | Deduped alert, severity, incident id, correlation id, service/environment |
| `orchestration-events` | Orchestrator | Context Agent | Workflow decision, risk tier, execution mode, connector config, policy metadata |
| `context-events` | Context Agent | Resolution Agent | RAG matches, documents touched, dependencies, incidents, changes, connector evidence |
| `resolution-events` | Resolution Agent | Approval Service or Remediation Engine | RCA, impact, confidence, scores, recommendation, editable execution plan |
| `approval-events` | Approval Service | Remediation Engine | Human decision, edited plan, connection profile, approval metadata |
| `remediation-events` | Remediation Engine | Closure Service | Execution status, action id, output, error, connector result |
| `closure-events` | Closure Service | Notifications, Reports, Dashboard | Validation result, final incident status, evidence, audit references |

## Config And Policy Inputs

| Component | Config Read |
| --- | --- |
| Monitoring Adapter | Monitoring provider, landing path, project, service profile |
| Orchestrator | Workflow policy, bus provider, risk policy, execution mode, tenant/environment config |
| Context Agent | RAG/vector index config, embedding model, connector registry, document metadata |
| Resolution Agent | Prompt version, model-router endpoint, evaluation thresholds, remediation safety contract |
| Approval Service | RBAC policy, role eligibility, risk gate policy |
| Remediation Engine | `playbooks.json`, `action_catalog.json`, connector executor, `secret_ref`, dry-run and rollback rules |
| Closure Service | Validation checks, health endpoints, incident projection config |

