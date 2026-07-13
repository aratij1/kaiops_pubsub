# Deployment Strategy

This runbook defines a practical deployment approach for KaiOps across local, staging, and production.

## Current Runtime Snapshot

Latest checks show local services are reachable:

- UI: http://localhost:8501 returns HTTP 200
- API Gateway: http://localhost:8010/healthz returns status ok
- Approval Service: http://localhost:8007/healthz returns status ok
- Docker Compose core containers are Up

If the UI appears broken while health checks are green, treat it as a functional/runtime error (payload, validation, or stale browser assets), not a platform boot failure.

## Goals

1. Keep incident pipeline available during releases.
2. Prevent bad payload/schema changes from reaching production.
3. Enable fast rollback with clear health gates.
4. Validate end-to-end workflow behavior after every deployment.

## Environment Model

1. Local (Docker Compose): developer integration and bug fixes.
2. Staging (Kubernetes namespace): release candidate verification with production-like dependencies.
3. Production (Kubernetes namespace): progressive rollout with automated rollback gates.

## Release Artifact Strategy

1. Build immutable image per service tagged with git SHA.
2. Publish images to registry.
3. Deploy only pinned tags in staging/prod (never latest).
4. Keep one previous known-good version for rollback.

Example tagging:

- ghcr.io/your-org/kaiops/api-gateway:sha-<commit>
- ghcr.io/your-org/kaiops/ui:sha-<commit>

## Configuration Strategy

1. Keep environment config in ConfigMap and secrets in Secret.
2. Version configuration changes with the same PR as code.
3. Use explicit env values for policy and routing controls.
4. Avoid changing policy thresholds in production without staging soak.

Important knobs to control rollout risk:

- MESSAGE_BUS_DYNAMIC_ROUTING
- MESSAGE_BUS_STREAM_THRESHOLD
- ORCHESTRATION_APPROVAL_SEVERITIES
- CONFIDENCE_GUIDED_EXECUTE_THRESHOLD
- CONFIDENCE_AUTO_EXECUTE_THRESHOLD

## Database and Migration Strategy

1. Apply backward-compatible migrations first.
2. Deploy services second.
3. Validate read/write paths.
4. Remove deprecated schema only after one stable release cycle.

Migration order:

1. Schema migration
2. Backfill migration
3. Service rollout
4. Cleanup migration

## Deployment Phases

### Phase 1: Local Verification

Run:

```powershell
docker compose up -d --build
```

Health checks:

```powershell
$ProgressPreference='SilentlyContinue'
(Invoke-WebRequest -UseBasicParsing http://localhost:8501).StatusCode
(Invoke-WebRequest -UseBasicParsing http://localhost:8010/healthz).Content
(Invoke-WebRequest -UseBasicParsing http://localhost:8001/healthz).Content
(Invoke-WebRequest -UseBasicParsing http://localhost:8007/healthz).Content
```

Functional smoke:

```powershell
Invoke-RestMethod -Method Post -Uri "http://localhost:8010/sample/payment-latency/workflow" | ConvertTo-Json -Depth 10
Invoke-RestMethod -Uri "http://localhost:8010/observability/summary" | ConvertTo-Json -Depth 10
```

### Phase 2: Staging Deployment

1. Deploy namespace baseline from k8s manifests.
2. Update Deployment images with release SHA.
3. Wait for rollouts to finish.
4. Run synthetic incident flow and approval flow tests.

Example rollout commands:

```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/secret.yaml
kubectl apply -f k8s/services.yaml
kubectl apply -f k8s/hpa.yaml
kubectl apply -f k8s/ingress.yaml
kubectl -n kaiops rollout status deployment/api-gateway
kubectl -n kaiops rollout status deployment/monitoring-adapter
```

### Phase 3: Production Progressive Rollout

1. Start with edge services first: ui and api-gateway.
2. Roll out workflow services in this order:
   alert-intelligence -> orchestrator -> context-agent -> resolution-agent -> approval-service -> remediation-engine -> closure-service.
3. Monitor error rate and incident state transitions before each wave.
4. Continue only if gates pass.

Suggested wave pattern:

1. 10 percent traffic
2. 25 percent traffic
3. 50 percent traffic
4. 100 percent traffic

If a service mesh is not available, use Deployment rolling update with low maxUnavailable and staged rollout timing.

## Health Gates and SLO Checks

Gate A: Platform health

- All /healthz endpoints return ok
- No CrashLoopBackOff pods

Gate B: Pipeline continuity

- Events emitted for workflow.selected, context.collected, recommendation.generated
- Remediation and closure events appear for auto paths

Gate C: Incident lifecycle quality

- incident_projections status distribution is stable
- awaiting_approval does not spike unexpectedly
- closed plus failed increase after synthetic runs

Gate D: Approval path

- approval submit succeeds with UUID incident_id and recommendation_id
- gateway returns true downstream status codes (422 must remain 422)

Useful SQL check:

```sql
SELECT status, COUNT(*) AS cnt
FROM incident_projections
GROUP BY status
ORDER BY cnt DESC;

SELECT event_type, status, COUNT(*) AS cnt
FROM incident_events
GROUP BY event_type, status
ORDER BY cnt DESC
LIMIT 30;
```

## Rollback Strategy

1. Roll back only impacted services first.
2. Keep database schema backward compatible so app rollback is safe.
3. Revert image tag to previous stable SHA.
4. Confirm health and incident flow gates again.

Kubernetes rollback examples:

```bash
kubectl -n kaiops rollout undo deployment/api-gateway
kubectl -n kaiops rollout undo deployment/ui
kubectl -n kaiops rollout status deployment/api-gateway
kubectl -n kaiops rollout status deployment/ui
```

Docker Compose rollback example:

1. Switch image tags in compose override file to previous stable tags.
2. Run docker compose up -d --build for only affected services.

## Incident Triage During Deployments

Use this order when something appears "not starting":

1. Check container state with docker compose ps or kubectl get pods.
2. Check /healthz endpoints.
3. Check gateway logs for status codes and payloads.
4. Confirm UI is not using stale cached assets (hard refresh).
5. Validate approval payload UUID fields before submission.

## Operational Recommendations

1. Add a periodic synthetic auto-remediation incident in staging.
2. Alert on sustained awaiting_approval growth.
3. Alert when closure events are missing for more than threshold window.
4. Add deployment dashboard with release SHA, status mix, and event throughput.

## Onboarding Rule Pipelines

KaiOps now supports two onboarding rule pipelines for enterprise onboarding:

1. Existing Rule Sync Pipeline (pull/push)
2. New Rule Onboarding Pipeline (AI-assisted generation)

API endpoints (via API Gateway):

- GET /onboarding/rules/capabilities
- POST /onboarding/rules/pipeline/existing
- POST /onboarding/rules/pipeline/new
- GET /onboarding/rules/pipeline/{workflow_id}

Pipeline 1: Existing Rule Sync

Use this for existing monitoring applications where rules must be pulled from platform and optionally pushed back after governance validation.

Payload highlights:

- project metadata (business and technical context)
- platform (prometheus, datadog, new_relic, etc.)
- mode: pull | push | bidirectional
- rules_to_push (optional)

Pipeline 2: New Rule Onboarding

Use this for net-new application onboarding driven by plain-English requirements.

Payload highlights:

- project metadata
- monitoring_requirements (plain-English policy statements)
- target_platforms
- discovery_inputs

Outputs include:

- generated_rules
- validation and governance checks
- simulation summary
- knowledge documents
- missing_information prompts
- approval_package
- deployment_plan

## Ownership and Change Control

1. Platform owner approves policy changes.
2. Service owner approves schema changes.
3. Release manager approves production rollout/rollback decisions.
4. Post-release review is required for any failed gate.
