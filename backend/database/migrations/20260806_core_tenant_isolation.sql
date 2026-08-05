-- Adds tenant_id to the core alert/incident/remediation pipeline tables and
-- to users, matching the `tenant_id VARCHAR(128) NOT NULL DEFAULT 'default'`
-- + index convention already established by incident_events,
-- incident_projections, monitoring_* and context_knowledge. Additive and
-- default-backfilling: every existing row becomes tenant 'default', which is
-- the only tenant that has ever existed in this deployment, so this changes
-- no observable behavior until a second tenant is introduced.
--
-- Written with information_schema-guarded conditional DDL (matching
-- 20260708_enterprise_hardening_p0.sql) so it is safe to re-run.

-- Reusable pattern: for each (table, index_name) pair below, add
-- `tenant_id VARCHAR(128) NOT NULL DEFAULT 'default'` and a supporting index
-- if not already present.

SET @has_alerts_tenant := (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'alerts' AND column_name = 'tenant_id'
);
SET @sql := IF(@has_alerts_tenant = 0,
    'ALTER TABLE alerts ADD COLUMN tenant_id VARCHAR(128) NOT NULL DEFAULT ''default'' AFTER id',
    'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @has_alerts_tenant_idx := (
    SELECT COUNT(*) FROM information_schema.statistics
    WHERE table_schema = DATABASE() AND table_name = 'alerts' AND index_name = 'idx_alerts_tenant'
);
SET @sql := IF(@has_alerts_tenant_idx = 0,
    'CREATE INDEX idx_alerts_tenant ON alerts (tenant_id)',
    'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;


SET @has_incidents_tenant := (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'incidents' AND column_name = 'tenant_id'
);
SET @sql := IF(@has_incidents_tenant = 0,
    'ALTER TABLE incidents ADD COLUMN tenant_id VARCHAR(128) NOT NULL DEFAULT ''default'' AFTER id',
    'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @has_incidents_tenant_idx := (
    SELECT COUNT(*) FROM information_schema.statistics
    WHERE table_schema = DATABASE() AND table_name = 'incidents' AND index_name = 'idx_incidents_tenant'
);
SET @sql := IF(@has_incidents_tenant_idx = 0,
    'CREATE INDEX idx_incidents_tenant ON incidents (tenant_id)',
    'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;


SET @has_approvals_tenant := (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'approvals' AND column_name = 'tenant_id'
);
SET @sql := IF(@has_approvals_tenant = 0,
    'ALTER TABLE approvals ADD COLUMN tenant_id VARCHAR(128) NOT NULL DEFAULT ''default'' AFTER id',
    'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @has_approvals_tenant_idx := (
    SELECT COUNT(*) FROM information_schema.statistics
    WHERE table_schema = DATABASE() AND table_name = 'approvals' AND index_name = 'idx_approvals_tenant'
);
SET @sql := IF(@has_approvals_tenant_idx = 0,
    'CREATE INDEX idx_approvals_tenant ON approvals (tenant_id)',
    'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;


SET @has_actions_tenant := (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'actions' AND column_name = 'tenant_id'
);
SET @sql := IF(@has_actions_tenant = 0,
    'ALTER TABLE actions ADD COLUMN tenant_id VARCHAR(128) NOT NULL DEFAULT ''default'' AFTER id',
    'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @has_actions_tenant_idx := (
    SELECT COUNT(*) FROM information_schema.statistics
    WHERE table_schema = DATABASE() AND table_name = 'actions' AND index_name = 'idx_actions_tenant'
);
SET @sql := IF(@has_actions_tenant_idx = 0,
    'CREATE INDEX idx_actions_tenant ON actions (tenant_id)',
    'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;


SET @has_rca_reports_tenant := (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'rca_reports' AND column_name = 'tenant_id'
);
SET @sql := IF(@has_rca_reports_tenant = 0,
    'ALTER TABLE rca_reports ADD COLUMN tenant_id VARCHAR(128) NOT NULL DEFAULT ''default'' AFTER id',
    'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @has_rca_reports_tenant_idx := (
    SELECT COUNT(*) FROM information_schema.statistics
    WHERE table_schema = DATABASE() AND table_name = 'rca_reports' AND index_name = 'idx_rca_reports_tenant'
);
SET @sql := IF(@has_rca_reports_tenant_idx = 0,
    'CREATE INDEX idx_rca_reports_tenant ON rca_reports (tenant_id)',
    'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;


SET @has_knowledge_base_tenant := (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'knowledge_base' AND column_name = 'tenant_id'
);
SET @sql := IF(@has_knowledge_base_tenant = 0,
    'ALTER TABLE knowledge_base ADD COLUMN tenant_id VARCHAR(128) NOT NULL DEFAULT ''default'' AFTER id',
    'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @has_knowledge_base_tenant_idx := (
    SELECT COUNT(*) FROM information_schema.statistics
    WHERE table_schema = DATABASE() AND table_name = 'knowledge_base' AND index_name = 'idx_knowledge_base_tenant'
);
SET @sql := IF(@has_knowledge_base_tenant_idx = 0,
    'CREATE INDEX idx_knowledge_base_tenant ON knowledge_base (tenant_id)',
    'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;


SET @has_audit_logs_tenant := (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'audit_logs' AND column_name = 'tenant_id'
);
SET @sql := IF(@has_audit_logs_tenant = 0,
    'ALTER TABLE audit_logs ADD COLUMN tenant_id VARCHAR(128) NOT NULL DEFAULT ''default'' AFTER id',
    'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @has_audit_logs_tenant_idx := (
    SELECT COUNT(*) FROM information_schema.statistics
    WHERE table_schema = DATABASE() AND table_name = 'audit_logs' AND index_name = 'idx_audit_logs_tenant'
);
SET @sql := IF(@has_audit_logs_tenant_idx = 0,
    'CREATE INDEX idx_audit_logs_tenant ON audit_logs (tenant_id)',
    'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;


-- users: needed so a JWT can carry a tenant_id claim derived from the
-- authenticated account, letting read endpoints scope by the caller's own
-- tenant instead of trusting a client-supplied value.
SET @has_users_tenant := (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'users' AND column_name = 'tenant_id'
);
SET @sql := IF(@has_users_tenant = 0,
    'ALTER TABLE users ADD COLUMN tenant_id VARCHAR(128) NOT NULL DEFAULT ''default'' AFTER id',
    'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @has_users_tenant_idx := (
    SELECT COUNT(*) FROM information_schema.statistics
    WHERE table_schema = DATABASE() AND table_name = 'users' AND index_name = 'idx_users_tenant'
);
SET @sql := IF(@has_users_tenant_idx = 0,
    'CREATE INDEX idx_users_tenant ON users (tenant_id)',
    'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
