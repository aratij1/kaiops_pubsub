# Modernization Phase 16 — Authenticated SSE Live Updates

## Outcome

KaiOps now exposes a production-authenticated, tenant-scoped SSE stream for alert, incident, approval, remediation, and connector changes. The React client consumes the stream with resumable IDs and updates TanStack Query caches while retaining 60-second polling as a degraded fallback.

## Scope completed

- Added `GET /events/operations` with `text/event-stream`, event IDs, typed events, heartbeats, anti-buffering headers, and `Last-Event-ID` resume support.
- Enforced bearer authentication for the stream outside local/demo/test environments.
- Scoped business-record queries by the authenticated tenant.
- Restricted connector-health events to administrators.
- Added `alert.created`, `incident.status`, `approval.state`, `remediation.progress`, `connector.health`, and `heartbeat` event types.
- Added active-connection and emitted-event Prometheus metrics.
- Added a fetch-stream React client so bearer headers remain supported (native `EventSource` cannot set them).
- Added bounded event-ID deduplication, exponential reconnect backoff, hidden-tab suspension, Query-cache invalidation, connection-state UI, last-event timestamp, and Pause/Resume control.
- Preserved selected alert rows: push refresh does not reorder the alert list while a detail record is selected.
- Preserved slower existing polling as fallback when push is unavailable.

## Contracts and security

The endpoint is additive; existing REST contracts and polling remain unchanged. Event payloads contain IDs, state, tenant correlation, and timestamps—not raw alerts, commands, credentials, or sensitive payloads. Clients retrieve canonical authorized data through the existing REST/Query path.

## MySQL impact

No schema change. The stream performs bounded, indexed `updated_at` queries and tenant filters against existing operational tables. Connector health is emitted only for administrators.

## Validation

- Backend Python compile: passed.
- Frontend TypeScript check: passed.
- Frontend unit tests: 14 passed.
- Frontend production build: passed.
- App bundle: 660.58 kB / 160.69 kB gzip; CSS: 133.13 kB / 24.61 kB gzip.
- Authentication policy regression now asserts the SSE route requires an authenticated user.

## Known limitations

Broker-native queue depth/age changes do not yet have a durable provider-neutral source (documented in Phase 12). Heartbeats therefore identify queue health as polling fallback rather than inventing a healthy state. Phase 18 will add provider telemetry and publish real queue-health changes through this stream.

The existing application retains a large compatibility chunk; route-level extraction remains technical debt and is tracked separately.

## Rollback

Remove the React `useOperationalEvents` hook usage and the `/events/operations` route/auth rule. Existing polling continues to provide the prior behavior without data migration.

## Recommended next phase

Phase 17: replace production local authentication with deployment-selected Entra ID or Keycloak OIDC while preserving explicitly labelled local development authentication.
