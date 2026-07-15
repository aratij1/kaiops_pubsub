-- Add document-availability flag to incident_projections.
-- Idempotent migration for existing environments.

SET @has_projection_table := (
    SELECT COUNT(*)
    FROM information_schema.tables
    WHERE table_schema = DATABASE()
      AND table_name = 'incident_projections'
);

SET @has_document_available_column := (
    SELECT COUNT(*)
    FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'incident_projections'
      AND column_name = 'document_available'
);

SET @add_document_available_sql := IF(
    @has_projection_table = 1 AND @has_document_available_column = 0,
    'ALTER TABLE incident_projections ADD COLUMN document_available BOOLEAN NULL',
    'SELECT 1'
);
PREPARE stmt_add_document_available FROM @add_document_available_sql;
EXECUTE stmt_add_document_available;
DEALLOCATE PREPARE stmt_add_document_available;
