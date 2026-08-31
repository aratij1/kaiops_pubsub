# Continuous learning and self-healing

KaiMS retains MySQL and its existing monitoring-adapter, RAG, resolution-agent, approval-service,
remediation-engine, validation-agent, closure-service and audit-service boundaries. The continuous-learning
domain is an additive shared contract used by those services; it does not create a second remediation path.

## Inventory and gap analysis

Existing capabilities include authenticated monitoring/Jira/telemetry ingestion, canonical alerts and tickets,
hybrid RAG, structured RCA recommendations, OIDC/RBAC, approval policy, idempotent remediation, validation,
closure feedback, SSE operational events and an audit UI. The missing cohesive capabilities were a complete
incident-evidence schema, periodic recurrence analysis, immutable/versioned runbooks, explicit independent-
evidence drafting thresholds, hybrid runbook scoring and one deterministic execution-policy contract.

## Mode 02

Read-only connectors submit `IncidentEvidence`; credentials remain secret-manager references. External text is
masked and tagged as untrusted data before any model request. The periodic worker groups the deterministic issue
signature, deduplicates incident/signature pairs, computes recurrence and common symptoms/resolutions, detects
conflicting resolution outcomes, and permits a draft only with two independent sources, confidence >= 0.60, a
successful resolution and no conflict. Every generated or changed version is `draft`. Approval creates an immutable
approved version; outcomes update counters only after review and never rewrite content.

## Mode 01

The existing alert workflow normalizes/deduplicates and gathers context. Matching then combines service/signature,
semantic token similarity, telemetry presence, recent changes and historical success. Only approved runbooks are
eligible. Root cause and impact remain independently evaluated by the resolution agent. Policy abstains below 0.45
or on conflicting evidence; sensitive/destructive/database/security/large-radius actions require approval; only an
approved, low-risk, small-radius, confidence >= 0.80 action is automatic.

The resolution agent uses the configured model for RCA and, by default, structured impact and remediation analysis
(`RESOLUTION_DEEP_ANALYSIS_ENABLED=true`). Model output must include competing hypotheses and falsification checks,
observed versus potential impact, citations, validation, rollback/compensation, idempotency, timeouts and retries.
Deterministic quality gates cap confidence based on independent/direct evidence and prevent model output from
authorizing itself. Set the variable to `false` only when the lower-latency deterministic impact/fix path is required.

Execution continues through the remediation engine, whose idempotency key, timeouts, bounded retries, dry-run,
execution logs and target allow-list are authoritative. Validation and closure verify alerts, health and regression
signals. Failed validation invokes safe compensation, reopens/escalates, and marks the exact runbook version
`suspended` until an engineer reviews a new draft.

## Storage and audit

Apply `20260809_continuous_learning.sql` after existing migrations. `runbook_versions` uses `(runbook_id, version)`
as its immutable key. `runbook_outcomes` references that exact version. `learning_audit_log` is append-only; the
runtime identity receives INSERT/SELECT only. Database backups and connections use the platform encryption policy.
