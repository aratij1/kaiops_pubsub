-- Keep this migration compatible with databases that were first upgraded by
-- common.database.create_schema(), which historically added these columns.

SET @sql := IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'evaluation_records' AND column_name = 'tenant_id') = 0,
    'ALTER TABLE evaluation_records ADD COLUMN tenant_id VARCHAR(128) NOT NULL DEFAULT ''default''', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'evaluation_records' AND column_name = 'expires_at') = 0,
    'ALTER TABLE evaluation_records ADD COLUMN expires_at DATETIME(6) NULL', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'evaluation_records' AND column_name = 'artifact_signature') = 0,
    'ALTER TABLE evaluation_records ADD COLUMN artifact_signature VARCHAR(255) NULL', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := IF((SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema = DATABASE() AND table_name = 'evaluation_records' AND index_name = 'idx_evaluation_records_tenant_created') = 0,
    'CREATE INDEX idx_evaluation_records_tenant_created ON evaluation_records (tenant_id, created_at)', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := IF((SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema = DATABASE() AND table_name = 'evaluation_records' AND index_name = 'idx_evaluation_records_tenant_expiry') = 0,
    'CREATE INDEX idx_evaluation_records_tenant_expiry ON evaluation_records (tenant_id, expires_at)', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
