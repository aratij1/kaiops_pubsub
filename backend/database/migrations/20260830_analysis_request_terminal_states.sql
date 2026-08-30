SET @has_expires_at = (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'analysis_requests' AND column_name = 'expires_at'
);
SET @add_expires_at = IF(
    @has_expires_at = 0,
    'ALTER TABLE analysis_requests ADD COLUMN expires_at DATETIME NULL AFTER completed_at',
    'SELECT 1'
);
PREPARE analysis_request_stmt FROM @add_expires_at;
EXECUTE analysis_request_stmt;
DEALLOCATE PREPARE analysis_request_stmt;

UPDATE analysis_requests
SET expires_at = DATE_ADD(created_at, INTERVAL 15 MINUTE)
WHERE expires_at IS NULL;

ALTER TABLE analysis_requests MODIFY COLUMN expires_at DATETIME NOT NULL;

SET @has_expires_index = (
    SELECT COUNT(*) FROM information_schema.statistics
    WHERE table_schema = DATABASE() AND table_name = 'analysis_requests'
      AND index_name = 'idx_analysis_requests_expires_at'
);
SET @add_expires_index = IF(
    @has_expires_index = 0,
    'CREATE INDEX idx_analysis_requests_expires_at ON analysis_requests (expires_at)',
    'SELECT 1'
);
PREPARE analysis_request_index_stmt FROM @add_expires_index;
EXECUTE analysis_request_index_stmt;
DEALLOCATE PREPARE analysis_request_index_stmt;
