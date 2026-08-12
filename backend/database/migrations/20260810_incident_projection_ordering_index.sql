-- Keep the incident metadata feed on an indexed newest-first scan.
--
-- Some long-lived environments created incident_projections before the
-- updated_at index was included in the base migration. Sorting rows that
-- contain projection_payload JSON can exhaust MySQL's per-query sort buffer
-- and surface as an intermittent HTTP 503 from /incidents/metadata.

SET @has_projection_updated_index := (
    SELECT COUNT(*)
    FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'incident_projections'
      AND index_name = 'idx_incident_projections_updated'
);

SET @projection_updated_index_sql := IF(
    @has_projection_updated_index = 0,
    'CREATE INDEX idx_incident_projections_updated ON incident_projections (updated_at DESC)',
    'SELECT 1'
);

PREPARE projection_updated_index_stmt FROM @projection_updated_index_sql;
EXECUTE projection_updated_index_stmt;
DEALLOCATE PREPARE projection_updated_index_stmt;
