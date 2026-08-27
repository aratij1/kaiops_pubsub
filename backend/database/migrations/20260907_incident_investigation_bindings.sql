-- Immutable normalized binding for one alert/context/RCA/plan generation.
-- Historical recommendations are intentionally not backfilled with guessed IDs.
CREATE TABLE IF NOT EXISTS incident_investigation_bindings (
    binding_id CHAR(32) NOT NULL,
    tenant_id VARCHAR(128) NOT NULL,
    project_id VARCHAR(128) NOT NULL,
    incident_id CHAR(32) NOT NULL,
    alert_id CHAR(32) NOT NULL,
    analysis_request_id CHAR(32) NOT NULL,
    context_snapshot_id CHAR(32) NOT NULL,
    context_fingerprint VARCHAR(64) NOT NULL,
    recommendation_id CHAR(32) NOT NULL,
    rca_version INT NOT NULL,
    resolution_plan_id CHAR(32) NULL,
    plan_fingerprint VARCHAR(71) NULL,
    status VARCHAR(32) NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    expires_at DATETIME(6) NOT NULL,
    PRIMARY KEY (binding_id),
    UNIQUE KEY uq_investigation_binding_request (tenant_id, analysis_request_id),
    UNIQUE KEY uq_investigation_binding_version (tenant_id, incident_id, rca_version),
    KEY idx_investigation_binding_current (
        tenant_id, incident_id, alert_id, recommendation_id, status
    ),
    KEY idx_investigation_binding_context (
        tenant_id, context_snapshot_id, context_fingerprint
    ),
    CONSTRAINT fk_investigation_binding_context
        FOREIGN KEY (context_snapshot_id) REFERENCES context_snapshots(snapshot_id),
    CONSTRAINT fk_investigation_binding_incident
        FOREIGN KEY (incident_id) REFERENCES incidents(id),
    CONSTRAINT fk_investigation_binding_alert
        FOREIGN KEY (alert_id) REFERENCES alerts(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
