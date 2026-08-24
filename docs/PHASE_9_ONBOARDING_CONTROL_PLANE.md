# Phase 9 Onboarding Control Plane

Milestone 11 adds a resumable, versioned 12-step onboarding control plane while
preserving the existing `/applications` APIs.

The workflow covers project identity, environments, technology discovery,
observability, incident sources, change sources, resolution connections,
knowledge, discovery, monitoring recommendations, capability autonomy policy,
and end-to-end validation. Steps are sequential, support save/resume, and use
optimistic versions to prevent two operators from silently overwriting a draft.

Connector selections expose Connected, Connection failed, Permission
insufficient, Secret unavailable, and Pending states. Only opaque provider
`secret_ref` values are accepted; raw credentials are rejected.

Operational readiness is derived from observed evidence across Monitoring,
Telemetry, Topology, Change Intelligence, Knowledge, RCA, Remediation, and
Validation. A dimension is marked ready only at 100% with evidence. Production
`AUTO_EXECUTE` is blocked unless all mandatory monitoring, telemetry, topology,
RCA, remediation, and validation gates pass.

## APIs

- `POST /onboarding/projects`
- `GET /onboarding/projects/{onboarding_id}`
- `PUT /onboarding/projects/{onboarding_id}/steps/{step}`
- `POST /onboarding/projects/{onboarding_id}/readiness`

Tenant-scoped reads and updates require `X-Tenant-Id`. Step and readiness writes
require `expected_version`.

## Persistence and rollback

Migration `20260824_onboarding_control_plane.sql` creates the additive
`onboarding_control_planes` table. Rollback consists of disabling the new routes
and dropping that table only after exporting active drafts; legacy application
onboarding remains unaffected.

## Remaining work

- The polished progressive frontend wizard is delivered with the later design
  system and onboarding UX milestone.
- Live connector validation and discovery depend on production connector
  profiles; readiness never fabricates success when these are absent.
- Project-scoped policy administration will be expanded during the role-model
  migration.
