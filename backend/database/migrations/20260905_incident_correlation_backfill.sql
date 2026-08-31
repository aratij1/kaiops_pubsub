-- Restartable audit ledger for migration-safe canonical incident correlation.
CREATE TABLE IF NOT EXISTS incident_correlation_backfill (
    incident_id CHAR(32) NOT NULL,
    tenant_id VARCHAR(128) NOT NULL,
    backfill_version VARCHAR(64) NOT NULL,
    source VARCHAR(64) NOT NULL DEFAULT 'incidents',
    status VARCHAR(32) NOT NULL,
    reason VARCHAR(255) NOT NULL,
    project_id VARCHAR(128) NOT NULL,
    needs_scope_review BOOLEAN NOT NULL DEFAULT FALSE,
    correlation_family_id CHAR(32) NULL,
    correlation_generation INTEGER NULL,
    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    PRIMARY KEY (incident_id),
    KEY idx_incident_backfill_tenant (tenant_id),
    KEY idx_incident_backfill_version (backfill_version),
    KEY idx_incident_backfill_status (status),
    KEY idx_incident_backfill_project (project_id),
    KEY idx_incident_backfill_scope_review (needs_scope_review),
    KEY idx_incident_backfill_family (correlation_family_id)
);
