-- Add recommendation and flow context columns to incident_projections.
-- Idempotent migration for existing environments.

SET @has_projection_table := (
    SELECT COUNT(*)
    FROM information_schema.tables
    WHERE table_schema = DATABASE()
      AND table_name = 'incident_projections'
);

SET @has_recommendation_column := (
    SELECT COUNT(*)
    FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'incident_projections'
      AND column_name = 'recommendation_id'
);

SET @add_recommendation_sql := IF(
    @has_projection_table = 1 AND @has_recommendation_column = 0,
    'ALTER TABLE incident_projections ADD COLUMN recommendation_id CHAR(32) NULL',
    'SELECT 1'
);
PREPARE stmt_add_recommendation FROM @add_recommendation_sql;
EXECUTE stmt_add_recommendation;
DEALLOCATE PREPARE stmt_add_recommendation;

SET @has_flow_column := (
    SELECT COUNT(*)
    FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'incident_projections'
      AND column_name = 'flow_id'
);

SET @add_flow_sql := IF(
    @has_projection_table = 1 AND @has_flow_column = 0,
    'ALTER TABLE incident_projections ADD COLUMN flow_id VARCHAR(128) NULL',
    'SELECT 1'
);
PREPARE stmt_add_flow FROM @add_flow_sql;
EXECUTE stmt_add_flow;
DEALLOCATE PREPARE stmt_add_flow;

SET @idx_recommendation_exists := (
    SELECT COUNT(*)
    FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'incident_projections'
      AND index_name = 'idx_incident_projections_recommendation'
);

SET @create_idx_recommendation_sql := IF(
    @has_projection_table = 1 AND @idx_recommendation_exists = 0,
    'CREATE INDEX idx_incident_projections_recommendation ON incident_projections (recommendation_id)',
    'SELECT 1'
);
PREPARE stmt_idx_recommendation FROM @create_idx_recommendation_sql;
EXECUTE stmt_idx_recommendation;
DEALLOCATE PREPARE stmt_idx_recommendation;

SET @idx_flow_exists := (
    SELECT COUNT(*)
    FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'incident_projections'
      AND index_name = 'idx_incident_projections_flow'
);

SET @create_idx_flow_sql := IF(
    @has_projection_table = 1 AND @idx_flow_exists = 0,
    'CREATE INDEX idx_incident_projections_flow ON incident_projections (flow_id)',
    'SELECT 1'
);
PREPARE stmt_idx_flow FROM @create_idx_flow_sql;
EXECUTE stmt_idx_flow;
DEALLOCATE PREPARE stmt_idx_flow;
