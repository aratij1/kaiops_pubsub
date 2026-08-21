ALTER TABLE evaluation_records
    ADD COLUMN tenant_id VARCHAR(128) NOT NULL DEFAULT 'default',
    ADD COLUMN expires_at DATETIME(6) NULL,
    ADD COLUMN artifact_signature VARCHAR(255) NULL;

CREATE INDEX idx_evaluation_records_tenant_created
    ON evaluation_records (tenant_id, created_at);

CREATE INDEX idx_evaluation_records_tenant_expiry
    ON evaluation_records (tenant_id, expires_at);
