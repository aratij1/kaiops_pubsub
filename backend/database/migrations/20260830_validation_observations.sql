CREATE TABLE IF NOT EXISTS validation_observations (
    id VARCHAR(64) NOT NULL PRIMARY KEY,
    tenant_id VARCHAR(128) NOT NULL,
    incident_id CHAR(32) NOT NULL,
    report_id CHAR(32) NOT NULL,
    remediation_action_id CHAR(32) NULL,
    validator_id VARCHAR(255) NOT NULL,
    connector_id VARCHAR(255) NOT NULL,
    target_resource_id VARCHAR(768) NOT NULL,
    observed_at DATETIME(6) NOT NULL,
    collected_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    authoritative_source VARCHAR(255) NOT NULL,
    result_checksum VARCHAR(80) NOT NULL,
    passed BOOLEAN NOT NULL,
    payload JSON NOT NULL,
    KEY idx_validation_observations_incident_time (tenant_id, incident_id, observed_at),
    KEY idx_validation_observations_validator_time (tenant_id, validator_id, observed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
