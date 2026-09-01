-- Bind every accepted HITL decision to an immutable tenant-scoped plan.
-- Nullable columns preserve read compatibility for historical decisions;
-- remediation rejects historical rows without a complete binding.
SET @sql := IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'approvals' AND column_name = 'plan_id') = 0,
    'ALTER TABLE approvals ADD COLUMN plan_id CHAR(36) NULL AFTER recommendation_id', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'approvals' AND column_name = 'plan_fingerprint') = 0,
    'ALTER TABLE approvals ADD COLUMN plan_fingerprint VARCHAR(71) NULL AFTER plan_id', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'approvals' AND column_name = 'approval_expires_at') = 0,
    'ALTER TABLE approvals ADD COLUMN approval_expires_at DATETIME(6) NULL AFTER plan_fingerprint', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'approvals' AND column_name = 'approver_role') = 0,
    'ALTER TABLE approvals ADD COLUMN approver_role VARCHAR(64) NULL AFTER approver', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := IF((SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema = DATABASE() AND table_name = 'approvals' AND index_name = 'idx_approvals_plan_binding') = 0,
    'CREATE INDEX idx_approvals_plan_binding ON approvals (tenant_id, plan_id, plan_fingerprint, decision, approval_expires_at)', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
