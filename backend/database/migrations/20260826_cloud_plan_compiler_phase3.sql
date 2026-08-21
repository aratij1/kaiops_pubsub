CREATE TABLE IF NOT EXISTS cloud_compiled_plans (
  id CHAR(32) PRIMARY KEY, tenant_id VARCHAR(128) NOT NULL, project_id VARCHAR(128) NOT NULL,
  service_id VARCHAR(128) NOT NULL, environment VARCHAR(64) NOT NULL, intent VARCHAR(512) NOT NULL,
  actions JSON NOT NULL, risk_level VARCHAR(32) NOT NULL, requires_approval BOOLEAN NOT NULL DEFAULT TRUE,
  checksum CHAR(64) NOT NULL, status VARCHAR(32) NOT NULL DEFAULT 'compiled', compiled_by VARCHAR(255) NOT NULL,
  compiled_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), UNIQUE KEY uq_cloud_plan_checksum (checksum),
  KEY idx_cloud_plan_scope (tenant_id, project_id, service_id, environment)
);

CREATE TABLE IF NOT EXISTS cloud_plan_simulations (
  id CHAR(32) PRIMARY KEY, plan_id CHAR(32) NOT NULL, tenant_id VARCHAR(128) NOT NULL,
  verdict VARCHAR(32) NOT NULL, gates JSON NOT NULL, simulated_by VARCHAR(255) NOT NULL,
  simulated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  KEY idx_cloud_simulation_plan (tenant_id, plan_id, simulated_at)
);
