-- Scope reviewer capacity and assignments by verified tenant identity.
-- Legacy `default` rows must be reassigned to a real tenant before production.

SET @sql := IF((SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema = DATABASE() AND table_name = 'approval_capacity' AND index_name = 'username') > 0,
    'ALTER TABLE approval_capacity DROP INDEX username', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := IF((SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema = DATABASE() AND table_name = 'approval_capacity' AND index_name = 'uq_approval_capacity_tenant_username') = 0,
    'ALTER TABLE approval_capacity ADD CONSTRAINT uq_approval_capacity_tenant_username UNIQUE (tenant_id, username)', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := IF((SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema = DATABASE() AND table_name = 'approval_assignments' AND index_name = 'incident_id') > 0,
    'ALTER TABLE approval_assignments DROP INDEX incident_id', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := IF((SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema = DATABASE() AND table_name = 'approval_assignments' AND index_name = 'uq_approval_assignment_tenant_incident') = 0,
    'ALTER TABLE approval_assignments ADD CONSTRAINT uq_approval_assignment_tenant_incident UNIQUE (tenant_id, incident_id)', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
