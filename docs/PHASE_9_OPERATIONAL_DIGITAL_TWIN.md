# KaiMS Phase 9 Operational Digital Twin

## Foundation

KaiMS reuses the existing `discovered_resources`, `resource_relationships`, `service_resource_mappings`, discovery-run, provider-connection, onboarding-profile, and readiness records. Phase 9 extends this working cloud-operations foundation rather than introducing a second topology database.

## Stable identity

Every newly upserted discovered resource receives a canonical ID:

`urn:kaims:<provider>:<provider-account>:<sha256(provider-resource-id)>`

The ID is independent of display name. The original provider resource ID remains available for deterministic connector calls. Existing rows are backfilled by migration using the same provider key already stored by KaiMS.

## Provenance and verification

Resources now retain:

- `canonical_resource_id`
- `provenance`
- `evidence`
- `discovered_at`
- `last_verified_at`

Relationships retain:

- typed source and target resource IDs
- relationship type
- `relationship_source`: discovered, declared, imported, or inferred
- confidence
- evidence
- last verification time
- owner confirmation

Inferred relationships without evidence are rejected by the domain contract. Inference is never silently promoted to discovered or verified topology.

## Traversal and blast-radius foundation

`CloudOperationsRepository.dependency_traversal` performs bounded inbound, outbound, or bidirectional traversal. Queries are restricted by verified tenant and project scope and capped at eight levels. The result contains the root, unique resource IDs, and full relationship projections suitable for dependency and blast-radius analysis.

This method is a repository foundation; a public API will be added with the Connector Hub/Digital Twin API increment after authorization and pagination conventions are finalized.

## Migration

Migration `20260902_operational_digital_twin.sql` adds nullable columns and indexes, then backfills existing resources and relationships. It does not delete or rename columns and does not change existing unique keys.

Before applying it to a shared environment:

1. Back up `discovered_resources` and `resource_relationships`.
2. Run `python scripts/apply-migrations.py --dry-run` with the target database configuration.
3. Apply during a controlled deployment.
4. Verify canonical IDs and traversal indexes.
5. Deploy services built from the matching source revision.

The local running database was not migrated automatically because it may contain user data and the repository migration runner can include other pending migrations.

## Rollback

Application rollback is safe while the added columns remain: older code ignores them. Database rollback is intentionally manual and should occur only after reverting the application and confirming no Phase 9 data is required. Drop the new indexes, then the added columns. No existing resource, relationship, or discovery data needs to be deleted.

## Known limitations

- The current stable ID uses provider identity; non-provider resources need a connector-specific deterministic identity strategy.
- Existing relationship names are not yet migrated to the complete Phase 9 relationship vocabulary.
- Traversal loads project relationships before applying a bounded graph walk; large estates require recursive SQL or a graph-optimized projection plus pagination.
- No public Digital Twin API or UI explorer is included in this increment.
- Existing simulated discovery remains labeled simulation and is not production evidence.

