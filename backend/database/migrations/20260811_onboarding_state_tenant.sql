-- Make onboarding state tenant-safe. Existing rows belong to the historical
-- default tenant; the composite primary key allows the same project/provider
-- names to be onboarded independently in other tenants.

SET @has_onboarding_tenant := (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'onboarding_state' AND column_name = 'tenant_id'
);
SET @sql := IF(@has_onboarding_tenant = 0,
    'ALTER TABLE onboarding_state ADD COLUMN tenant_id VARCHAR(128) NOT NULL DEFAULT ''default'' FIRST',
    'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @has_tenant_primary_key := (
    SELECT COUNT(*) FROM information_schema.statistics
    WHERE table_schema = DATABASE() AND table_name = 'onboarding_state'
      AND index_name = 'PRIMARY' AND column_name = 'tenant_id'
);
SET @sql := IF(@has_tenant_primary_key = 0,
    'ALTER TABLE onboarding_state DROP PRIMARY KEY, ADD PRIMARY KEY (tenant_id, project_name, provider_name)',
    'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @has_onboarding_tenant_idx := (
    SELECT COUNT(*) FROM information_schema.statistics
    WHERE table_schema = DATABASE() AND table_name = 'onboarding_state' AND index_name = 'idx_onboarding_state_tenant'
);
SET @sql := IF(@has_onboarding_tenant_idx = 0,
    'CREATE INDEX idx_onboarding_state_tenant ON onboarding_state (tenant_id)',
    'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
