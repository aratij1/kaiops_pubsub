# KaiOps autonomous resolution reference architecture

## Executive decision

KaiOps should evolve from a linear alert-to-plan pipeline into a closed-loop, service-aware resolution system:

```text
signals -> correlate -> understand service -> investigate iteratively
        -> prove cause -> compile governed plan -> simulate/canary
        -> approve by risk -> execute -> verify independently
        -> rollback/escalate -> learn from outcome
```

The core design principle is separation of responsibilities:

- AI investigates and proposes.
- Deterministic policy decides what is allowed.
- A reviewed catalog supplies executable capabilities.
- An isolated executor performs the operation.
- Independent monitoring proves recovery.
- The outcome ledger decides what may be reused in the future.

## Reference products and the patterns to adopt

### Dynatrace Intelligence

Dynatrace combines deterministic causal analysis with a real-time dependency graph and correlates applications, services, infrastructure, logs, traces, deployments, code changes, configuration, and policy changes. Its automation model proposes or runs approved actions under policy guardrails.

Adopt:

- A continuously maintained service/dependency graph rather than flat service labels.
- Reverse impact traversal from a suspected root cause to affected entry points.
- Change correlation as a first-class causal signal.
- Deterministic causal ranking alongside generative explanation.

Do not copy:

- Dependence on one proprietary telemetry lake. KaiOps must retain connector-neutral evidence contracts.

Official references:

- https://docs.dynatrace.com/docs/dynatrace-intelligence
- https://docs.dynatrace.com/docs/dynatrace-intelligence/root-cause-analysis/event-analysis-and-correlation

### Datadog Bits Investigation

Bits runs a continuous observation-reasoning-action loop: it forms hypotheses, queries telemetry to validate or invalidate them, updates the hypothesis tree, and either returns an evidence-backed conclusion or declares the investigation inconclusive. It spans metrics, traces, logs, change tracking, source code, databases, profiles, networks, RUM, and external systems. Datadog also exposes tool-call audit trails, automatic-investigation rate limits, investigation APIs, and a separate code-fix/PR path.

Adopt:

- Iterative investigation, not one fixed batch of context followed by one LLM request.
- A durable hypothesis tree with supporting, contradicting, and falsifying evidence.
- `inconclusive` as a legitimate outcome that triggers targeted evidence collection.
- Source-specific tools and budgets, with every tool call audited.
- A distinct code-remediation path that creates a reviewed pull request and waits for CI.
- Per-service and organization-wide investigation rate limits.

Official references:

- https://docs.datadoghq.com/bits_ai/bits_investigation/investigate_issues/
- https://docs.datadoghq.com/bits_ai/bits_investigation/configure/
- https://docs.datadoghq.com/bits_ai/bits_investigation/take_action/

### PagerDuty AIOps and Automation Actions

PagerDuty separates noise reduction, triage/RCA, event orchestration, incident workflows, and runbook execution. It uses past incidents, related incidents, probable origin, and recent changes for triage. Event Orchestration applies nested deterministic rules, while Automation Actions executes vetted jobs and retains their output on the incident.

Adopt:

- Correlation and transient-alert handling before starting expensive investigation.
- Global policy followed by service-specific policy, with explicit precedence.
- Event-count windows and burst/sustained-state differentiation.
- Runbook execution as a separately permissioned capability with durable output.
- Suppress/pause/investigate/remediate/escalate as distinct actions.
- A dry-run rule evaluator to detect unreachable or conflicting automation rules.

Official references:

- https://support.pagerduty.com/main/docs/aiops
- https://support.pagerduty.com/main/docs/event-orchestration
- https://support.pagerduty.com/main/docs/automation-actions
- https://support.pagerduty.com/main/docs/incident-workflows

### ServiceNow ITOM AIOps

ServiceNow anchors correlation and remediation in a service graph/CMDB. Its current autonomous workflow covers triage, impact assessment, root-cause investigation, and next-step reporting; newer remediation agents select approved remediation subflows. ServiceNow guidance distinguishes automatic low-risk actions from approval-gated high-risk actions and uses historical incidents, changes, knowledge, and service health.

Adopt:

- A governed application/CI/service graph with ownership and business criticality.
- Approved remediation subflows selected by applicability filters.
- Low-risk auto-execution and high-risk approval as policy outcomes, not model choices.
- An automation-opportunity pipeline learned from repeated successful operator actions.
- Progressive rollout from one high-value service to broad autonomous operations.

Official references:

- https://www.servicenow.com/docs/r/it-operations-management/event-management/c_EM.html
- https://www.servicenow.com/docs/r/it-operations-management/now-assist-for-it-operations-management/itom-autonomous-operator-workflow.html
- https://www.servicenow.com/docs/r/store-release-notes/store-rn-itom-now-assist-itom.html
- https://www.servicenow.com/docs/r/it-operations-management/itom-health-admin-config-use-case.html

## Current KaiOps assessment

### Existing strengths

- Connector-based collection of logs, telemetry, code, tickets, database data, runbooks, and historical knowledge.
- Immutable context snapshots and evidence provenance.
- Evidence citation validation and confidence ceilings.
- A versioned resolution lifecycle and plan fingerprint.
- Reviewed playbook/action/connector catalogs.
- HITL/HOTL policy, immutable execution attempts, rollback fields, and independent closure validation.
- The new evidence-first stages: crawl manifest, hypothesis ranking, historical outcomes, and evidence-enriched catalog matching.

### Material gaps

1. Context collection is still primarily a bounded batch. Resolution cannot yet request a second targeted query after a hypothesis changes.
2. Service identity is label-based; there is no authoritative temporal dependency graph with deployed version and ownership edges.
3. Historical similarity does not yet learn calibrated success rates by action, service version, environment, and failure signature.
4. Plans are not simulated against a target-state model before approval.
5. Execution lacks a general canary/blast-radius controller and per-action error-budget limits.
6. Validation is mostly command/URL based rather than SLO, symptom, dependency, and regression based.
7. Automation rules lack a preview engine that detects precedence conflicts and unreachable branches.
8. There is no formal promotion pipeline from repeated human remediation to reviewed automation.
9. The UI does not yet expose the complete hypothesis tree, contradictions, evidence gaps, and plan alternatives.
10. Fleet-level budgets, service-level kill switches, and automated rollback thresholds need one unified policy contract.

## Target architecture

### 1. Signal and correlation plane

Responsibilities:

- Normalize alerts, anomalies, tickets, synthetic failures, SLO burn, and change events.
- Deduplicate repeated events using stable alert-family identity.
- Group related events using service graph, time, topology, change, and content features.
- Classify transient, sustained, flapping, correlated, and novel conditions.
- Apply cheap deterministic suppression/pause rules before AI investigation.

Required output: `IncidentCandidate.v2`

```json
{
  "incident_family_id": "sha256",
  "primary_signal": "alert-id",
  "member_signal_ids": [],
  "service_graph_scope": [],
  "condition": "sustained",
  "correlation_reasons": [],
  "investigation_priority": 0.0,
  "suppression_decision": "investigate"
}
```

### 2. Service intelligence plane

Maintain a temporal graph containing:

- application -> service -> workload -> process/container -> host/cluster;
- service -> database/queue/cache/external API dependencies;
- service -> repository -> path -> deployed commit/build;
- service -> dashboards/log indexes/traces/SLOs;
- service -> owner/on-call/business journey/criticality;
- change -> deployed entity -> time window;
- runbook/action -> supported service/version/environment.

Every edge needs provenance, valid-from/valid-to, confidence, and last-verified time. Resolution queries the graph as it existed at alert onset, not only its current state.

### 3. Investigation control plane

Replace the fixed pipeline with a bounded state machine:

```text
scope incident
  -> seed hypotheses
  -> choose highest-information next tool
  -> execute read-only query
  -> normalize evidence
  -> support/contradict/falsify hypotheses
  -> update confidence
  -> stop when proven, inconclusive, unsafe, or budget exhausted
```

Investigation stop conditions:

- `conclusive`: one hypothesis is sufficiently corroborated and alternatives are materially weaker.
- `inconclusive`: evidence budget exhausted or required source unavailable.
- `no_fault`: source alert cleared and no harmful state remains.
- `unsafe_scope`: identity or tenant boundary cannot be proven.
- `needs_human`: ambiguity, business decision, security concern, or destructive-only remedy.

Tool selection should maximize expected information gain while respecting source cost, freshness, latency, permissions, and rate limits.

### 4. Evidence and hypothesis ledger

Persist every investigation step, not hidden chain-of-thought:

```json
{
  "hypothesis_id": "uuid",
  "claim": "connection pool exhaustion caused checkout timeouts",
  "status": "leading|viable|falsified|confirmed",
  "supporting_evidence_ids": [],
  "contradicting_evidence_ids": [],
  "falsification_query": {},
  "confidence": 0.0,
  "confidence_method": "calibrated-evidence-model-v1"
}
```

Store concise decision summaries and tool inputs/outputs. Do not persist private model reasoning. Evidence remains immutable and content-addressed.

### 5. Resolution memory plane

Use three distinct memory types:

- Semantic memory: reviewed runbooks, architecture, known errors, service conventions.
- Episodic memory: prior incidents with exact symptoms, cause, action, validation, rollback, and outcome.
- Procedural memory: reviewed executable actions and workflows.

Historical reuse requires:

- same tenant and compatible environment;
- service/version/topology applicability;
- matching failure signature;
- successful prior outcome and no later negative feedback;
- freshness and minimum sample count;
- current evidence independently confirming applicability.

Track per action-context pair:

- attempts, successes, validation failures, rollbacks, manual overrides;
- median recovery time and blast radius;
- Wilson lower-bound success rate, not raw percentage;
- last reviewed catalog version.

### 6. Resolution plan compiler

The AI produces a typed intent; the compiler produces an executable plan.

Plan stages:

1. Target identity and expected current state.
2. Preconditions and read-only preflight.
3. One minimal reversible mutation.
4. Canary scope and observation window.
5. Symptom validation.
6. Service/SLO validation.
7. Dependency/regression validation.
8. Rollback trigger and executable compensation.
9. Idempotency key, timeout, retry ceiling, and concurrency lock.
10. Evidence and hypothesis binding.

Reject compilation when commands are invented, target identity is ambiguous, required variables are unbound, connector permissions are missing, validation is absent, rollback is absent for reversible changes, or historical applicability is unproven.

### 7. Counterfactual and policy plane

Before execution, estimate:

- expected symptom change if the hypothesis is correct;
- likely effect if the hypothesis is wrong;
- maximum affected instances/users;
- SLO/error-budget consumption;
- data-loss/security/compliance risk;
- action success lower bound from history.

Policy returns exactly one decision:

- `observe`: gather more evidence.
- `diagnostic_complete`: close diagnostic workflow without claiming recovery.
- `hitl`: human approves exact fingerprint.
- `hotl`: notify human, delay, then execute unless vetoed.
- `auto_canary`: execute limited scope automatically.
- `auto_full`: execute within a proven low-risk envelope.
- `manual_only`: AI cannot execute.

Suggested initial auto-canary requirements:

- reviewed catalog action and connector;
- non-destructive and reversible;
- exact target identity;
- sufficient fresh evidence from at least two independent planes;
- confidence >= 0.85 and calibrated precision target >= 95%;
- historical Wilson lower-bound success >= 0.90 with at least 20 comparable attempts;
- canary <= 10% of instances and <= 5% projected error-budget burn;
- executable rollback and independent validation;
- no security, data-loss, schema, financial, or Tier-0 exclusion.

### 8. Execution plane

- Run actions in isolated workers with short-lived credentials.
- Enforce tenant, target, operation, parameter, and network allow-lists.
- Acquire an incident/target lock and use immutable attempt IDs.
- Stream signed execution output into the incident timeline.
- Execute canary first, observe, then expand progressively.
- Stop immediately on health regression, unexpected output, timeout, policy change, or operator veto.
- Never let the model directly access shell, cloud, database, or Kubernetes credentials.

### 9. Independent validation and closure

Recovery requires all applicable checks:

- original alert condition cleared for a stability window;
- symptom metric/log signature recovered;
- golden signals within bounds;
- critical dependencies healthy;
- synthetic/business journey passes;
- no new correlated high-severity alert;
- canary and full-scope state converge;
- external monitoring confirms the result.

Lifecycle outcomes must remain distinct:

- `diagnostic_closed`: analysis finished, no recovery claim.
- `recovered`: recovery evidence passed, stability window active.
- `closed`: recovery durable and ticket/knowledge updates committed.
- `validation_failed`: action completed but recovery not proven.
- `rolled_back`: compensation ran and awaits validation.
- `manual_intervention_required`: automated envelope exhausted.

### 10. Learning and governance plane

- Capture operator approval, edit, rejection, and reason.
- Compare predicted versus actual effect for every action.
- Generate automation candidates from repeated successful manual procedures.
- Require review, test fixtures, sandbox replay, permissions, rollback, and owner before catalog promotion.
- Automatically demote actions after validation failures, rollback spikes, topology drift, or stale review.
- Provide global, tenant, service, action, and connector kill switches.
- Version prompts, models, policies, tools, graph snapshots, evidence, and plans for replay.

## End-to-end decision process

| Phase | Primary output | Hard gate |
|---|---|---|
| Correlate | Incident family | Stable identity and non-transient condition |
| Scope | Temporal service subgraph | Tenant, service, version, and dependency boundaries |
| Investigate | Evidence ledger | Fresh provenance and source permissions |
| Hypothesize | Ranked hypothesis tree | Supporting and contradicting evidence visible |
| Conclude | RCA or inconclusive result | Calibrated sufficiency threshold |
| Plan | Typed corrective intent | Cause-action relevance |
| Compile | Governed executable plan | Catalog, connector, rollback, validation |
| Simulate | Counterfactual risk report | Risk envelope and projected blast radius |
| Decide | Policy disposition | Deterministic policy, exact fingerprint |
| Execute | Immutable attempt | Lock, identity, credential, idempotency |
| Validate | Recovery report | Independent multi-signal stability window |
| Learn | Outcome record | Human feedback and actual effect |

## APIs and durable records to add

- `service_graph_nodes`, `service_graph_edges`, `service_graph_snapshots`
- `investigations`, `investigation_steps`, `tool_calls`
- `hypotheses`, `hypothesis_evidence_links`
- `resolution_candidates`, `plan_simulations`
- `action_outcome_stats`, `automation_candidates`
- `policy_decisions`, `kill_switches`, `automation_budgets`

Primary APIs:

- `POST /investigations`
- `GET /investigations/{id}`
- `POST /investigations/{id}/next-step`
- `POST /plans/{id}/simulate`
- `POST /plans/{id}/policy-evaluate`
- `POST /executions/{id}/veto`
- `GET /services/{id}/resolution-readiness`
- `GET /automation/opportunities`

## Product experience

The incident workspace should present:

1. Service graph and affected business journeys.
2. Timeline aligned across alert, logs, traces, deploys, config, and operator actions.
3. Hypothesis tree with support, contradictions, and next falsification check.
4. Evidence coverage and missing connectors.
5. Ranked plan alternatives with expected effect and risk.
6. Exact command diff, target, canary, validation, and rollback.
7. Policy explanation and approval fingerprint.
8. Live execution output and veto control.
9. Recovery checks and stability-window countdown.
10. Outcome feedback and proposed knowledge/catalog update.

## Phased implementation

### Phase 0: correctness baseline (now to 2 weeks)

- Preserve diagnostic versus recovered closure semantics.
- Finish current lifecycle consistency and remove legacy UI state derivation.
- Add investigation source coverage and historical outcome visibility.
- Establish baseline precision, unsafe-plan, rollback, and false-closure metrics.

Exit criteria: zero false recovery claims in replay tests and one lifecycle state across API, UI, Jira, and audit.

### Phase 1: iterative investigation (2 to 6 weeks)

- Add durable investigation/tool-call records.
- Let Resolution request targeted read-only Context tools in a bounded loop.
- Add hypothesis support/contradiction/falsification transitions.
- Add `inconclusive`, evidence budget, rate limit, and cancellation.
- Render investigation steps and hypothesis tree.

Exit criteria: >= 80% of conclusions cite two independent evidence planes; unsupported RCA rate < 5% in the golden dataset.

### Phase 2: temporal service graph (4 to 10 weeks)

- Build graph ingestion from onboarding, Kubernetes/cloud discovery, APM, repositories, CI/CD, and CMDB connectors.
- Snapshot the relevant subgraph at incident onset.
- Add reverse impact and change correlation.
- Require graph-bound execution targets.

Exit criteria: >= 95% of onboarded production alerts map to an owned service and deployed version.

### Phase 3: plan compiler and simulation (8 to 14 weeks)

- Split AI intent from deterministic plan compilation.
- Add plan linting, rule preview, counterfactual risk, and sandbox replay.
- Add canary scopes, observation windows, SLO gates, and automatic rollback.
- Add policy budgets and kill switches.

Exit criteria: 100% of executable plans have target identity, validation, rollback/exception, idempotency, and simulation report.

### Phase 4: controlled autonomy (12 to 20 weeks)

- Start with one non-critical service and two reversible actions.
- Run shadow mode, then recommendation-only, HITL, HOTL, auto-canary, and limited auto-full.
- Promote only after statistically meaningful success and rollback performance.
- Add continuous demotion on drift or failures.

Exit criteria: policy-specific precision targets met for four consecutive weeks with no severity-1 automation-caused incident.

### Phase 5: learning and code remediation (16 to 28 weeks)

- Mine successful manual actions into automation candidates.
- Add reviewed code-fix branch: repository scope, patch, tests, security scan, PR, CI, canary deployment, recovery validation.
- Calibrate confidence and action success models from actual outcomes.

Exit criteria: measurable reduction in repeated manual work without increased change-failure rate.

## Metrics and SLOs

Investigation:

- time to first useful evidence;
- time to conclusion;
- evidence-plane coverage;
- conclusive/inconclusive rate;
- RCA precision and calibration error;
- unsupported-claim rate;
- tool failure, timeout, and budget-exhaustion rate.

Planning:

- executable-plan rate;
- plan lint rejection reasons;
- cause-action relevance;
- operator approval/edit/rejection rate;
- simulation-to-actual effect error.

Execution:

- action success, recovery success, and false-success rate;
- rollback rate and rollback success;
- automation-caused incident rate;
- canary abort rate;
- blast radius and error-budget consumed.

Business:

- MTTA, time to conclusion, MTTR, and time to verified recovery;
- incidents avoided by pause/suppression;
- responder minutes saved;
- repeated-incident reduction;
- percentage of services eligible for each autonomy tier.

## Non-negotiable acceptance tests

1. An unrelated historical incident cannot justify a current mutation.
2. A plausible model RCA without admitted citations remains inconclusive.
3. A changed deployment version invalidates incompatible cached resolution memory.
4. A plan cannot execute against a target absent from the incident service graph.
5. Approval for plan A cannot execute plan B.
6. A successful process exit without recovery evidence cannot close an incident.
7. Canary regression automatically stops expansion and triggers rollback.
8. A kill switch blocks queued and new attempts before credential issuance.
9. Duplicate events, deliveries, approvals, and execution submissions remain idempotent.
10. Diagnostic closure never sets `health_restored` or `alerts_cleared` to true.
11. Policy-rule preview identifies shadowed and unreachable automation branches.
12. Every conclusion, decision, action, validation, and learning update is replayable from versioned durable records.

## Recommended next build slice

Implement Phase 1 before adding more automatic actions. The immediate deliverable should be a durable iterative investigation service with:

- read-only tool registry;
- investigation and step tables;
- hypothesis ledger;
- source/time/cost budgets;
- `conclusive` and `inconclusive` stop decisions;
- investigation timeline and hypothesis-tree UI;
- offline replay evaluation against a curated incident set.

This closes the largest gap between the current KaiOps pipeline and the leading systems: the ability to adaptively seek the next most useful evidence instead of making one plan from one static context batch.
