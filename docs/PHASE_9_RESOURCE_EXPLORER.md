# Phase 9 — Unified Resource Explorer

Milestone 17 replaces the cloud-only inventory grid with one consistent Operational Digital Twin explorer for applications, services, cloud, Kubernetes, infrastructure, databases, messaging, and data pipelines.

## Implemented

- Tenant isolation remains enforced by the API gateway; project, service, and environment narrow the visible scope.
- Deterministically discovered resources are grouped into operator-facing domains without changing stored resource types.
- Search covers display name, stable provider identity, type, provider, service, environment, and region.
- Health filtering and explicit result counts expose degraded assets without implying missing telemetry is healthy.
- Selection exposes stable identity, ownership, discovery time, connection provenance, and service topology relationships.
- The entity sidebar, filter bar, resource list, health, relationships, and detail pattern is consistent across domains.
- Responsive behavior collapses the domain rail and dense resource columns on smaller displays.

## Compatibility and rollback

No schema, event, or API changes are required. The explorer reuses `GET /cloud-ops/resources` and `GET /cloud-ops/services/{service_id}/topology`; older clients remain compatible. Rollback is limited to reverting the route, stylesheet, and navigation copy.

## Verification

Unit coverage verifies deterministic resource-domain classification. Frontend type checking, unit tests, and the production build are the milestone gates.

## Known limitations

- Domain classification is a presentation mapping over provider-normalized types; connector metadata should eventually supply an explicit canonical domain.
- Relationship drill-down is service-scoped because the existing topology API is service-scoped.
- Resources without a service mapping correctly show that topology is unavailable instead of fabricating relationships.

## Recommended next milestone

Milestone 18: global Kai command palette and Copilot experience.
