-- Bind every newly discovered topology row to its authoritative provider connection.
-- Guards keep this migration safe when ORM schema creation ran before migrations.

SET @sql := IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'discovered_resources' AND column_name = 'connection_id') = 0,
    'ALTER TABLE discovered_resources ADD COLUMN connection_id CHAR(32) NULL', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := IF((SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema = DATABASE() AND table_name = 'discovered_resources' AND index_name = 'idx_discovered_resources_connection') = 0,
    'CREATE INDEX idx_discovered_resources_connection ON discovered_resources (tenant_id, project_id, connection_id)', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'resource_relationships' AND column_name = 'connection_id') = 0,
    'ALTER TABLE resource_relationships ADD COLUMN connection_id CHAR(32) NULL', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := IF((SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema = DATABASE() AND table_name = 'resource_relationships' AND index_name = 'idx_resource_relationships_connection') = 0,
    'CREATE INDEX idx_resource_relationships_connection ON resource_relationships (tenant_id, project_id, connection_id)', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
