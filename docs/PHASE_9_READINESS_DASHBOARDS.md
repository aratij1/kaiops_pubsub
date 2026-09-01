# Phase 9 — Readiness and autonomy dashboards

Milestone 19 exposes real per-service and project readiness using configured onboarding controls and deterministic topology results.

The additive cockpit response reports monitoring, logs, traces, topology, runbooks, remediation, validation, automation-policy, and SLO dimensions. Each weak dimension includes a concrete recommendation. The UI distinguishes operational readiness from autonomy readiness and never turns missing configuration into implied coverage.

These scores describe configured evidence and controls; they do not authorize execution. Runtime identity, policy, approval, maintenance-window, blast-radius, validation, and connector gates continue to fail closed.

No migration or event-contract change is required. Existing cockpit consumers remain compatible because the fields are additive.

Known limitation: source presence measures configured coverage, not telemetry quality or live signal volume. Milestone 20 should add production observability and quality gates without fabricating unavailable runtime measurements.
