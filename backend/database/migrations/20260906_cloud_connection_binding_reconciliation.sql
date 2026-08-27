-- Reconcile legacy cloud topology only when one authoritative connection is provable.
-- Ambiguous and unmatched rows remain visible and explicitly require review.

SET @sql := IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'discovered_resources' AND column_name = 'connection_id') = 0,
    'ALTER TABLE discovered_resources ADD COLUMN connection_id CHAR(32) NULL', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'resource_relationships' AND column_name = 'connection_id') = 0,
    'ALTER TABLE resource_relationships ADD COLUMN connection_id CHAR(32) NULL', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'discovered_resources' AND column_name = 'connection_binding_status') = 0,
    'ALTER TABLE discovered_resources ADD COLUMN connection_binding_status VARCHAR(32) NOT NULL DEFAULT ''needs_review''', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'resource_relationships' AND column_name = 'connection_binding_status') = 0,
    'ALTER TABLE resource_relationships ADD COLUMN connection_binding_status VARCHAR(32) NOT NULL DEFAULT ''needs_review''', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

UPDATE discovered_resources r
JOIN (
    SELECT tenant_id, project_id, provider_type AS provider, MIN(id) AS connection_id
    FROM provider_connections
    WHERE status = 'validated' AND read_capability = TRUE
    GROUP BY tenant_id, project_id, provider_type
    HAVING COUNT(*) = 1
) c ON c.tenant_id = r.tenant_id AND c.project_id = r.project_id AND c.provider = r.provider
SET r.connection_id = c.connection_id, r.connection_binding_status = 'bound'
WHERE r.connection_id IS NULL;

UPDATE discovered_resources
SET connection_binding_status = CASE WHEN connection_id IS NULL THEN 'needs_review' ELSE 'bound' END;

UPDATE resource_relationships edge
JOIN discovered_resources source_resource ON source_resource.id = edge.source_resource_id
JOIN discovered_resources target_resource ON target_resource.id = edge.target_resource_id
SET edge.connection_id = source_resource.connection_id, edge.connection_binding_status = 'bound'
WHERE edge.connection_id IS NULL
  AND source_resource.connection_id IS NOT NULL
  AND source_resource.connection_id = target_resource.connection_id
  AND source_resource.tenant_id = edge.tenant_id
  AND source_resource.project_id = edge.project_id
  AND target_resource.tenant_id = edge.tenant_id
  AND target_resource.project_id = edge.project_id;

UPDATE resource_relationships
SET connection_binding_status = CASE WHEN connection_id IS NULL THEN 'needs_review' ELSE 'bound' END;

SET @sql := IF((SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema = DATABASE() AND table_name = 'discovered_resources' AND index_name = 'idx_discovered_resources_binding_status') = 0,
    'CREATE INDEX idx_discovered_resources_binding_status ON discovered_resources (tenant_id, project_id, connection_binding_status)', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := IF((SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema = DATABASE() AND table_name = 'resource_relationships' AND index_name = 'idx_resource_relationships_binding_status') = 0,
    'CREATE INDEX idx_resource_relationships_binding_status ON resource_relationships (tenant_id, project_id, connection_binding_status)', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
