# KaiMS Cloud-Agnostic Implementation Plan (60 Days)

## 1. Objective
Build and run KaiMS consistently across AWS, Azure, GCP, and on-prem with:
- One application codebase
- One container image set per release
- Provider-specific behavior isolated behind adapters and deployment overlays

## 2. Target Outcomes
By day 60, KaiMS should provide:
1. No direct cloud SDK usage in domain services outside adapter modules.
2. Pluggable providers for secrets, object storage, messaging bridges, identity, and telemetry sinks.
3. Same API and event contracts in every environment.
4. Same operational runbooks and SLO checks independent of cloud provider.

## 3. Design Principles
1. Contracts before providers: API and event schemas are the portability boundary.
2. Inversion of dependencies: domain code depends on interfaces, not vendor SDKs.
3. Build once, deploy many: artifact immutability across environments.
4. Config over forks: profile-based overlays, no cloud-specific service code branches.
5. Progressive replacement: wrap existing implementations before introducing new providers.

## 4. Recommended Folder Structure
Add a shared portability layer under services/common:

```text
services/common/common/portability/
  interfaces/
    secrets.py
    object_store.py
    pubsub_bridge.py
    identity.py
    telemetry_sink.py
    feature_flags.py
  providers/
    local/
      secrets_local.py
      object_store_fs.py
      pubsub_noop.py
      identity_dev.py
      telemetry_stdout.py
    aws/
      secrets_aws.py
      object_store_s3.py
      pubsub_aws_bridge.py
      identity_cognito_oidc.py
      telemetry_otel_aws.py
    azure/
      secrets_azure.py
      object_store_blob.py
      pubsub_azure_bridge.py
      identity_entra_oidc.py
      telemetry_otel_azure.py
    gcp/
      secrets_gcp.py
      object_store_gcs.py
      pubsub_gcp_bridge.py
      identity_google_oidc.py
      telemetry_otel_gcp.py
  registry.py
  settings.py
```

## 5. Core Interfaces (Minimal Contract)
Use small, stable interfaces to avoid lock-in.

### 5.1 SecretsProvider
```python
class SecretsProvider(Protocol):
    async def get_secret(self, key: str) -> str: ...
    async def get_optional_secret(self, key: str) -> str | None: ...
```

### 5.2 ObjectStore
```python
class ObjectStore(Protocol):
    async def put_bytes(self, bucket: str, key: str, data: bytes, content_type: str) -> None: ...
    async def get_bytes(self, bucket: str, key: str) -> bytes: ...
    async def list_keys(self, bucket: str, prefix: str) -> list[str]: ...
```

### 5.3 PubSubBridge
```python
class PubSubBridge(Protocol):
    async def publish(self, topic: str, key: str, payload: dict) -> None: ...
    async def health(self) -> dict: ...
```

### 5.4 IdentityProvider
```python
class IdentityProvider(Protocol):
    async def validate_token(self, token: str) -> dict: ...
    async def resolve_roles(self, principal: dict) -> list[str]: ...
```

### 5.5 TelemetrySink
```python
class TelemetrySink(Protocol):
    def record_counter(self, name: str, value: float, labels: dict[str, str]) -> None: ...
    def record_histogram(self, name: str, value: float, labels: dict[str, str]) -> None: ...
```

## 6. Adapter Wiring Strategy
1. Add a provider registry in services/common/common/portability/registry.py.
2. Select provider via environment profile:
   - KAIOPS_CLOUD_PROFILE=local|aws|azure|gcp
3. Resolve providers at startup and inject them into services through existing settings/bootstrap modules.
4. Fail fast on missing mandatory provider configs.

## 7. Service-by-Service Refactor Map
Scope aligned to current service topology.

1. api-gateway
- Move token validation and role resolution to IdentityProvider.
- Move secret reads to SecretsProvider.

2. monitoring-adapter
- Move rules/artifact persistence to ObjectStore abstraction when needed.
- Keep Prometheus path as portable baseline; provider-specific integrations behind adapters.

3. alert-intelligence, orchestrator, context-agent, resolution-agent
- Keep domain logic unchanged.
- Replace direct provider calls (if any) with portability interfaces.

4. approval-service
- Integrate outbound channels through adapter wrappers where cloud services are used.

5. remediation-engine
- Wrap cloud-specific execution hooks behind provider-specific automation adapters.

6. closure-service
- Persist artifacts via ObjectStore abstraction when using cloud object stores.

7. model-router
- Keep vendor model routing policy-based.
- Avoid provider assumptions in request/response normalization.

## 8. Deployment Model (Cloud-Agnostic)
1. Keep base manifests and compose config provider-neutral.
2. Add overlays per provider:

```text
k8s/
  base/
  overlays/
    local/
    aws/
    azure/
    gcp/
```

3. Overlays should only change:
- Ingress and load balancer annotations
- Secret references
- Storage class and PVC classes
- Managed identity annotations
- Provider-specific observability exporters

## 9. CI/CD Changes
1. Build stage
- Build and sign images once.
- Generate SBOM once.

2. Verify stage
- Contract tests (API + events) must pass once per release.
- Portability lint checks reject direct cloud SDK imports outside provider modules.

3. Deploy stage
- Promote same image digest through local -> non-prod -> prod overlays.

## 10. Portability Guardrails
1. Add an import rule check in CI to block vendor SDK imports in domain packages.
2. Add a startup self-check endpoint to print active cloud profile and provider bindings.
3. Add conformance tests that run on each profile:
- secrets read/write
- object put/get/list
- pubsub publish smoke
- identity token validation

## 11. 60-Day Execution Plan

### Days 1-10: Baseline and Contracts
1. Freeze API and event schemas for portability-critical flows.
2. Add portability interfaces and registry scaffolding.
3. Implement local provider pack fully.
4. Add CI rule for forbidden direct cloud imports.

Deliverables:
- portability interfaces
- local providers
- CI portability lint

### Days 11-20: Identity and Secrets Decoupling
1. Refactor api-gateway auth and secret reads to adapters.
2. Add aws/azure/gcp secrets providers.
3. Add identity provider adapters (OIDC-compatible).

Deliverables:
- adapterized auth and secrets path
- profile-based identity and secrets config

### Days 21-30: Storage and Artifact Portability
1. Add ObjectStore adapters (S3/Blob/GCS/local).
2. Refactor monitoring-adapter and closure-service artifact writes.
3. Add storage conformance tests.

Deliverables:
- object store adapters
- portable artifact path

### Days 31-40: Messaging and Execution Bridges
1. Keep Kafka as canonical app bus.
2. Add optional provider bridge adapters where needed.
3. Refactor remediation hooks to provider execution adapters.

Deliverables:
- messaging bridge interfaces
- remediation provider adapters

### Days 41-50: Deployment Overlays and Observability
1. Create k8s base plus overlays for local/aws/azure/gcp.
2. Keep OpenTelemetry + Prometheus contracts provider-neutral.
3. Add deployment profile smoke tests.

Deliverables:
- overlay manifests
- profile smoke pipelines

### Days 51-60: Hardening and Release Readiness
1. Run full E2E on at least two non-local providers.
2. Run failover drills (secrets unavailable, object store timeout, pubsub transient failure).
3. Finalize runbooks and cloud-agnostic ops checklist.

Deliverables:
- cross-cloud E2E evidence
- failure drill report
- release checklist

## 12. Success Metrics
1. Code metric: 0 direct vendor SDK imports in domain services.
2. Delivery metric: same image digest deployed across all profiles.
3. Runtime metric: E2E pass rate >= 95% in each provider profile.
4. Ops metric: same incident triage runbook usable across providers.

## 13. Immediate Next Steps for This Repo
1. Create services/common/common/portability/interfaces and local providers first.
2. Refactor api-gateway to use IdentityProvider and SecretsProvider.
3. Add k8s/base and first overlay (gcp or aws, whichever is current target).
4. Add CI portability lint and profile smoke job.
