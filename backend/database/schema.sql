CREATE TABLE IF NOT EXISTS alerts (
    id CHAR(32) PRIMARY KEY,
    tenant_id VARCHAR(128) NOT NULL DEFAULT 'default',
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
    KEY idx_alerts_created_at (created_at DESC),
    KEY idx_alerts_tenant (tenant_id),
    -- Lets alert-intelligence scope correlation/dedup candidate scans to the
    -- same service+environment instead of a cluster-wide unfiltered scan.
    KEY idx_alerts_service_env_created (service, environment, created_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS incidents (
    id CHAR(32) PRIMARY KEY,
    tenant_id VARCHAR(128) NOT NULL DEFAULT 'default',
    service VARCHAR(128) NOT NULL,
    environment VARCHAR(64) NOT NULL,
    severity VARCHAR(32) NOT NULL,
    status VARCHAR(64) NOT NULL,
    title VARCHAR(255) NOT NULL,
    ticket_id VARCHAR(128),
    payload JSON NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    KEY idx_incidents_status_severity (status, severity),
    KEY idx_incidents_tenant (tenant_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS approvals (
    id CHAR(32) PRIMARY KEY,
    tenant_id VARCHAR(128) NOT NULL DEFAULT 'default',
    incident_id CHAR(32) NOT NULL,
    recommendation_id CHAR(32) NOT NULL,
    decision VARCHAR(32) NOT NULL,
    approver VARCHAR(255),
    payload JSON NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    KEY idx_approvals_incident (incident_id),
    KEY idx_approvals_tenant (tenant_id),
    CONSTRAINT fk_approvals_incident FOREIGN KEY (incident_id) REFERENCES incidents(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS actions (
    id CHAR(32) PRIMARY KEY,
    tenant_id VARCHAR(128) NOT NULL DEFAULT 'default',
    incident_id CHAR(32) NOT NULL,
    action_type VARCHAR(128) NOT NULL,
    target VARCHAR(255) NOT NULL,
    -- Deterministic sha256(incident_id:recommendation_id:action_type), set by
    -- remediation-engine before executing. NULL for actions where no
    -- execution risk exists (rejected/policy-blocked). Redelivered
    -- approval/resolution messages compute the same key, so this UNIQUE
    -- constraint plus a check-before-execute lookup prevents a message
    -- redelivery from re-running a real remediation plugin twice.
    idempotency_key VARCHAR(64),
    status VARCHAR(32) NOT NULL,
    payload JSON NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    KEY idx_actions_incident (incident_id),
    KEY idx_actions_tenant (tenant_id),
    UNIQUE KEY uq_actions_idempotency (idempotency_key),
    CONSTRAINT fk_actions_incident FOREIGN KEY (incident_id) REFERENCES incidents(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS rca_reports (
    id CHAR(32) PRIMARY KEY,
    tenant_id VARCHAR(128) NOT NULL DEFAULT 'default',
    incident_id CHAR(32) NOT NULL,
    root_cause TEXT NOT NULL,
    impact TEXT NOT NULL,
    payload JSON NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    KEY idx_rca_reports_incident (incident_id),
    KEY idx_rca_reports_tenant (tenant_id),
    CONSTRAINT fk_rca_reports_incident FOREIGN KEY (incident_id) REFERENCES incidents(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS knowledge_base (
    id CHAR(32) PRIMARY KEY,
    tenant_id VARCHAR(128) NOT NULL DEFAULT 'default',
    service VARCHAR(128) NOT NULL,
    title VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    embedding_ref VARCHAR(255),
    payload JSON,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    KEY idx_knowledge_base_service (service),
    KEY idx_knowledge_base_tenant (tenant_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS audit_logs (
    id CHAR(32) PRIMARY KEY,
    tenant_id VARCHAR(128) NOT NULL DEFAULT 'default',
    actor VARCHAR(255) NOT NULL,
    action VARCHAR(255) NOT NULL,
    resource_type VARCHAR(128) NOT NULL,
    resource_id VARCHAR(128) NOT NULL,
    payload JSON,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    KEY idx_audit_logs_tenant (tenant_id),
    KEY idx_audit_logs_actor (actor),
    KEY idx_audit_logs_action (action),
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

CREATE TABLE IF NOT EXISTS evidence_rag_drafts (
    draft_id CHAR(36) NOT NULL, tenant_id VARCHAR(128) NOT NULL,
    project_id VARCHAR(128) NULL, incident_id CHAR(36) NOT NULL, alert_id CHAR(36) NOT NULL,
    analysis_request_id CHAR(36) NOT NULL, context_snapshot_id CHAR(36) NOT NULL,
    context_fingerprint CHAR(64) NOT NULL, recommendation_id CHAR(36) NOT NULL,
    rca_version INT NOT NULL, document_kind VARCHAR(32) NOT NULL, document_version INT NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'draft', title VARCHAR(160) NOT NULL,
    content LONGTEXT NOT NULL, content_checksum CHAR(71) NOT NULL,
    evidence_ids JSON NOT NULL, source_uris JSON NOT NULL, owner_team VARCHAR(160) NULL,
    created_by VARCHAR(160) NOT NULL, reviewed_by VARCHAR(160) NULL, review_notes TEXT NULL,
    reviewed_at DATETIME(6) NULL, approved_by VARCHAR(160) NULL, approved_at DATETIME(6) NULL,
    indexed_at DATETIME(6) NULL, row_version INT NOT NULL DEFAULT 1,
    created_at DATETIME(6) NOT NULL, updated_at DATETIME(6) NOT NULL,
    PRIMARY KEY (draft_id),
    UNIQUE KEY uq_evidence_draft_version (tenant_id, alert_id, document_kind, document_version),
    KEY ix_evidence_draft_incident (tenant_id, incident_id, status),
    KEY ix_evidence_draft_alert (tenant_id, alert_id, status),
    KEY ix_evidence_draft_context (tenant_id, context_snapshot_id, recommendation_id)
);

CREATE TABLE IF NOT EXISTS governed_rag_documents (
    document_id CHAR(36) NOT NULL, draft_id CHAR(36) NOT NULL, tenant_id VARCHAR(128) NOT NULL,
    incident_id CHAR(36) NOT NULL, alert_id CHAR(36) NOT NULL,
    context_snapshot_id CHAR(36) NOT NULL, context_fingerprint CHAR(64) NOT NULL,
    recommendation_id CHAR(36) NOT NULL, rca_version INT NOT NULL,
    document_kind VARCHAR(32) NOT NULL, document_version INT NOT NULL,
    title VARCHAR(160) NOT NULL, content LONGTEXT NOT NULL, content_checksum CHAR(71) NOT NULL,
    evidence_ids JSON NOT NULL, source_uris JSON NOT NULL,
    corpus_classification VARCHAR(32) NOT NULL, review_status VARCHAR(32) NOT NULL,
    approved_by VARCHAR(160) NOT NULL, approved_at DATETIME(6) NOT NULL,
    index_status VARCHAR(32) NOT NULL DEFAULT 'pending', indexed_at DATETIME(6) NULL,
    created_at DATETIME(6) NOT NULL, PRIMARY KEY (document_id),
    UNIQUE KEY uq_governed_document_version (tenant_id, alert_id, document_kind, document_version),
    UNIQUE KEY uq_governed_document_draft (draft_id),
    KEY ix_governed_rag_retrieval (tenant_id, review_status, index_status, document_kind)
);

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
    document_available BOOLEAN,
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
    tenant_id VARCHAR(128) NOT NULL DEFAULT 'default',
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
    KEY idx_users_tenant (tenant_id),
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

CREATE TABLE IF NOT EXISTS monitoring_integrations (
    id CHAR(32) PRIMARY KEY,
    tenant_id VARCHAR(128) NOT NULL DEFAULT 'default',
    project_name VARCHAR(255) NOT NULL,
    provider VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    active BOOLEAN NOT NULL DEFAULT FALSE,
    auth_type VARCHAR(64) NOT NULL DEFAULT 'api_key',
    endpoint_url VARCHAR(512),
    webhook_path VARCHAR(255) NOT NULL,
    deployment_mode VARCHAR(64) NOT NULL DEFAULT 'existing_monitoring',
    config_payload JSON NOT NULL,
    validation_payload JSON NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    KEY idx_monitoring_integrations_tenant (tenant_id),
    KEY idx_monitoring_integrations_provider (provider),
    KEY idx_monitoring_integrations_status (status),
    KEY idx_monitoring_integrations_project (project_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS monitoring_credentials (
    id CHAR(32) PRIMARY KEY,
    integration_id CHAR(32) NOT NULL,
    credential_type VARCHAR(64) NOT NULL,
    secret_ref VARCHAR(255) NOT NULL,
    encrypted_payload JSON NOT NULL,
    redacted_payload JSON NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    KEY idx_monitoring_credentials_integration (integration_id),
    KEY idx_monitoring_credentials_type (credential_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS monitoring_webhook_endpoints (
    id CHAR(32) PRIMARY KEY,
    integration_id CHAR(32) NOT NULL,
    provider VARCHAR(64) NOT NULL,
    webhook_path VARCHAR(255) NOT NULL,
    token_hash VARCHAR(255),
    hmac_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    m_tls_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    metadata_payload JSON NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    KEY idx_monitoring_webhooks_integration (integration_id),
    KEY idx_monitoring_webhooks_provider (provider),
    KEY idx_monitoring_webhooks_active (active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS monitoring_alert_mappings (
    id CHAR(32) PRIMARY KEY,
    integration_id CHAR(32) NOT NULL,
    provider VARCHAR(64) NOT NULL,
    provider_field VARCHAR(128) NOT NULL,
    kaiops_field VARCHAR(128) NOT NULL,
    transform VARCHAR(128),
    required BOOLEAN NOT NULL DEFAULT FALSE,
    mapping_payload JSON NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    KEY idx_monitoring_mappings_integration (integration_id),
    KEY idx_monitoring_mappings_provider_field (provider_field),
    KEY idx_monitoring_mappings_kaiops_field (kaiops_field)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS monitoring_connection_health (
    id CHAR(32) PRIMARY KEY,
    integration_id CHAR(32) NOT NULL,
    provider VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'unknown',
    connectivity_ok BOOLEAN NOT NULL DEFAULT FALSE,
    authentication_ok BOOLEAN NOT NULL DEFAULT FALSE,
    webhook_ok BOOLEAN NOT NULL DEFAULT FALSE,
    last_received_alert_at DATETIME(6),
    last_successful_test_at DATETIME(6),
    rate_limit_remaining INTEGER,
    payload JSON NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    KEY idx_monitoring_health_integration (integration_id),
    KEY idx_monitoring_health_provider (provider),
    KEY idx_monitoring_health_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS monitoring_received_alerts (
    id CHAR(32) PRIMARY KEY,
    integration_id CHAR(32),
    tenant_id VARCHAR(128) NOT NULL DEFAULT 'default',
    provider VARCHAR(64) NOT NULL,
    provider_alert_id VARCHAR(255),
    dedupe_key VARCHAR(255),
    signature_valid BOOLEAN NOT NULL DEFAULT TRUE,
    auth_valid BOOLEAN NOT NULL DEFAULT TRUE,
    status VARCHAR(32) NOT NULL DEFAULT 'received',
    raw_payload JSON NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    KEY idx_monitoring_received_alerts_tenant (tenant_id),
    KEY idx_monitoring_received_alerts_provider (provider),
    KEY idx_monitoring_received_alerts_status (status),
    KEY idx_monitoring_received_alerts_dedupe (dedupe_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS monitoring_normalized_alerts (
    id CHAR(32) PRIMARY KEY,
    received_alert_id CHAR(32) NOT NULL,
    integration_id CHAR(32),
    tenant_id VARCHAR(128) NOT NULL DEFAULT 'default',
    provider VARCHAR(64) NOT NULL,
    application VARCHAR(255),
    environment VARCHAR(64),
    severity VARCHAR(32),
    alert_name VARCHAR(255) NOT NULL,
    resource VARCHAR(255),
    labels JSON NOT NULL,
    annotations JSON NOT NULL,
    normalized_payload JSON NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    KEY idx_monitoring_normalized_alerts_tenant (tenant_id),
    KEY idx_monitoring_normalized_alerts_provider (provider),
    KEY idx_monitoring_normalized_alerts_application (application),
    KEY idx_monitoring_normalized_alerts_alert_name (alert_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS monitoring_connection_audit (
    id CHAR(32) PRIMARY KEY,
    integration_id CHAR(32),
    tenant_id VARCHAR(128) NOT NULL DEFAULT 'default',
    actor VARCHAR(255) NOT NULL,
    action VARCHAR(128) NOT NULL,
    provider VARCHAR(64),
    outcome VARCHAR(32) NOT NULL DEFAULT 'success',
    message VARCHAR(512),
    payload JSON NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    KEY idx_monitoring_audit_tenant (tenant_id),
    KEY idx_monitoring_audit_action (action),
    KEY idx_monitoring_audit_provider (provider),
    KEY idx_monitoring_audit_outcome (outcome),
    KEY idx_monitoring_audit_created (created_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
