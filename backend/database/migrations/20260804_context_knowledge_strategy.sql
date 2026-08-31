-- Durable cache-aside context knowledge for Continuous mode (MySQL 8+).
CREATE TABLE IF NOT EXISTS context_knowledge (
    id CHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(128) NOT NULL DEFAULT 'default',
    service VARCHAR(128) NOT NULL,
    environment VARCHAR(64) NOT NULL,
    alert_name VARCHAR(255) NOT NULL,
    alert_signature CHAR(64) NOT NULL,
    source_alert_id CHAR(36),
    source_incident_id CHAR(36),
    collected_at DATETIME(6) NOT NULL,
    reuse_count INT UNSIGNED NOT NULL DEFAULT 0,
    payload JSON NOT NULL,
    resolution_payload JSON NOT NULL,
    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    KEY idx_context_knowledge_lookup (
        tenant_id,
        service,
        environment,
        alert_signature,
        updated_at
    ),
    KEY idx_context_knowledge_collected (collected_at),
    KEY idx_context_knowledge_source_alert (source_alert_id),
    KEY idx_context_knowledge_source_incident (source_incident_id)
);
