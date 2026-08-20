-- Durable, queryable control-plane records for governed self-healing.
-- Existing JSON payloads remain intact; this migration is additive and safe
-- for rolling deployment of older services.

CREATE TABLE IF NOT EXISTS execution_plans (
    id CHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(128) NOT NULL DEFAULT 'default',
    incident_id CHAR(32) NOT NULL,
    recommendation_id CHAR(36),
    playbook_id VARCHAR(255) NOT NULL,
    schema_version VARCHAR(64) NOT NULL,
    fingerprint CHAR(71) NOT NULL,
    target_service VARCHAR(255) NOT NULL,
    target_environment VARCHAR(64) NOT NULL,
    risk_tier VARCHAR(32) NOT NULL,
    execution_mode VARCHAR(32) NOT NULL,
    approval_required BOOLEAN NOT NULL DEFAULT TRUE,
    execution_ready BOOLEAN NOT NULL DEFAULT FALSE,
    readiness_blocks JSON NOT NULL,
    plan_payload JSON NOT NULL,
    supersedes_plan_id CHAR(36),
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    UNIQUE KEY uq_execution_plans_fingerprint (tenant_id, fingerprint),
    KEY idx_execution_plans_incident_created (tenant_id, incident_id, created_at DESC),
    KEY idx_execution_plans_target_ready (tenant_id, target_service, execution_ready),
    CONSTRAINT fk_execution_plans_incident FOREIGN KEY (incident_id) REFERENCES incidents(id),
    CONSTRAINT fk_execution_plans_supersedes FOREIGN KEY (supersedes_plan_id) REFERENCES execution_plans(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS remediation_attempts (
    id CHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(128) NOT NULL DEFAULT 'default',
    incident_id CHAR(32) NOT NULL,
    action_id CHAR(32),
    execution_plan_id CHAR(36) NOT NULL,
    approval_id CHAR(32),
    attempt_number INTEGER NOT NULL,
    executor_type VARCHAR(64) NOT NULL,
    executor_reference VARCHAR(512),
    status VARCHAR(32) NOT NULL,
    failure_class VARCHAR(64),
    failure_reason TEXT,
    started_at DATETIME(6),
    completed_at DATETIME(6),
    attempt_payload JSON NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    UNIQUE KEY uq_remediation_attempt_number (tenant_id, execution_plan_id, attempt_number),
    KEY idx_remediation_attempts_incident_status (tenant_id, incident_id, status, created_at DESC),
    CONSTRAINT fk_remediation_attempts_incident FOREIGN KEY (incident_id) REFERENCES incidents(id),
    CONSTRAINT fk_remediation_attempts_plan FOREIGN KEY (execution_plan_id) REFERENCES execution_plans(id),
    CONSTRAINT fk_remediation_attempts_action FOREIGN KEY (action_id) REFERENCES actions(id),
    CONSTRAINT fk_remediation_attempts_approval FOREIGN KEY (approval_id) REFERENCES approvals(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS recovery_evidence (
    id CHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(128) NOT NULL DEFAULT 'default',
    incident_id CHAR(32) NOT NULL,
    remediation_attempt_id CHAR(36) NOT NULL,
    evidence_type VARCHAR(64) NOT NULL,
    source VARCHAR(128) NOT NULL,
    check_name VARCHAR(255) NOT NULL,
    passed BOOLEAN NOT NULL,
    observed_value TEXT,
    expected_value TEXT,
    evidence_payload JSON NOT NULL,
    observed_at DATETIME(6) NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    KEY idx_recovery_evidence_attempt (tenant_id, remediation_attempt_id, observed_at),
    KEY idx_recovery_evidence_incident_passed (tenant_id, incident_id, passed, observed_at DESC),
    CONSTRAINT fk_recovery_evidence_incident FOREIGN KEY (incident_id) REFERENCES incidents(id),
    CONSTRAINT fk_recovery_evidence_attempt FOREIGN KEY (remediation_attempt_id) REFERENCES remediation_attempts(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS remediation_outcomes (
    id CHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(128) NOT NULL DEFAULT 'default',
    incident_id CHAR(32) NOT NULL,
    remediation_attempt_id CHAR(36) NOT NULL,
    playbook_id VARCHAR(255) NOT NULL,
    target_service VARCHAR(255) NOT NULL,
    successful BOOLEAN NOT NULL,
    rolled_back BOOLEAN NOT NULL DEFAULT FALSE,
    operator_modified BOOLEAN NOT NULL DEFAULT FALSE,
    time_to_recovery_seconds INTEGER,
    confidence_before DOUBLE,
    confidence_after DOUBLE,
    outcome_payload JSON NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    UNIQUE KEY uq_remediation_outcomes_attempt (tenant_id, remediation_attempt_id),
    KEY idx_remediation_outcomes_learning (tenant_id, playbook_id, target_service, successful, created_at DESC),
    CONSTRAINT fk_remediation_outcomes_incident FOREIGN KEY (incident_id) REFERENCES incidents(id),
    CONSTRAINT fk_remediation_outcomes_attempt FOREIGN KEY (remediation_attempt_id) REFERENCES remediation_attempts(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
