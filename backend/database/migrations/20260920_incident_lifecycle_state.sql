-- Forward-only authoritative incident lifecycle state and immutable history.
ALTER TABLE incident_projections
    ADD COLUMN lifecycle_state VARCHAR(64) NOT NULL DEFAULT 'DETECTED',
    ADD COLUMN lifecycle_version INT NOT NULL DEFAULT 1,
    ADD COLUMN lifecycle_failure_code VARCHAR(128) NULL,
    ADD COLUMN lifecycle_failure_reason TEXT NULL,
    ADD INDEX ix_incident_projection_failure (lifecycle_failure_code),
    ADD INDEX ix_incident_projection_lifecycle (tenant_id, lifecycle_state, updated_at);

CREATE TABLE IF NOT EXISTS incident_lifecycle_transitions (
    transition_id CHAR(32) NOT NULL,
    tenant_id VARCHAR(128) NOT NULL,
    incident_id CHAR(32) NOT NULL,
    sequence_no INT NOT NULL,
    previous_state VARCHAR(64) NOT NULL,
    new_state VARCHAR(64) NOT NULL,
    actor VARCHAR(160) NOT NULL,
    reason TEXT NOT NULL,
    failure_code VARCHAR(128) NULL,
    idempotency_key VARCHAR(160) NOT NULL,
    occurred_at DATETIME(6) NOT NULL,
    PRIMARY KEY (transition_id),
    UNIQUE KEY uq_incident_lifecycle_idempotency (tenant_id, idempotency_key),
    UNIQUE KEY uq_incident_lifecycle_sequence (tenant_id, incident_id, sequence_no),
    KEY ix_incident_lifecycle_history (tenant_id, incident_id, sequence_no),
    KEY ix_incident_lifecycle_state (tenant_id, new_state, occurred_at),
    CONSTRAINT fk_incident_lifecycle_projection FOREIGN KEY (incident_id)
        REFERENCES incident_projections (incident_id)
);
