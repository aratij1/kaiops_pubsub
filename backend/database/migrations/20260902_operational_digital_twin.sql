-- Phase 9 additive Operational Digital Twin provenance and stable identity.

ALTER TABLE discovered_resources
    ADD COLUMN canonical_resource_id VARCHAR(768) NULL,
    ADD COLUMN last_verified_at DATETIME(6) NULL,
    ADD COLUMN provenance JSON NULL,
    ADD COLUMN evidence JSON NULL;

CREATE INDEX idx_discovered_resources_canonical_id
    ON discovered_resources (canonical_resource_id(191));
CREATE INDEX idx_discovered_resources_last_verified
    ON discovered_resources (tenant_id, project_id, last_verified_at);

ALTER TABLE resource_relationships
    ADD COLUMN relationship_source VARCHAR(32) NOT NULL DEFAULT 'discovered',
    ADD COLUMN evidence JSON NULL,
    ADD COLUMN last_verified_at DATETIME(6) NULL;

CREATE INDEX idx_resource_relationships_traversal_source
    ON resource_relationships (tenant_id, project_id, source_resource_id);
CREATE INDEX idx_resource_relationships_traversal_target
    ON resource_relationships (tenant_id, project_id, target_resource_id);
CREATE INDEX idx_resource_relationships_provenance
    ON resource_relationships (tenant_id, project_id, relationship_source, last_verified_at);

UPDATE discovered_resources
SET canonical_resource_id = CONCAT(
        'urn:kaims:', provider, ':', provider_account_id, ':', provider_resource_key
    ),
    last_verified_at = COALESCE(last_verified_at, discovered_at),
    provenance = COALESCE(provenance, JSON_OBJECT('source', 'legacy-discovery-migration')),
    evidence = COALESCE(evidence, JSON_ARRAY())
WHERE canonical_resource_id IS NULL;

UPDATE resource_relationships
SET last_verified_at = COALESCE(last_verified_at, discovered_at),
    evidence = COALESCE(evidence, JSON_ARRAY())
WHERE last_verified_at IS NULL OR evidence IS NULL;

