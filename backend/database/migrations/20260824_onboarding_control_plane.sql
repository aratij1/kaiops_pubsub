CREATE TABLE IF NOT EXISTS onboarding_control_planes (
  onboarding_id CHAR(36) NOT NULL,
  tenant_id VARCHAR(128) NOT NULL,
  project_name VARCHAR(255) NOT NULL,
  current_step INT NOT NULL DEFAULT 1,
  status VARCHAR(32) NOT NULL DEFAULT 'DRAFT',
  version INT NOT NULL DEFAULT 1,
  payload JSON NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (onboarding_id),
  KEY idx_onboarding_control_plane_tenant_status (tenant_id, status),
  KEY idx_onboarding_control_plane_project (tenant_id, project_name)
);
