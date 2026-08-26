-- Support bounded execution/audit-history reads ordered newest first.
SET @has_audit_created_index := (
    SELECT COUNT(*)
    FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'audit_logs'
      AND index_name = 'idx_audit_logs_created_at'
);

SET @create_audit_created_index_sql := IF(
    @has_audit_created_index = 0,
    'CREATE INDEX idx_audit_logs_created_at ON audit_logs (created_at)',
    'SELECT 1'
);
PREPARE stmt_audit_created_index FROM @create_audit_created_index_sql;
EXECUTE stmt_audit_created_index;
DEALLOCATE PREPARE stmt_audit_created_index;
