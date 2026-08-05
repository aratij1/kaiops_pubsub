# KaiOps modernization: Phase 11 report

Date: 2026-08-04 (Asia/Calcutta)

## Scope completed

An opt-in Temporal pilot now owns only Context → Resolution → Human Approval → Remediation Decision. RabbitMQ remains the default and continues to own alert intake and broad events. The workflow has durable state, bounded retries with exponential backoff, activity timeouts, an approval timer/wait, approval and cancellation signals, a status query, incident-derived workflow IDs, idempotency headers, and a durable compensation hook.

## Files created

- `backend/src/temporal-pilot/temporal_pilot/__init__.py`
- `backend/src/temporal-pilot/temporal_pilot/workflow.py`
- `backend/src/temporal-pilot/temporal_pilot/activities.py`
- `backend/src/temporal-pilot/temporal_pilot/worker.py`
- `docs/MODERNIZATION_PHASE_11_REPORT.md`

## Files modified

- `pyproject.toml`
- `deploy/docker/requirements.service.txt`
- `deploy/docker/Dockerfile.service`
- `docker-compose.yml`
- `backend/src/common/common/config.py`
- `backend/src/orchestrator/app.py`
- `backend/src/approval-service/app.py`
- `ai-workbench/src/context-agent/app.py`
- `ai-workbench/src/resolution-agent/app.py`

## Architecture decisions

1. `TEMPORAL_PILOT_ENABLED=false` is the safe default.
2. Incident-derived workflow IDs prevent replayed intake from starting duplicate workflows.
3. Context and Resolution add backward-compatible `publish_events` query flags so the pilot does not duplicate downstream bus work.
4. Approval-service signals Temporal when enabled and falls back to the existing approval event if signaling fails.
5. MySQL remains authoritative for incidents, recommendations, approvals, remediation actions, and audit metadata.
6. Compensation truthfully returns `rollback_required`; it does not claim rollback ran because remediation-engine has no rollback API.
7. Temporal Server is an external/managed dependency addressed by `TEMPORAL_ADDRESS`; the repository does not create a second business database.

## Existing functionality preserved

- default RabbitMQ orchestration and all existing message topics
- optional Kafka routing
- context, resolution, approval, remediation, and audit persistence
- current APIs; added query flags default to existing publication behavior

## API contracts affected

Backward-compatible query parameter:

```text
POST /collect?publish_events=false
POST /resolve?publish_events=false
```

Pilot control endpoints on orchestrator:

```text
POST /temporal/workflows/{incident_id}/approval
POST /temporal/workflows/{incident_id}/cancel
GET  /temporal/workflows/{incident_id}/status
```

## MySQL impact

No schema change. Temporal is not the system of record. No PostgreSQL or pgvector integration was introduced by this phase.

## Security implications

- the pilot uses the existing internal service network and optional AI-layer bearer token
- activity IDs are propagated as idempotency keys
- remediation-engine remains the final allowlist and persistence boundary
- pilot control endpoints are internal; external exposure must remain behind API-gateway authorization

## Feature flags added

- `TEMPORAL_PILOT_ENABLED` (default `false`)
- `TEMPORAL_ADDRESS`
- `TEMPORAL_NAMESPACE`
- `TEMPORAL_TASK_QUEUE`
- `TEMPORAL_APPROVAL_TIMEOUT_HOURS`

## Tests and commands

```text
Python compile of pilot and touched services                 PASS
docker compose config --quiet                               PASS
docker compose --profile temporal-pilot build worker        PASS after packaging correction
Temporal SDK workflow/activity import in built image         PASS
Direct approval/cancel signal and status-query smoke test    PASS
```

The first worker image exposed that production images install `requirements.service.txt` rather than `pyproject.toml`; the SDK and source path were added to both production packaging surfaces and the rebuilt image passed.

## Performance considerations

The flag-off path adds only a boolean branch. The pilot worker is a separate optional process. Activity retries are bounded to five attempts with exponential backoff and one-minute maximum spacing.

## Known limitations

- a reachable Temporal Server/Cloud namespace must be provisioned separately
- a full Temporal test-server integration suite is still required in CI
- compensation records `rollback_required` because no backend rollback endpoint exists
- approval signal failure uses the existing bus fallback to preserve availability; reconciliation should alert on that event
- Temporal Web/UI deployment and mTLS/API-key configuration are environment concerns not embedded in application source

## Rollback procedure

Set `TEMPORAL_PILOT_ENABLED=false` and restart orchestrator/approval-service. The normal message-bus workflow resumes without data migration. The worker can then be stopped. Existing MySQL business records remain valid.

## Recommended next phase

Proceed directly to Phase 12 message-bus abstraction, retaining external-event responsibilities and making RabbitMQ/Kafka/Azure Service Bus selection explicit without coupling it to Temporal.
