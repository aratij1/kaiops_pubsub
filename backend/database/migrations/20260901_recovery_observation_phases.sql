-- Preserve immutable recovery observations as explicit pre/post-state samples.
-- Prepared statements keep this migration idempotent on MySQL versions that do
-- not implement ALTER TABLE ... ADD COLUMN IF NOT EXISTS.
SET @sql := IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'validation_observations' AND column_name = 'phase') = 0,
    'ALTER TABLE validation_observations ADD COLUMN phase VARCHAR(16) NOT NULL DEFAULT ''post_state'' AFTER target_resource_id', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'validation_observations' AND column_name = 'observation_window_start') = 0,
    'ALTER TABLE validation_observations ADD COLUMN observation_window_start DATETIME(6) NULL AFTER phase', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'validation_observations' AND column_name = 'observation_window_end') = 0,
    'ALTER TABLE validation_observations ADD COLUMN observation_window_end DATETIME(6) NULL AFTER observation_window_start', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
