# Modernization Phase 22 — Degraded-state UX

## Outcome

Browser connectivity loss now produces a prominent, screen-reader-announced
state while preserving already loaded operational information. The UI no longer
allows a disconnected workspace to look silently current.

## Delivered

- Online/offline lifecycle detection with listener cleanup.
- Sticky warning that states live updates are paused and displayed data may be
  stale.
- Explicit retry action that refreshes only after connectivity returns.
- Responsive banner layout and an automated offline/restore browser scenario.

## Operational interpretation

This banner covers client connectivity. Individual API and dependency failures
continue to use their panel error states and backend readiness/telemetry. A
healthy browser connection is not presented as proof that every downstream
dependency is healthy.
