-- Durable bounded investigation loop for evidence-first resolution.

CREATE TABLE IF NOT EXISTS resolution_investigations (
    investigation_id CHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(128) NOT NULL DEFAULT 'default',
    incident_id VARCHAR(128) NOT NULL,
    alert_id VARCHAR(128),
    status VARCHAR(32) NOT NULL,
    stop_reason VARCHAR(128),
    step_budget INT NOT NULL,
    steps_used INT NOT NULL DEFAULT 0,
    evidence_count INT NOT NULL DEFAULT 0,
    tool_budget JSON NOT NULL,
    source_coverage JSON NOT NULL,
    missing_sources JSON NOT NULL,
    conclusion JSON NOT NULL,
    payload JSON NOT NULL,
    started_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    completed_at DATETIME(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    KEY idx_resolution_investigations_incident (tenant_id, incident_id, started_at),
    KEY idx_resolution_investigations_status (status, updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS resolution_investigation_steps (
    step_id CHAR(36) PRIMARY KEY,
    investigation_id CHAR(36) NOT NULL,
    sequence_no INT NOT NULL,
    tool_name VARCHAR(128) NOT NULL,
    query_payload JSON NOT NULL,
    status VARCHAR(32) NOT NULL,
    result_count INT NOT NULL DEFAULT 0,
    evidence_ids JSON NOT NULL,
    hypothesis_updates JSON NOT NULL,
    error_message VARCHAR(1000),
    started_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    completed_at DATETIME(6),
    UNIQUE KEY uq_resolution_investigation_step (investigation_id, sequence_no),
    KEY idx_resolution_investigation_steps_tool (tool_name, status, started_at),
    CONSTRAINT fk_resolution_investigation_steps_investigation
      FOREIGN KEY (investigation_id) REFERENCES resolution_investigations(investigation_id)
      ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS resolution_hypotheses (
    hypothesis_id CHAR(36) PRIMARY KEY,
    investigation_id CHAR(36) NOT NULL,
    claim_digest CHAR(64) NOT NULL,
    claim_text TEXT NOT NULL,
    status VARCHAR(32) NOT NULL,
    confidence DECIMAL(5,4) NOT NULL DEFAULT 0,
    supporting_evidence_ids JSON NOT NULL,
    contradicting_evidence_ids JSON NOT NULL,
    falsification_query JSON NOT NULL,
    source VARCHAR(64) NOT NULL,
    payload JSON NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    UNIQUE KEY uq_resolution_hypothesis_claim (investigation_id, claim_digest),
    KEY idx_resolution_hypotheses_status (investigation_id, status, confidence),
    CONSTRAINT fk_resolution_hypotheses_investigation
      FOREIGN KEY (investigation_id) REFERENCES resolution_investigations(investigation_id)
      ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
