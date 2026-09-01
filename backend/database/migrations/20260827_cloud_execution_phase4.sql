CREATE TABLE IF NOT EXISTS cloud_plan_approvals (
  id CHAR(32) PRIMARY KEY, plan_id CHAR(32) NOT NULL, tenant_id VARCHAR(128) NOT NULL,
  checksum CHAR(64) NOT NULL, decision VARCHAR(32) NOT NULL, reason VARCHAR(1000) NOT NULL,
  actor VARCHAR(255) NOT NULL, decided_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  UNIQUE KEY uq_cloud_plan_approval_binding (tenant_id, plan_id, checksum)
);

CREATE TABLE IF NOT EXISTS cloud_plan_executions (
  id CHAR(32) PRIMARY KEY, plan_id CHAR(32) NOT NULL, tenant_id VARCHAR(128) NOT NULL,
  checksum CHAR(64) NOT NULL, idempotency_key VARCHAR(128) NOT NULL, provider VARCHAR(64) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'leased', action_results JSON NOT NULL, validation JSON NOT NULL,
  error TEXT NULL, actor VARCHAR(255) NOT NULL, lease_expires_at DATETIME(6) NOT NULL,
  started_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), completed_at DATETIME(6) NULL,
  UNIQUE KEY uq_cloud_execution_lease (tenant_id, idempotency_key),
  KEY idx_cloud_execution_plan (tenant_id, plan_id, started_at)
);
