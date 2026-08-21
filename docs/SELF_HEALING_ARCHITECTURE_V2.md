# KaiOps Self-Healing Architecture v2

## Objective

KaiOps separates probabilistic diagnosis from deterministic execution. Models
may rank hypotheses and propose intents; only a reviewed catalog can bind an
intent to a target, connector, command, approval policy, rollback strategy, and
recovery check.

## Control loop

1. Ingest and normalize alerts into a tenant-scoped event envelope.
2. Correlate alerts into an incident and construct an evidence graph.
3. Produce RCA hypotheses with citations, confidence, and explicit unknowns.
4. Resolve a versioned catalog playbook for the affected service and signal.
5. Persist an immutable execution plan and fingerprint before approval.
6. Apply policy using risk, blast radius, environment, confidence, and history.
7. Dispatch through a connector-specific executor with idempotency protection.
8. Capture preflight, execution, validation, and rollback evidence separately.
9. Close only when objective recovery checks pass.
10. Learn from confirmed outcomes; never promote generated runbooks directly.

## Service boundaries

- Ingestion plane: adapters normalize signals but do not diagnose or mutate.
- Intelligence plane: correlation, context, RCA, and impact analysis are read-only.
- Control plane: policy, approvals, execution plans, and workflow state are durable.
- Execution plane: narrow connector plugins execute catalog-bound operations.
- Verification plane: independent checks decide recovery and rollback.
- Learning plane: outcome records influence ranking after governance review.

Each service owns routers, application services, domain models, and adapters.
Cross-service data is exchanged through versioned event contracts rather than
imports or shared mutable state.

## Database ownership

The existing event log remains the source of incident history. The v2 control
plane adds normalized `execution_plans`, `remediation_attempts`,
`recovery_evidence`, and `remediation_outcomes` tables. These make authorization,
retries, verification, and learning queryable without parsing arbitrary JSON.
The migration is additive so old and new services can coexist during rollout.

## UI information architecture

The primary operator journey is: Detect → Investigate → Decide → Execute →
Verify → Learn. Every incident view must show the evidence supporting RCA, the
exact target and executable plan, policy gates, live attempt state, validation
results, and rollback availability. Administrative onboarding and knowledge
authoring remain separate from the incident cockpit.

## Non-negotiable safety invariants

- No model-produced shell text executes directly.
- Detector identity never implies mutation-target identity.
- Production mutation requires a catalog operation and credential reference.
- Every mutation has validation and either rollback or an explicit irreversible policy.
- Plan fingerprints and idempotency keys are checked before dispatch.
- Closure requires independent recovery evidence.
- Failed or operator-modified runbooks are suspended from automatic reuse.

## Resilience and error boundaries

Every HTTP service created through `common.service.create_app` emits the
versioned `kaiops.error.v1` contract. The contract classifies validation,
request, dependency, downstream, and internal failures; preserves the legacy
`detail` field; carries a trace identifier; and explicitly declares whether a
read operation is safe to retry. Rejected payload values and internal exception
messages are never returned to clients.

The web client validates successful responses with Zod and normalizes failed
responses into `ApiRequestError`. Query retries are limited to errors explicitly
marked retryable, mutations never retry automatically, and route rendering is
protected by a safe fallback with trace context and deterministic recovery
actions. Chunk loading retains its bounded retry and single-reload guard.

Fallbacks must remain observable and honest: cached or partial data must be
labelled, model fallbacks cannot bypass deterministic execution policy, and an
error boundary may preserve access to navigation but must never present a
failed mutation as successful.

## Runtime and technology decision

KaiOps uses two complementary workflow runtimes with deliberately different
authority. LangGraph owns bounded, read-only intelligence graphs: evidence
collection, hypothesis generation, impact analysis, and ranked remediation
intent. Temporal owns the durable control loop: approval interrupts,
fingerprint-bound execution, retry, timeout, compensation, validation, and
closure. RabbitMQ transports integration events but is not a workflow state
store. Jenkins remains an execution adapter for existing operational jobs; it
does not own incident lifecycle state and can be replaced per connector without
changing the control plane.

The next deployment target is Azure Container Apps for stateless APIs and
event-driven discovery workers, with Temporal workers kept continuously
available. Moving directly to a new agent framework or allowing generated tool
calls to execute would reduce determinism and is therefore rejected.

Intelligence containers have explicit CPU, memory, process, startup, shutdown,
health, and Linux capability boundaries. These limits prevent an expensive or
stalled model/context request from degrading the execution and verification
planes. Image minimization and per-service dependency locks remain a staged
migration because the current shared image is still required by code-discovery
and legacy imports.

## Accuracy contract

Accuracy is measured as a chain of evidence, not a single model confidence:

1. Context records source identity, freshness, reliability, contradictions,
   connector failures, and collection budget exhaustion.
2. RCA cites accepted evidence identifiers and retains alternative causes and
   missing evidence. Uncited output is confidence-capped.
3. Resolution binds intent only to a versioned catalog plan. The finalized plan
   is authoritative about whether corrective capability exists.
4. Policy combines evidence sufficiency, RCA and impact confidence, fallback
   use, environment, risk, blast radius, validation, and rollback readiness.
5. Executor success never means recovery; independent validation controls
   closure and supplies outcome evidence for later ranking.

The UI consumes these persisted contracts. It must not reconstruct approval or
execution eligibility from command text after the typed control projection is
available. Legacy inference is migration-only and must fail closed.
