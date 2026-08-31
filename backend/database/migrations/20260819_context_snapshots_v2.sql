-- Immutable, quality-scored context packages. context_knowledge remains the
-- cache-aside family index; this table records exactly what each incident and
-- downstream RCA consumed.

CREATE TABLE IF NOT EXISTS context_snapshots (
    snapshot_id CHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(128) NOT NULL DEFAULT 'default',
    incident_id VARCHAR(128) NOT NULL,
    source_incident_id VARCHAR(128),
    alert_signature CHAR(64) NOT NULL,
    subject_fingerprint CHAR(64) NOT NULL,
    context_fingerprint CHAR(64) NOT NULL,
    contract_version VARCHAR(32) NOT NULL DEFAULT 'kaiops.context.v2',
    quality_score DECIMAL(5,4) NOT NULL DEFAULT 0,
    reusable BOOLEAN NOT NULL DEFAULT FALSE,
    source_manifest JSON NOT NULL,
    payload JSON NOT NULL,
    collected_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    expires_at DATETIME(6) NOT NULL,
    KEY idx_context_snapshots_incident_collected (tenant_id, incident_id, collected_at),
    KEY idx_context_snapshots_subject_collected (tenant_id, subject_fingerprint, collected_at),
    KEY idx_context_snapshots_fingerprint (context_fingerprint)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
