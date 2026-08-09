SET @has_human_correction_version := (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'human_corrections'
      AND column_name = 'version'
);
SET @add_human_correction_version_sql := IF(
    @has_human_correction_version = 0,
    'ALTER TABLE human_corrections ADD COLUMN version INT NOT NULL DEFAULT 1 AFTER status',
    'SELECT 1'
);
PREPARE stmt_add_human_correction_version FROM @add_human_correction_version_sql;
EXECUTE stmt_add_human_correction_version;
DEALLOCATE PREPARE stmt_add_human_correction_version;
