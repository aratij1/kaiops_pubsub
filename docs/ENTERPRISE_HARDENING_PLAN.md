# Enterprise Hardening Plan

This document turns the latest architecture/code review into an execution-ready remediation plan.

## Scope

- Security hardening
- Reliability and recoverability
- Data durability and auditability
- Deployment consistency and production controls
- CI/CD quality gates

## Delivery Model

- Priority order: P0 -> P1 -> P2
- Each item has: owner, implementation target, acceptance criteria
- Use feature flags where rollout risk exists

## P0 (Blockers)

### 1) Compose dependency and runtime consistency
- Owner: Platform Engineering
- Files:
  - `docker-compose.yml`
- Problem:
  - `model-router` depends on `postgres` service that is not defined.
- Implementation:
  - Remove invalid `postgres` dependency.
  - Align dependencies to actual DB/service topology in compose.
- Acceptance criteria:
  - `docker compose up --build` starts all services without unresolved dependency errors.
  - Health checks pass for all API services.

### 2) K8s secret/config DB mismatch
- Owner: Platform Engineering
- Files:
  - `k8s/create-secret.ps1`
  - `k8s/configmap.yaml`
- Problem:
  - K8s secret still uses postgres URL while codebase/runtime is MySQL-first.
  - Placeholder API keys remain in manifest.
- Implementation:
  - Generate the deployment secret out of band from environment or secret manager values.
  - Remove committed secret manifests and document the runtime secret creation workflow.
- Acceptance criteria:
  - K8s deployment connects to intended DB backend.
  - Secret values are managed outside git (or encrypted workflow).

### 3) Pending approval state durability
- Owner: Monitoring Adapter + Data Engineering
- Files:
  - `services/monitoring-adapter/app.py`
  - `services/common/common/repository.py`
  - `database/schema.sql`
- Problem:
  - `PENDING_WORKFLOWS` in-memory map loses state on restart.
- Implementation:
  - Persist pending workflow continuation payload in DB (new table or extension of existing metadata model).
  - Use idempotent continuation endpoint keyed by incident and recommendation IDs.
- Acceptance criteria:
  - Restart during pending approval does not lose continuation ability.
  - Duplicate continue requests are safely idempotent.

### 4) Silent failures in background workers
- Owner: Monitoring Adapter
- Files:
  - `services/monitoring-adapter/app.py`
- Problem:
  - Bare `except Exception: pass` hides projection/ingestion failures.
- Implementation:
  - Replace silent catches with structured error logging and failure counters.
  - Add health degradation flag if repeated failures exceed threshold.
- Acceptance criteria:
  - Worker failures appear in logs/metrics.
  - `/readyz` reflects degraded state when critical worker loops fail repeatedly.

## P1 (High Impact)

### 5) Message reliability contract (DLQ + retry semantics)
- Owner: Messaging Platform + Service Owners
- Files:
  - `services/common/common/kafka.py`
  - `services/common/common/rabbitmq.py`
- Problem:
  - Kafka auto-commit and RabbitMQ `requeue=False` can drop failed messages without replay policy.
- Implementation:
  - Introduce explicit retry policy and dead-letter flow for both transports.
  - Define poison-message handling and observability.
- Acceptance criteria:
  - Failed message processing produces retry attempts and DLQ entries.
  - No untracked message loss for handler exceptions.

### 6) Token/session hardening
- Owner: API Gateway Security
- Files:
  - `services/api-gateway/api_gateway/modules/users/service.py`
  - `services/api-gateway/api_gateway/modules/users/permissions.py`
- Problem:
  - Refresh token is reused without rotation.
  - Access token auth path does not consult revocation/session state.
- Implementation:
  - Implement refresh token rotation (new jti each refresh, revoke previous session).
  - Add access-token revocation model (short TTL + deny-list/session check).
  - Enforce strict validation of `sub`, `jti`, and session status.
- Acceptance criteria:
  - Reused refresh token is rejected after rotation.
  - Logout/session revoke invalidates subsequent token use per policy.

### 7) Agent work item history model
- Owner: Data Model + Monitoring Adapter
- Files:
  - `database/schema.sql`
  - `services/common/common/database.py`
  - `services/common/common/repository.py`
- Problem:
  - Composite PK `(incident_id, agent_name)` overwrites repeated attempts.
- Implementation:
  - Move to append-only key model (e.g., `id` PK + unique constraints by attempt/sequence where required).
  - Preserve full retry lineage for forensic auditing.
- Acceptance criteria:
  - Multiple entries for same agent/incident can coexist across retries.
  - UI queue and audit views show chronological attempt history.

### 8) Alert intelligence state consistency across replicas
- Owner: Alert Intelligence + Data Engineering
- Files:
  - `services/alert-intelligence/alert_intelligence/agents/alert/intelligence.py`
  - `services/common/common/repository_interfaces.py`
- Problem:
  - In-memory history repository yields inconsistent dedup/correlation in horizontal scale.
- Implementation:
  - Back alert history with persistent/shared store (DB or Redis) behind repository port.
  - Add bounded read window and indexed query path.
- Acceptance criteria:
  - Dedup/correlation behavior is stable across service restarts and replica distribution.

## P2 (Operational Maturity)

### 9) Kubernetes production hardening baseline
- Owner: Platform Engineering
- Files:
  - `k8s/services.yaml`
  - `k8s/ingress.yaml`
- Problem:
  - Missing resource requests/limits and container security contexts.
  - No TLS section on ingress.
- Implementation:
  - Add `resources.requests/limits`, `securityContext` (`runAsNonRoot`, `readOnlyRootFilesystem`, `allowPrivilegeEscalation: false`).
  - Add ingress TLS and cert management integration.
  - Add NetworkPolicy manifests.
- Acceptance criteria:
  - Pods pass admission/security policies.
  - Ingress traffic is TLS-terminated.

### 10) Audit retention and long-term observability
- Owner: API Gateway + SRE
- Files:
  - `services/api-gateway/app.py`
- Problem:
  - Gateway audit stream retained only in memory (`deque(maxlen=200)`).
- Implementation:
  - Persist gateway audit events to DB/log sink.
  - Add retention policy and queryable dashboard.
- Acceptance criteria:
  - Audit events survive restarts and satisfy retention requirements.

### 11) CI security gates
- Owner: DevSecOps
- Files:
  - `.github/workflows/ci.yml`
- Problem:
  - No SAST/dependency/container security scan stages.
- Implementation:
  - Add stages for dependency audit, static security checks, and image scanning.
  - Fail on critical vulnerabilities in protected branches.
- Acceptance criteria:
  - Pull requests surface security findings before merge.

## Suggested Rollout Sequence

1. Fix deployment blockers and config drift (P0-1, P0-2)
2. Add state durability and worker failure visibility (P0-3, P0-4)
3. Introduce messaging reliability controls (P1-5)
4. Harden auth/session lifecycle (P1-6)
5. Upgrade data model for work history + alert state backend (P1-7, P1-8)
6. Complete infra/CI hardening (P2)

## Validation Matrix

For each completed item, capture:
- Test evidence: unit + integration + failure-injection scenario
- Runtime evidence: metrics/logs/traces screenshots or links
- Rollback plan: explicit command/procedure
- Residual risk note: what is still not covered
