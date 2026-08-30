CREATE TABLE IF NOT EXISTS analysis_requests (
    request_id CHAR(32) NOT NULL PRIMARY KEY,
    tenant_id VARCHAR(128) NOT NULL,
    incident_id CHAR(32) NOT NULL,
    alert_id CHAR(32) NOT NULL,
    expected_recommendation_id CHAR(32) NOT NULL,
    mode VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'accepted',
    delivery VARCHAR(32) NOT NULL DEFAULT 'pending',
    recommendation_id CHAR(32) NULL,
    terminal_reason VARCHAR(255) NULL,
    completed_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_analysis_requests_recommendation (expected_recommendation_id),
    KEY idx_analysis_requests_incident_status (tenant_id, incident_id, status, created_at),
    KEY idx_analysis_requests_alert_created (tenant_id, alert_id, created_at),
    KEY idx_analysis_requests_recommendation_id (recommendation_id)
);
