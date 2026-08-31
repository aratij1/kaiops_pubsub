-- Durable lifecycle, runbook governance and reviewed execution history.

CREATE TABLE IF NOT EXISTS resolution_state_transitions (
    transition_id CHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(128) NOT NULL DEFAULT 'default',
    incident_id VARCHAR(128) NOT NULL,
    recommendation_id CHAR(36),
    execution_plan_id CHAR(36),
    previous_state VARCHAR(32) NOT NULL,
    new_state VARCHAR(32) NOT NULL,
    event_id CHAR(36) NOT NULL,
    correlation_id VARCHAR(128),
    causation_id VARCHAR(128),
    idempotency_key VARCHAR(255) NOT NULL,
    actor VARCHAR(64) NOT NULL,
    occurred_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    reason_code VARCHAR(128) NOT NULL,
    evidence_ids JSON NOT NULL,
    policy_decision JSON NOT NULL,
    payload JSON NOT NULL,
    UNIQUE KEY uq_resolution_transition_event (tenant_id, event_id),
    UNIQUE KEY uq_resolution_transition_idempotency (tenant_id, idempotency_key),
    KEY idx_resolution_transition_incident (tenant_id, incident_id, occurred_at),
    KEY idx_resolution_transition_state (new_state, occurred_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS runbooks (
    runbook_id CHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(128) NOT NULL DEFAULT 'default',
    slug VARCHAR(255) NOT NULL,
    owner VARCHAR(255) NOT NULL,
    service VARCHAR(255) NOT NULL,
    alert_family VARCHAR(255) NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    UNIQUE KEY uq_runbook_slug (tenant_id, slug),
    KEY idx_runbook_match (tenant_id, service, alert_family)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS runbook_parameters (
    parameter_id CHAR(36) PRIMARY KEY,
    runbook_id CHAR(36) NOT NULL,
    version INT UNSIGNED NOT NULL,
    parameter_name VARCHAR(128) NOT NULL,
    parameter_schema JSON NOT NULL,
    required BOOLEAN NOT NULL DEFAULT TRUE,
    secret_reference BOOLEAN NOT NULL DEFAULT FALSE,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    UNIQUE KEY uq_runbook_parameter (runbook_id, version, parameter_name),
    CONSTRAINT fk_runbook_parameter_runbook FOREIGN KEY (runbook_id) REFERENCES runbooks(runbook_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS runbook_approvals (
    approval_id CHAR(36) PRIMARY KEY,
    runbook_id CHAR(36) NOT NULL,
    version INT UNSIGNED NOT NULL,
    status VARCHAR(32) NOT NULL,
    approver VARCHAR(255) NOT NULL,
    approver_role VARCHAR(64) NOT NULL,
    reason VARCHAR(1000),
    approved_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    UNIQUE KEY uq_runbook_version_approval (runbook_id, version, status),
    CONSTRAINT fk_runbook_approval_runbook FOREIGN KEY (runbook_id) REFERENCES runbooks(runbook_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS runbook_execution_history (
    execution_history_id CHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(128) NOT NULL DEFAULT 'default',
    incident_id VARCHAR(128) NOT NULL,
    runbook_id CHAR(36) NOT NULL,
    version INT UNSIGNED NOT NULL,
    execution_plan_id CHAR(36),
    outcome VARCHAR(64) NOT NULL,
    reviewed BOOLEAN NOT NULL DEFAULT FALSE,
    reviewed_by VARCHAR(255),
    validation JSON NOT NULL,
    operator_edits JSON NOT NULL,
    started_at DATETIME(6),
    completed_at DATETIME(6),
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    UNIQUE KEY uq_runbook_execution_incident (tenant_id, incident_id, runbook_id, version),
    KEY idx_runbook_execution_learning (tenant_id, runbook_id, version, outcome, reviewed, created_at),
    CONSTRAINT fk_runbook_execution_runbook FOREIGN KEY (runbook_id) REFERENCES runbooks(runbook_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
