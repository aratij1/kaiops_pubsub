# KaiMS functional requirement coverage

This document is the acceptance map for application onboarding, live incident
processing, periodic knowledge development, and governed continuous learning.
Every release must keep the referenced automated tests green.

| Capability | Enforcement point | Acceptance evidence |
|---|---|---|
| Application profile, ownership, environment and connection setup | Monitoring Adapter onboarding contract and Operations setup UI | `test_onboarding_api_contract.py` |
| Multiple metrics, logs, traces, telemetry, email, ITSM and Jira sources | `monitoring_sources` plus application-scoped connection metadata | onboarding API and `onboardingSources.test.ts` |
| Central normalized landing pad | Monitoring Adapter ingestion adapters and partitioned landing-pad writer | ingestion and landing-pad tests |
| Normalize, deduplicate, correlate and prioritize | Alert Intelligence and Monitoring Adapter correlation pipeline | alert intelligence, deduplication and ingestion tests |
| Existing-knowledge search and evidence collection | Context Agent connector fan-out, RAG and knowledge graph | context connector and knowledge-pack tests |
| Evidence-based RCA, impact and resolution | Resolution Agent graph with evidence-quality confidence ceilings | resolution-quality and RCA evaluation suites |
| Human or policy-governed execution | Approval Service, remediation policy and safety gateway | approval and remediation tests |
| Recovery validation, rollback or escalation | Closure Service validation and remediation rollback metadata | closure and remediation tests |
| Periodic pattern analysis and runbook drafting | `Mode02Worker` and `FailurePatternAnalyzer` | `test_learning_workflows.py`, `test_continuous_learning.py` |
| Durable Mode 02 evidence and pattern history | canonical `incident_evidence` and `failure_patterns` records | knowledge-development worker persistence and migration `20260809_continuous_learning.sql` |
| New knowledge requires review | Mode 02 produces `draft` runbooks with mandatory approval | Mode 02 draft test |
| Project activation readiness | Monitoring Adapter activation gate requires connector validation and a processed test alert | monitoring onboarding contract and HTTP 409 readiness response |
| Automatic execution only from approved matching knowledge | Remediation Engine `validate_automatic_runbook_use` | auto-resolution policy tests |
| Failed or modified runbooks are suspended | `RunbookVersion.record_execution_outcome` | continuous-learning lifecycle test |
| Outcomes feed future confidence | Closure Service writes `runbook_outcomes`, updates counters, and appends a hash-verifiable learning event | closure integration and continuous-learning schema |
| Corrections are immutable and audited | `human_corrections`, audit records and evidence-draft review | API gateway correction tests |

## Release invariants

1. Model confidence alone never authorizes execution.
2. A newly generated resolution is review-only until an authorized user approves
   a versioned runbook.
3. Automatic execution requires an approved runbook identifier, active status,
   sufficient current evidence match, policy permission, evidence identifiers,
   and reasoning.
4. A failed or operator-modified execution suspends that runbook version. A new
   version must be reviewed and approved before automatic reuse.
5. Secret values are never onboarding or remediation payload fields; only
   enterprise secret-manager references are accepted.
6. A project or monitoring integration remains draft until connector validation
   and an end-to-end test alert have both passed.
7. Mode 02 writes evidence and failure patterns to their canonical tenant-scoped
   stores. Eligible knowledge is created as a versioned draft with mandatory HITL
   review; the worker never marks it approved.
8. Closure always records a durable runbook outcome. Failure or operator
   modification suspends that version before the transaction commits.

## Operational controls requiring deployment evidence

The codebase provides enforcement points for OIDC/RBAC, tenant scoping, vault
references, transport encryption, masking, and append-only audit. A production
release must additionally provide environment-specific evidence for identity
provider configuration, vault access policies, encryption keys, database grants,
retention, backup/restore, and reviewer project assignments. These controls cannot
be truthfully certified from source code alone.
