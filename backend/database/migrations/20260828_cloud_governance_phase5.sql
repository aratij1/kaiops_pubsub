CREATE TABLE IF NOT EXISTS cloud_execution_policies (
 id CHAR(32) PRIMARY KEY, tenant_id VARCHAR(128) NOT NULL, project_id VARCHAR(128) NOT NULL, environment VARCHAR(64) NOT NULL,
 allowed_providers JSON NOT NULL, allowed_actions JSON NOT NULL, maximum_risk VARCHAR(32) NOT NULL, require_rollback BOOLEAN NOT NULL,
 require_maintenance_window BOOLEAN NOT NULL, enabled BOOLEAN NOT NULL, actor VARCHAR(255) NOT NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
 UNIQUE KEY uq_cloud_execution_policy_scope (tenant_id, project_id, environment)
);
CREATE TABLE IF NOT EXISTS cloud_maintenance_windows (
 id CHAR(32) PRIMARY KEY, tenant_id VARCHAR(128) NOT NULL, project_id VARCHAR(128) NOT NULL, environment VARCHAR(64) NOT NULL,
 starts_at DATETIME(6) NOT NULL, ends_at DATETIME(6) NOT NULL, reason VARCHAR(512) NOT NULL, actor VARCHAR(255) NOT NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), KEY idx_cloud_window_scope (tenant_id, project_id, environment, starts_at, ends_at)
);
CREATE TABLE IF NOT EXISTS cloud_credential_sessions (
 id CHAR(32) PRIMARY KEY, tenant_id VARCHAR(128) NOT NULL, execution_id CHAR(32) NOT NULL, provider VARCHAR(64) NOT NULL,
 credential_ref VARCHAR(512) NOT NULL, scopes JSON NOT NULL, expires_at DATETIME(6) NOT NULL, revoked_at DATETIME(6) NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), KEY idx_cloud_credential_expiry (tenant_id, expires_at)
);
CREATE TABLE IF NOT EXISTS cloud_compensations (
 id CHAR(32) PRIMARY KEY, tenant_id VARCHAR(128) NOT NULL, execution_id CHAR(32) NOT NULL, sequence INT NOT NULL,
 resource_id VARCHAR(128) NOT NULL, rollback_action VARCHAR(128) NOT NULL, status VARCHAR(32) NOT NULL, evidence JSON NOT NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), KEY idx_cloud_compensation_execution (tenant_id, execution_id, sequence)
);
