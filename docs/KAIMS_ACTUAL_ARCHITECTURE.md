# KaiMS Actual Architecture

Audit date: 2026-08-24  
Audited working commit: `df335b6ba8533f6b2bdc84dea5de1b8f22994bb2`  
Branch: `fix/kaims-resolution-production-readiness`  
Closest configured remote base: `origin/kaiops_azure` at `f211b688250f4a4e3b6ac3fc230b0d753ffffa45`

The requested baseline `0223710ac8ec30e036f53d61353d55a0da0c4f08` is not in the configured repository. The configured `origin` is `https://github.com/aratij1/kaiops_pubsub.git`, which has no `main` ref. This audit therefore records the executable working tree and does not treat README prose as authority.

## Executable service inventory

`backend/src/` contains these service roots:

| Classification | Services |
| --- | --- |
| Canonical incident runtime | `monitoring-adapter`, `alert-intelligence`, `orchestrator`, `approval-service`, `remediation-engine`, `closure-service`, `api-gateway` |
| Control-plane/runtime support | `application-onboarding`, `cloud-operations`, `discovery-service`, `discovery-mcp`, `audit-service`, `notification-service`, `knowledge-development-worker`, `prometheus-config-service` |
| Onboarding pipeline workers | `metrics-validation-agent`, `rule-generation-agent`, `validation-agent`, `dashboard-generator` |
| Orchestration experiment | `temporal-pilot` |
| Shared library, not a service | `common` |

The AI workbench supplies executable `context-agent`, `model-router`, `resolution-agent`, and `evaluation-service` processes under `ai-workbench/src/`. Resolution intelligence is therefore implemented, but it is outside `backend/src/`.

## Canonical deployed path

The currently executable Docker Compose path is:

`monitoring-adapter -> alert-intelligence -> orchestrator/context-agent -> resolution-agent -> approval-service or remediation-engine -> closure-service -> knowledge-development-worker`

RabbitMQ is the default message bus. `temporal-pilot-worker` provides durable remediation orchestration when enabled. MySQL is the durable system of record; Redis supports runtime coordination/caching. API Gateway exposes the operator and UI contract. The React UI consumes that gateway.

Lifecycle authority is represented by `common.resolution_lifecycle`: it validates legal edges, actor authority, plan fingerprint, and optimistic `state_version`. Durable action identity is enforced through remediation idempotency keys and persisted actions. Closure owns recovery/closure transitions.

## Event contract

The active legacy topics in `backend/src/common/common/topics.py` are:

`raw-alerts`, `jira-investigations`, `enriched-alerts`, `orchestration-events`, `context-events`, `code-analysis-events`, `resolution-events`, `approval-events`, `remediation-events`, `closure-events`, and `learning-events`.

Onboarding and cloud operations also use named domain events. A parallel versioned taxonomy exists (`kaiops.commands.v1`, `kaiops.events.v1`, `kaiops.results.v1`, `kaiops.retry.v1`, `kaiops.dlq.v1`, `kaiops.notifications.v1`) but is not yet the sole runtime contract.

## Deployment surfaces

- Docker Compose is the broadest runnable topology and includes the resolution agent, cloud operations, onboarding workers, Temporal worker, Jenkins, observability, and demo applications.
- `k8s/services.yaml` deploys the narrower core: monitoring adapter, API gateway, alert intelligence, orchestrator, context agent, model router, resolution agent, approval, remediation, closure, and UI.
- Kubernetes HPA/PDB coverage exists for selected hot-path services, not every Compose service.
- CI runs Python lint/tests, governed catalog validation, React quality/build budgets, dependency audits, Docker image builds, and Kubernetes client-side validation. The real ingestion load test is manual only.

## Runtime authority

Executable remediation authority is the immutable `kaims.execution-plan.v2` typed action plus its fingerprinted approval/execution contract. Natural-language recommendations are display/context only. Missing or invalid typed operations fail closed with `UNSUPPORTED_ACTION_PLAN`. Connector implementations must remain non-successful when live executor configuration or credentials are unavailable.

## Current proof boundary

The repository contains strong contract and component tests, but CI does not continuously prove a real signal-to-recovery Kubernetes incident. Production readiness therefore stops at “implemented and contract-tested”; it does not yet establish a continuously reproducible closed-loop recovery SLO.
