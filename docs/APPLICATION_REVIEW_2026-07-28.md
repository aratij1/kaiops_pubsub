# KaiOps Application Design and Code Review

Date: 2026-07-28

## Executive assessment

KaiOps has a sound event-driven target architecture, explicit event contracts, evidence-grounding controls,
database projections, provider routing, and health instrumentation. The main operational failures observed during
this review came from runtime drift away from that architecture: duplicated inline and asynchronous RCA execution,
missing packaged configuration, incomplete UI transparency for reviewed code, and duplicate frontend polling.

The highest-impact safe fixes were implemented and runtime-validated. Larger module decomposition remains necessary
but should be performed incrementally behind contract tests.

## End-to-end design

The authoritative processing path is:

1. `monitoring-adapter` persists and publishes `raw-alerts`.
2. `alert-intelligence` enriches and publishes `enriched-alerts`.
3. `orchestrator` persists the workflow decision and publishes `orchestration-events`.
4. `context-agent` retrieves evidence, persists `incident.context.collected`, and publishes `context-events`.
5. `resolution-agent` produces and persists the recommendation/RCA and publishes `resolution-events`.
6. Approval, remediation, and closure services continue the governed workflow.
7. The UI reads the relational projection through `processed-result` and `stage-completeness`.

## Findings and actions

### Critical: duplicated Context and RCA execution

The orchestrator published the asynchronous orchestration event and then independently called Context and
Resolution over HTTP. Since `/collect` also publishes `context-events`, the same alert could trigger duplicate
retrieval, model calls, recommendation writes, approval events, and cost.

Action: the event-driven chain is now the default. Inline resolution is retained only behind
`ORCHESTRATOR_INLINE_RESOLUTION_ENABLED=true` as an explicit recovery fallback.

### High: configured connection catalog missing from service images

`CONNECTION_CONFIG_PATH` pointed to `backend/config/kaiops-connections.json`, but the common service image copied
`backend/src` and not `backend/config`. Services repeatedly logged a missing-file warning and fell back to defaults.

Action: `backend/config` is now included in `Dockerfile.service`.

### High: code-review result lacked review transparency

The Context Agent retained only reviewed evidence IDs. File URI and excerpt were discarded unless the model produced
a finding, so the UI could claim code was reviewed without showing the reviewed code.

Action: validated code review now returns bounded `reviewed_sources` entries containing evidence ID, source URI, and
the retrieved excerpt. The UI renders these independently of findings and patches.

### Medium: evidence-specific impact overwritten by generic fallback

The MySQL exporter privilege analysis correctly derived loss of replication visibility, then overwrote it with a
generic service-degradation sentence whenever the model provider used a fallback.

Action: deterministic evidence-specific impact now takes precedence over the generic model fallback.

### Medium: duplicate Alert Stream polling

Two React effects independently refreshed the landing-pad stream every ten seconds.

Action: the duplicate effect was removed. Visibility checks and the in-flight guard remain on the canonical poller.

### Medium: oversized modules

The largest modules currently combine too many responsibilities:

- `frontend/react/src/App.jsx`: approximately 18,000 lines.
- `frontend/react/src/styles.css`: approximately 6,200 lines.
- `backend/src/monitoring-adapter/app.py`: approximately 5,800 lines.
- `backend/src/common/common/repository.py`: approximately 2,900 lines.

Recommendation: extract by stable contract boundaries. Start with UI API hooks and alert-detail panels; split
monitoring ingestion workers from HTTP routes; split repository query models from command/event persistence.

### Medium: optional OpenSearch integration floods logs while unavailable

The OpenSearch worker retries at a fixed interval and logs full connection tracebacks while the external endpoint is
offline.

Recommendation: add exponential backoff with jitter, a failure-state transition log, and a readiness/degraded
indicator. Keep the worker isolated from incident projection processing.

### Low: frontend bundle size

The production JavaScript bundle is about 667 KB before gzip and triggers Vite's chunk-size warning.

Recommendation: lazy-load admin, discovery, and alert-detail workspaces after decomposing `App.jsx`; isolate `xlsx`
behind dynamic import because it is needed only for exports.

## Validation

- Modified Python modules compile successfully.
- Production UI image builds successfully.
- Core pipeline test selection: 21 passed, 4 failed.
- The four failures expose pre-existing expectation drift in eager RAG loading, dependency fixtures, confidence
  thresholds, and MySQL fallback impact. The MySQL fallback defect was fixed in this pass.
- All deployed UI, orchestrator, context-agent, and resolution-agent health endpoints return HTTP 200.
- A labeled validation alert persisted exactly the expected core stages:
  `incident.alert.enriched`, `incident.workflow.selected`, `incident.context.collected`, and
  `incident.recommendation.generated`.
- Its `processed-result` contains both context metadata and a recommendation/RCA.

## Recommended next refactoring sequence

1. Add a contract-level event-chain integration test that asserts one logical event per stage and stable
   idempotency keys.
2. Extract React data-access hooks and alert-detail panels without changing payload contracts.
3. Separate monitoring workers into independently deployable processes with individual health states.
4. Split repository reads, commands, and projections into focused modules.
5. Add OpenSearch circuit breaking and dynamic frontend imports.
