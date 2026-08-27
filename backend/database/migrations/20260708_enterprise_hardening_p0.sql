-- Enterprise hardening P0 migration.
-- 1) Durable pending workflow storage.
-- 2) Append-only agent work items model.

CREATE TABLE IF NOT EXISTS pending_workflows (
    incident_id CHAR(32) PRIMARY KEY,
    recommendation_id CHAR(32) NOT NULL,
    flow_id VARCHAR(128) NOT NULL,
    trace_id VARCHAR(128),
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    payload JSON NOT NULL,
    completed_payload JSON,
    completed_at DATETIME(6),
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    KEY idx_pending_workflows_status (status),
    KEY idx_pending_workflows_recommendation (recommendation_id),
    KEY idx_pending_workflows_trace (trace_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

SET @has_agent_work_items := (
    SELECT COUNT(*)
    FROM information_schema.tables
    WHERE table_schema = DATABASE()
      AND table_name = 'agent_work_items'
);

SET @has_agent_work_item_id := (
    SELECT COUNT(*)
    FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'agent_work_items'
      AND column_name = 'id'
);

SET @add_id_sql := IF(
    @has_agent_work_items = 1 AND @has_agent_work_item_id = 0,
    'ALTER TABLE agent_work_items ADD COLUMN id CHAR(32) NULL FIRST',
    'SELECT 1'
);
PREPARE stmt_add_id FROM @add_id_sql;
EXECUTE stmt_add_id;
DEALLOCATE PREPARE stmt_add_id;

SET @fill_id_sql := IF(
    @has_agent_work_items = 1,
    'UPDATE agent_work_items SET id = REPLACE(UUID(), ''-'', '''') WHERE id IS NULL OR id = ''''',
    'SELECT 1'
);
PREPARE stmt_fill_id FROM @fill_id_sql;
EXECUTE stmt_fill_id;
DEALLOCATE PREPARE stmt_fill_id;

SET @current_pk_col := (
    SELECT COLUMN_NAME
    FROM information_schema.key_column_usage
    WHERE table_schema = DATABASE()
      AND table_name = 'agent_work_items'
      AND constraint_name = 'PRIMARY'
    ORDER BY ORDINAL_POSITION
    LIMIT 1
);

SET @switch_pk_sql := IF(
    @has_agent_work_items = 1 AND @current_pk_col <> 'id',
    'ALTER TABLE agent_work_items DROP PRIMARY KEY, ADD PRIMARY KEY (id)',
    'SELECT 1'
);
PREPARE stmt_switch_pk FROM @switch_pk_sql;
EXECUTE stmt_switch_pk;
DEALLOCATE PREPARE stmt_switch_pk;

SET @id_nullable := (
    SELECT IS_NULLABLE
    FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'agent_work_items'
      AND column_name = 'id'
    LIMIT 1
);

SET @set_not_null_sql := IF(
    @has_agent_work_items = 1 AND @id_nullable = 'YES',
    'ALTER TABLE agent_work_items MODIFY COLUMN id CHAR(32) NOT NULL',
    'SELECT 1'
);
PREPARE stmt_set_not_null FROM @set_not_null_sql;
EXECUTE stmt_set_not_null;
DEALLOCATE PREPARE stmt_set_not_null;

SET @idx_incident_exists := (
    SELECT COUNT(*)
    FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'agent_work_items'
      AND index_name = 'idx_agent_work_items_incident'
);
SET @create_idx_incident_sql := IF(
    @has_agent_work_items = 1 AND @idx_incident_exists = 0,
    'CREATE INDEX idx_agent_work_items_incident ON agent_work_items (incident_id)',
    'SELECT 1'
);
PREPARE stmt_create_idx_incident FROM @create_idx_incident_sql;
EXECUTE stmt_create_idx_incident;
DEALLOCATE PREPARE stmt_create_idx_incident;

SET @idx_agent_seq_exists := (
    SELECT COUNT(*)
    FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'agent_work_items'
      AND index_name = 'idx_agent_work_items_agent_seq'
);
SET @create_idx_agent_seq_sql := IF(
    @has_agent_work_items = 1 AND @idx_agent_seq_exists = 0,
    'CREATE INDEX idx_agent_work_items_agent_seq ON agent_work_items (agent_name, sequence)',
    'SELECT 1'
);
PREPARE stmt_create_idx_agent_seq FROM @create_idx_agent_seq_sql;
EXECUTE stmt_create_idx_agent_seq;
DEALLOCATE PREPARE stmt_create_idx_agent_seq;
