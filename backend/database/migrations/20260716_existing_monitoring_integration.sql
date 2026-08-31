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
