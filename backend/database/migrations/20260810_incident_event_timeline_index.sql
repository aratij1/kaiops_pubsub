-- Prevent incident timeline reads from sorting JSON-bearing event rows in memory.
-- Long-lived databases may predate the composite index in the base schema.

SET @has_incident_event_timeline_index := (
    SELECT COUNT(*)
    FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'incident_events'
      AND column_name = 'incident_id'
      AND seq_in_index = 1
      AND index_name IN ('idx_incident_events_incident_time', 'idx_incident_events_incident_created')
);

SET @incident_event_timeline_index_sql := IF(
    @has_incident_event_timeline_index = 0,
    'CREATE INDEX idx_incident_events_incident_created ON incident_events (incident_id, created_at)',
    'SELECT 1'
);

PREPARE incident_event_timeline_index_stmt FROM @incident_event_timeline_index_sql;
EXECUTE incident_event_timeline_index_stmt;
DEALLOCATE PREPARE incident_event_timeline_index_stmt;
