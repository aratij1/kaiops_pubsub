-- Phase 9 additive Operational Digital Twin provenance and stable identity.
-- Every DDL operation is guarded because create_schema() may have created
-- model-backed columns before the forward migration runner reaches this file.

SET @sql := IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'discovered_resources' AND column_name = 'canonical_resource_id') = 0,
    'ALTER TABLE discovered_resources ADD COLUMN canonical_resource_id VARCHAR(768) NULL', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'discovered_resources' AND column_name = 'last_verified_at') = 0,
    'ALTER TABLE discovered_resources ADD COLUMN last_verified_at DATETIME(6) NULL', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'discovered_resources' AND column_name = 'provenance') = 0,
    'ALTER TABLE discovered_resources ADD COLUMN provenance JSON NULL', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'discovered_resources' AND column_name = 'evidence') = 0,
    'ALTER TABLE discovered_resources ADD COLUMN evidence JSON NULL', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := IF((SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema = DATABASE() AND table_name = 'discovered_resources' AND index_name = 'idx_discovered_resources_canonical_id') = 0,
    'CREATE INDEX idx_discovered_resources_canonical_id ON discovered_resources (canonical_resource_id(191))', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := IF((SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema = DATABASE() AND table_name = 'discovered_resources' AND index_name = 'idx_discovered_resources_last_verified') = 0,
    'CREATE INDEX idx_discovered_resources_last_verified ON discovered_resources (tenant_id, project_id, last_verified_at)', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'resource_relationships' AND column_name = 'relationship_source') = 0,
    'ALTER TABLE resource_relationships ADD COLUMN relationship_source VARCHAR(32) NOT NULL DEFAULT ''discovered''', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'resource_relationships' AND column_name = 'evidence') = 0,
    'ALTER TABLE resource_relationships ADD COLUMN evidence JSON NULL', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'resource_relationships' AND column_name = 'last_verified_at') = 0,
    'ALTER TABLE resource_relationships ADD COLUMN last_verified_at DATETIME(6) NULL', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := IF((SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema = DATABASE() AND table_name = 'resource_relationships' AND index_name = 'idx_resource_relationships_traversal_source') = 0,
    'CREATE INDEX idx_resource_relationships_traversal_source ON resource_relationships (tenant_id, project_id, source_resource_id)', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := IF((SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema = DATABASE() AND table_name = 'resource_relationships' AND index_name = 'idx_resource_relationships_traversal_target') = 0,
    'CREATE INDEX idx_resource_relationships_traversal_target ON resource_relationships (tenant_id, project_id, target_resource_id)', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := IF((SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema = DATABASE() AND table_name = 'resource_relationships' AND index_name = 'idx_resource_relationships_provenance') = 0,
    'CREATE INDEX idx_resource_relationships_provenance ON resource_relationships (tenant_id, project_id, relationship_source, last_verified_at)', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

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
