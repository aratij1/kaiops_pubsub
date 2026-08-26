CREATE TABLE IF NOT EXISTS alerts (
    id CHAR(32) PRIMARY KEY,
    source VARCHAR(64) NOT NULL,
    name VARCHAR(255) NOT NULL,
    service VARCHAR(128) NOT NULL,
    environment VARCHAR(64) NOT NULL,
    severity VARCHAR(32) NOT NULL,
    fingerprint VARCHAR(255),
    correlation_id VARCHAR(255),
    payload JSON NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    KEY idx_alerts_service_severity (service, severity),
    KEY idx_alerts_created_at (created_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS incidents (
    id CHAR(32) PRIMARY KEY,
    service VARCHAR(128) NOT NULL,
    environment VARCHAR(64) NOT NULL,
    severity VARCHAR(32) NOT NULL,
    status VARCHAR(64) NOT NULL,
    title VARCHAR(255) NOT NULL,
    ticket_id VARCHAR(128),
    payload JSON NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    KEY idx_incidents_status_severity (status, severity)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS approvals (
    id CHAR(32) PRIMARY KEY,
    incident_id CHAR(32) NOT NULL,
    recommendation_id CHAR(32) NOT NULL,
    decision VARCHAR(32) NOT NULL,
    approver VARCHAR(255),
    payload JSON NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    KEY idx_approvals_incident (incident_id),
    CONSTRAINT fk_approvals_incident FOREIGN KEY (incident_id) REFERENCES incidents(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS actions (
    id CHAR(32) PRIMARY KEY,
    incident_id CHAR(32) NOT NULL,
    action_type VARCHAR(128) NOT NULL,
    target VARCHAR(255) NOT NULL,
    status VARCHAR(32) NOT NULL,
    payload JSON NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    KEY idx_actions_incident (incident_id),
    CONSTRAINT fk_actions_incident FOREIGN KEY (incident_id) REFERENCES incidents(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS rca_reports (
    id CHAR(32) PRIMARY KEY,
    incident_id CHAR(32) NOT NULL,
    root_cause VARCHAR(255) NOT NULL,
    impact VARCHAR(255) NOT NULL,
    payload JSON NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    KEY idx_rca_reports_incident (incident_id),
    CONSTRAINT fk_rca_reports_incident FOREIGN KEY (incident_id) REFERENCES incidents(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS knowledge_base (
    id CHAR(32) PRIMARY KEY,
    service VARCHAR(128) NOT NULL,
    title VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    embedding_ref VARCHAR(255),
    payload JSON,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    KEY idx_knowledge_base_service (service)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS audit_logs (
    id CHAR(32) PRIMARY KEY,
    actor VARCHAR(255) NOT NULL,
    action VARCHAR(255) NOT NULL,
    resource_type VARCHAR(128) NOT NULL,
    resource_id VARCHAR(128) NOT NULL,
    payload JSON,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    KEY idx_audit_logs_actor (actor),
    KEY idx_audit_logs_action (action),
    KEY idx_audit_logs_created_at (created_at),
    KEY idx_audit_logs_resource (resource_type, resource_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS onboarding_state (
    project_name VARCHAR(255) NOT NULL,
    provider_name VARCHAR(64) NOT NULL,
    owner_team VARCHAR(255),
    environment VARCHAR(64),
    region VARCHAR(128),
    endpoint_url VARCHAR(512),
    test_status VARCHAR(32),
    test_message VARCHAR(512),
    project_payload JSON NOT NULL,
    connectivity_payload JSON NOT NULL,
    last_tested_at DATETIME(6),
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (project_name, provider_name),
    KEY idx_onboarding_state_status (test_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS pending_workflows (
    incident_id CHAR(32) PRIMARY KEY,
    recommendation_id CHAR(32) NOT NULL,
    flow_id VARCHAR(128) NOT NULL,
    trace_id VARCHAR(128),
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    payload JSON NOT NULL,
    completed_payload JSON,
    completed_at DATETIME(6),
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    KEY idx_pending_workflows_status (status),
    KEY idx_pending_workflows_recommendation (recommendation_id),
    KEY idx_pending_workflows_trace (trace_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS agent_work_items (
    id CHAR(32) PRIMARY KEY,
    incident_id CHAR(32) NOT NULL,
    agent_name VARCHAR(128) NOT NULL,
    trace_id VARCHAR(128),
    ticket_id VARCHAR(128),
    work_item VARCHAR(255) NOT NULL,
    status VARCHAR(32) NOT NULL,
    sequence INTEGER,
    details JSON NOT NULL,
    started_at DATETIME(6),
    completed_at DATETIME(6),
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    KEY idx_agent_work_items_incident (incident_id),
    KEY idx_agent_work_items_agent_seq (agent_name, sequence),
    KEY idx_agent_work_items_status (status),
    KEY idx_agent_work_items_trace (trace_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS incident_events (
    id CHAR(32) PRIMARY KEY,
    incident_id CHAR(32) NOT NULL,
    alert_id CHAR(32),
    trace_id VARCHAR(128),
    correlation_id VARCHAR(255),
    causation_id VARCHAR(255),
    parent_event_id CHAR(32),
    tenant_id VARCHAR(128) NOT NULL DEFAULT 'default',
    service VARCHAR(128) NOT NULL,
    environment VARCHAR(64) NOT NULL,
    region VARCHAR(128),
    team VARCHAR(128),
    severity VARCHAR(32),
    status VARCHAR(64),
    event_type VARCHAR(128) NOT NULL,
    event_stage VARCHAR(64) NOT NULL,
    risk_tier VARCHAR(32),
    execution_mode VARCHAR(32),
    requires_approval BOOLEAN,
    policy_version VARCHAR(64),
    policy_reason TEXT,
    confidence DOUBLE,
    model_provider VARCHAR(64),
    model_name VARCHAR(128),
    transport_provider VARCHAR(32) NOT NULL,
    transport_channel VARCHAR(128) NOT NULL,
    transport_partition INTEGER,
    transport_offset BIGINT,
    transport_delivery_tag VARCHAR(128),
    idempotency_key VARCHAR(255),
    fingerprint VARCHAR(255),
    payload JSON NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    KEY idx_incident_events_incident_time (incident_id, created_at DESC),
    KEY idx_incident_events_service_status_time (service, status, created_at DESC),
    KEY idx_incident_events_trace (trace_id),
    KEY idx_incident_events_corr (correlation_id),
    KEY idx_incident_events_transport (transport_provider, transport_channel, created_at DESC),
    UNIQUE KEY uq_incident_events_idempotency (transport_provider, idempotency_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS incident_projections (
    incident_id CHAR(32) PRIMARY KEY,
    alert_id CHAR(32),
    trace_id VARCHAR(128),
    recommendation_id CHAR(32),
    flow_id VARCHAR(128),
    tenant_id VARCHAR(128) NOT NULL DEFAULT 'default',
    service VARCHAR(128) NOT NULL,
    environment VARCHAR(64) NOT NULL,
    severity VARCHAR(32),
    status VARCHAR(64) NOT NULL,
    owner VARCHAR(128),
    risk_tier VARCHAR(32),
    execution_mode VARCHAR(32),
    requires_approval BOOLEAN,
    policy_version VARCHAR(64),
    policy_reason TEXT,
    transport_provider VARCHAR(32),
    latest_event_id CHAR(32),
    latest_event_type VARCHAR(128),
    latest_event_at DATETIME(6),
    first_seen_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    projection_payload JSON NOT NULL,
    KEY idx_incident_projections_status (status),
    KEY idx_incident_projections_recommendation (recommendation_id),
    KEY idx_incident_projections_flow (flow_id),
    KEY idx_incident_projections_service_severity (service, severity),
    KEY idx_incident_projections_risk_mode (risk_tier, execution_mode),
    KEY idx_incident_projections_updated (updated_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS roles (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(50) UNIQUE NOT NULL,
    description VARCHAR(255),
    is_system_role BOOLEAN NOT NULL DEFAULT TRUE,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS users (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(64) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    first_name VARCHAR(80) NOT NULL,
    last_name VARCHAR(80) NOT NULL,
    role_id BIGINT NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    last_login DATETIME(6),
    failed_login_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until DATETIME(6),
    password_changed_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    KEY idx_users_role (role_id),
    KEY idx_users_status (status),
    CONSTRAINT fk_users_role FOREIGN KEY (role_id) REFERENCES roles(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS user_sessions (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    jwt_id VARCHAR(128) UNIQUE NOT NULL,
    login_time DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    expiry_time DATETIME(6) NOT NULL,
    ip_address VARCHAR(64),
    device VARCHAR(255),
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    KEY idx_user_sessions_user (user_id),
    KEY idx_user_sessions_status (status),
    CONSTRAINT fk_user_sessions_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
