-- Phase A hardening migration for 10k-alerts/day readiness.
-- 1) Idempotency key on `actions` so a redelivered approval/resolution message
--    cannot re-execute a real remediation action twice.
-- 2) Service/environment-scoped index on `alerts` so alert-intelligence
--    correlation/dedup no longer has to score every recent alert cluster-wide.
-- Written with information_schema-guarded conditional DDL (matching
-- 20260708_enterprise_hardening_p0.sql) so it is safe to re-run against a
-- database that already has either change applied.

SET @has_actions_idempotency_key := (
    SELECT COUNT(*)
    FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'actions'
      AND column_name = 'idempotency_key'
);
SET @add_idempotency_key_sql := IF(
    @has_actions_idempotency_key = 0,
    'ALTER TABLE actions ADD COLUMN idempotency_key VARCHAR(64) NULL AFTER target',
    'SELECT 1'
);
PREPARE stmt_add_idempotency_key FROM @add_idempotency_key_sql;
EXECUTE stmt_add_idempotency_key;
DEALLOCATE PREPARE stmt_add_idempotency_key;

SET @has_actions_idempotency_index := (
    SELECT COUNT(*)
    FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'actions'
      AND index_name = 'uq_actions_idempotency'
);
SET @add_actions_idempotency_index_sql := IF(
    @has_actions_idempotency_index = 0,
    'ALTER TABLE actions ADD UNIQUE KEY uq_actions_idempotency (idempotency_key)',
    'SELECT 1'
);
PREPARE stmt_add_actions_idempotency_index FROM @add_actions_idempotency_index_sql;
EXECUTE stmt_add_actions_idempotency_index;
DEALLOCATE PREPARE stmt_add_actions_idempotency_index;

SET @has_alerts_service_env_index := (
    SELECT COUNT(*)
    FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'alerts'
      AND index_name = 'idx_alerts_service_env_created'
);
SET @add_alerts_service_env_index_sql := IF(
    @has_alerts_service_env_index = 0,
    'CREATE INDEX idx_alerts_service_env_created ON alerts (service, environment, created_at DESC)',
    'SELECT 1'
);
PREPARE stmt_add_alerts_service_env_index FROM @add_alerts_service_env_index_sql;
EXECUTE stmt_add_alerts_service_env_index;
DEALLOCATE PREPARE stmt_add_alerts_service_env_index;
