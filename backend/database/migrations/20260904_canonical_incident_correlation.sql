-- Durable, bounded incident-correlation ownership and immutable occurrences.

CREATE TABLE IF NOT EXISTS incident_correlation_ownership (
    id CHAR(32) NOT NULL PRIMARY KEY,
    tenant_id VARCHAR(128) NOT NULL,
    project_id VARCHAR(128) NOT NULL,
    environment VARCHAR(64) NOT NULL,
    service VARCHAR(128) NOT NULL,
    correlation_key VARCHAR(255) NOT NULL,
    correlation_family_id CHAR(32) NOT NULL,
    correlation_generation INT NOT NULL,
    canonical_incident_id CHAR(32) NOT NULL,
    first_seen_at DATETIME(6) NOT NULL,
    last_seen_at DATETIME(6) NOT NULL,
    correlation_window_expires_at DATETIME(6) NOT NULL,
    lifecycle_state VARCHAR(64) NOT NULL,
    version INT NOT NULL DEFAULT 1,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    UNIQUE KEY uq_incident_correlation_generation (
        tenant_id, project_id, environment, service, correlation_key, correlation_generation
    ),
    KEY idx_incident_correlation_lookup (
        tenant_id, project_id, environment, service, correlation_key
    ),
    KEY idx_incident_correlation_canonical (canonical_incident_id),
    KEY idx_incident_correlation_family (correlation_family_id),
    KEY idx_incident_correlation_page (tenant_id, first_seen_at, id),
    KEY idx_incident_correlation_family_generation (tenant_id, correlation_family_id, correlation_generation),
    KEY idx_incident_correlation_lifecycle (lifecycle_state, last_seen_at)
);

CREATE TABLE IF NOT EXISTS incident_occurrences (
    id CHAR(32) NOT NULL PRIMARY KEY,
    tenant_id VARCHAR(128) NOT NULL,
    project_id VARCHAR(128) NOT NULL,
    environment VARCHAR(64) NOT NULL,
    service VARCHAR(128) NOT NULL,
    correlation_family_id CHAR(32) NOT NULL,
    correlation_generation INT NOT NULL,
    canonical_incident_id CHAR(32) NOT NULL,
    occurrence_id CHAR(32) NOT NULL,
    idempotency_key VARCHAR(255) NOT NULL,
    causation_id VARCHAR(255) NULL,
    payload JSON NOT NULL,
    observed_at DATETIME(6) NOT NULL,
    UNIQUE KEY uq_incident_occurrence_idempotency (tenant_id, idempotency_key),
    KEY idx_incident_occurrence_canonical_seen (canonical_incident_id, observed_at),
    KEY idx_incident_occurrence_family (correlation_family_id, correlation_generation),
    KEY idx_incident_occurrence_scope (tenant_id, project_id, environment, service),
    KEY idx_incident_occurrence_id (occurrence_id),
    KEY idx_incident_occurrence_causation (causation_id)
);

SET @sql := IF((SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema = DATABASE() AND table_name = 'incident_correlation_ownership' AND index_name = 'idx_incident_correlation_page') = 0,
    'CREATE INDEX idx_incident_correlation_page ON incident_correlation_ownership (tenant_id, first_seen_at, id)', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := IF((SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema = DATABASE() AND table_name = 'incident_correlation_ownership' AND index_name = 'idx_incident_correlation_family_generation') = 0,
    'CREATE INDEX idx_incident_correlation_family_generation ON incident_correlation_ownership (tenant_id, correlation_family_id, correlation_generation)', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
