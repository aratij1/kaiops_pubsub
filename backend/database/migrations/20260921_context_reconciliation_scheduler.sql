-- Forward-only durable reconciliation leases and run history.
CREATE TABLE IF NOT EXISTS context_reconciliation_leases (
    lease_key VARCHAR(128) NOT NULL,
    lease_owner VARCHAR(255) NULL,
    lease_expires_at DATETIME(6) NULL,
    version INT NOT NULL DEFAULT 1,
    updated_at DATETIME(6) NOT NULL,
    PRIMARY KEY (lease_key),
    KEY ix_context_reconciliation_lease_expiry (lease_expires_at),
    KEY ix_context_reconciliation_lease_owner (lease_owner)
);

CREATE TABLE IF NOT EXISTS context_reconciliation_runs (
    run_id CHAR(32) NOT NULL,
    lease_owner VARCHAR(255) NOT NULL,
    tenant_id VARCHAR(128) NULL,
    status VARCHAR(32) NOT NULL,
    incidents_scanned INT NOT NULL DEFAULT 0,
    gaps_found INT NOT NULL DEFAULT 0,
    requirements_created INT NOT NULL DEFAULT 0,
    jobs_scheduled INT NOT NULL DEFAULT 0,
    human_requests_created INT NOT NULL DEFAULT 0,
    skipped_incidents INT NOT NULL DEFAULT 0,
    errors JSON NOT NULL,
    started_at DATETIME(6) NOT NULL,
    completed_at DATETIME(6) NULL,
    duration_ms INT NULL,
    PRIMARY KEY (run_id),
    KEY ix_context_reconciliation_runs_started (status, started_at),
    KEY ix_context_reconciliation_runs_tenant (tenant_id, started_at)
);
