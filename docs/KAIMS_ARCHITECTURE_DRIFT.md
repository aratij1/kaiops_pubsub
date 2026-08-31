# KaiMS Architecture Drift

Audit basis: executable source, Docker Compose, Kubernetes manifests, gateway routes, event constants, and CI at `df335b6ba8533f6b2bdc84dea5de1b8f22994bb2`.

## DOCUMENTED_BUT_MISSING

- A configured `main` branch and the requested `ashneevai/kaims` remote are absent from this checkout; the supplied baseline cannot be verified here.
- One durable `IncidentWorkflowService` owning every incident transition does not exist as a single service. Lifecycle validation is centralized in a shared reducer, while transition initiation remains distributed across resolution, approval, remediation, and closure.
- The requested full `IncidentExecutionState` vocabulary is not implemented verbatim. The active resolution lifecycle begins at `ANALYZING`; detection, normalization, correlation, triage, and evidence collection remain represented by service/domain status and events.
- A single canonical `ResourceGraph` joining discovery, onboarding topology, runtime discovery, and CMDB is not yet the sole persistence contract.
- The Kubernetes manifests do not deploy every service available in Compose, notably cloud operations and several onboarding/learning workers.
- CI has no mandatory real Kubernetes closed-loop incident recovery test with validation and rollback evidence.

## IMPLEMENTED_BUT_UNDOCUMENTED OR UNDER-DOCUMENTED

- `cloud-operations` is a substantial executable control plane with connection, discovery, topology, planning, simulation, approval, execution, rollback, governance, and readiness routes, but the README's core architecture table does not present it as part of the canonical path.
- The versioned command/event/result/retry/DLQ topic taxonomy coexists with legacy topics without a documented cutover owner or date.
- Approval capacity/tenant isolation, validation observations, draft-PR outbox, artifact governance, and cloud governance migrations extend beyond the README service narrative.
- The closure reconciler and actor-authorized lifecycle reducer are stronger runtime controls than the high-level README flow communicates.

## DEAD

- `code-analysis-events` remains in the shared topic contract although the current core resolution path does not expose a corresponding deployable backend service.
- Root-level source directories such as `audit-service` and `notification-service` are not part of the broad default Compose service list and should be proven by deployment references before being called production runtime.
- Any execution path returning `SKIPPED` because no real executor is configured is a deliberate fail-closed stub, not a working remediation capability.

## DUPLICATE

- Incident progress is represented by legacy incident status, orchestration metadata, resolution lifecycle state, event delivery, and UI workflow-stage reducers. The resolution lifecycle is the authority for remediation/closure, but the other projections can drift.
- Discovery exists in `discovery-service`, `discovery-mcp`, application onboarding, and cloud operations. These are multiple graph producers without one enforced canonical ResourceGraph.
- Recovery checks exist across validation agents, remediation result handling, closure validation, and common outcome-validation contracts.
- Docker Compose, Kubernetes, and Azure deployment definitions describe overlapping but unequal service topologies.

## EXPERIMENTAL

- `temporal-pilot` is an optional durable-orchestration path rather than the universal lifecycle owner.
- The versioned enterprise topic taxonomy is additive; legacy routing remains active.
- Cloud operations expands the platform beyond the requested single proven Kubernetes executor and should not be treated as proof of closed-loop recovery.
- Generated knowledge-development and draft-PR learning flows are post-incident capabilities, not prerequisites for the core recovery claim.

## CANONICAL_RUNTIME

- Signal intake and normalization: `monitoring-adapter` and `alert-intelligence`.
- Incident coordination: `orchestrator`, with persisted incident records and shared lifecycle validation.
- Evidence/RCA/planning: `context-agent` and `resolution-agent`.
- Immutable authorization: typed execution plan, plan fingerprint, policy decision, and persisted approval.
- Execution: `remediation-engine`; connectors must fail closed without approved typed operations, capabilities, credentials, and live configuration.
- Recovery proof and terminal state: `closure-service` plus its validation/reconciliation contracts.
- Operator/API surface: `api-gateway` and the React incident workspace.

## Priority drift closure

1. Make one persisted workflow coordinator the only writer of incident lifecycle transitions; services should submit commands/results to it.
2. Map intake and investigation states into the durable state model so the canonical lifecycle starts at `DETECTED`, not `ANALYZING`.
3. Remove all remaining command/prose-to-action inference and require a schema-valid typed operation. This audit removes the remediation-engine command-text fallback; test helpers may still synthesize typed plans but have no runtime authority.
4. Select one graph persistence contract and make discovery/onboarding/cloud components producers to it.
5. Add a mandatory, hermetic Kubernetes incident test proving duplicate delivery protection, approval binding, actual execution, recovery validation, and rollback on failed validation.
6. Reconcile Compose, Kubernetes, Azure, README, and gateway route inventories through an automated architecture-drift check in CI.
