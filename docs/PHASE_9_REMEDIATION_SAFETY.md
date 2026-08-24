# KaiMS Phase 9 Remediation Safety

## Capability-first control

Infrastructure execution is authorized by `CapabilityRegistry`, never by free-form model output. A capability definition contains its risk, supported connectors, required permissions, typed input schema, preconditions, dry-run support, validation requirements, rollback capability, allowed environments, maximum blast radius, approval level, trust level, and mutation flag.

Unknown capability IDs fail closed. Connector, environment, blast-radius, and required-parameter checks occur before a definition can be bound to the existing `SafeRemediationBinding` contract.

## Initial registry

The registry covers Kubernetes restart/rollback/scale, Linux and Windows service restart, database diagnostics/session termination/failover, Kafka recovery, cache clearing, cloud restart/scale, pipeline and Airflow recovery, Jenkins and Terraform rollback, and application recovery endpoints.

Catalog presence is authorization metadata, not proof that an executor exists. Execution additionally requires a certified Connector Hub plugin.

## Existing safety layers retained

The registry binds into the established controls:

1. Registered `CapabilitySpec`
2. Opaque, tenant- and resource-scoped credential reference
3. Verified target and blast radius
4. Known dependencies
5. Durable preflight evidence
6. Dry-run evidence when required
7. Approval bound to the immutable plan
8. Idempotent deterministic execution
9. Closed-loop validation
10. Rollback or escalation on validation failure

The registry cannot itself execute anything.

## Trust and approval

Trust levels are `EXPERIMENTAL`, `HITL_ONLY`, `TRUSTED`, and `AUTONOMOUS`. Initial mutating capabilities are `HITL_ONLY`. Critical database failover and Terraform rollback require Admin approval. Read-only database diagnostics are trusted and require no approval, but still require a registered connector and scoped credential.

No capability is initially autonomous. Promotion remains controlled by the existing evidence-threshold learning contracts.

## API

The Connector Hub exposes read-only registry metadata:

- `GET /capabilities`
- `GET /capabilities/{capability_id}`

There is no registry execution endpoint in this milestone.

## Known limitations and next step

The registry is currently code-defined and versioned with the application; tenant-specific policy overlays and durable registry revisions are not yet persisted. Several definitions have no certified Connector Hub executor and therefore remain non-executable. The next milestone migrates Resolution Agent output to a typed `RemediationPlan` that references these IDs and Digital Twin targets, while quarantining command-shaped compatibility fields from autonomous paths.

