CREATE TABLE IF NOT EXISTS context_evidence_requirements (
  requirement_id CHAR(36) NOT NULL PRIMARY KEY, tenant_id VARCHAR(128) NOT NULL,
  incident_id CHAR(36) NOT NULL, rca_version INT NOT NULL, requirement_key VARCHAR(64) NOT NULL,
  category VARCHAR(32) NOT NULL, question TEXT NOT NULL, reason TEXT NOT NULL,
  priority VARCHAR(16) NOT NULL, collection_mode VARCHAR(32) NOT NULL,
  candidate_connectors JSON NOT NULL, status VARCHAR(32) NOT NULL,
  retry_count INT NOT NULL DEFAULT 0, retry_after DATETIME(6) NULL,
  assigned_to VARCHAR(255) NULL, jira_issue_key VARCHAR(64) NULL, evidence_ids JSON NOT NULL,
  version INT NOT NULL DEFAULT 1, created_at DATETIME(6) NOT NULL, updated_at DATETIME(6) NOT NULL,
  UNIQUE KEY uq_context_requirement (tenant_id, incident_id, rca_version, requirement_key),
  KEY idx_context_requirement_work (tenant_id, status, retry_after)
);

CREATE TABLE IF NOT EXISTS context_enrichment_jobs (
  job_id CHAR(36) NOT NULL PRIMARY KEY, tenant_id VARCHAR(128) NOT NULL,
  incident_id CHAR(36) NOT NULL, requirement_id CHAR(36) NOT NULL,
  connector_id VARCHAR(255) NOT NULL, idempotency_key VARCHAR(64) NOT NULL,
  query_payload JSON NOT NULL, observation_start DATETIME(6) NOT NULL,
  observation_end DATETIME(6) NOT NULL, status VARCHAR(32) NOT NULL,
  attempt_count INT NOT NULL DEFAULT 0, available_at DATETIME(6) NOT NULL,
  last_error TEXT NULL, version INT NOT NULL DEFAULT 1,
  created_at DATETIME(6) NOT NULL, updated_at DATETIME(6) NOT NULL,
  UNIQUE KEY uq_context_enrichment_job (tenant_id, idempotency_key),
  KEY idx_context_enrichment_job_work (tenant_id, status, available_at)
);

CREATE TABLE IF NOT EXISTS human_evidence_requests (
  request_id CHAR(36) NOT NULL PRIMARY KEY, tenant_id VARCHAR(128) NOT NULL,
  incident_id CHAR(36) NOT NULL, requirement_id CHAR(36) NOT NULL,
  expected_responder VARCHAR(255) NOT NULL, due_at DATETIME(6) NOT NULL,
  acceptable_format VARCHAR(512) NOT NULL, investigation_can_continue BOOLEAN NOT NULL DEFAULT TRUE,
  evidence_already_checked JSON NOT NULL, hypothesis_impact TEXT NOT NULL,
  status VARCHAR(32) NOT NULL, response_payload JSON NOT NULL, version INT NOT NULL DEFAULT 1,
  created_at DATETIME(6) NOT NULL, updated_at DATETIME(6) NOT NULL,
  UNIQUE KEY uq_human_evidence_requirement (tenant_id, requirement_id)
);

CREATE TABLE IF NOT EXISTS jira_incident_bindings (
  binding_id CHAR(36) NOT NULL PRIMARY KEY, tenant_id VARCHAR(128) NOT NULL,
  incident_id CHAR(36) NOT NULL, jira_issue_key VARCHAR(64) NOT NULL,
  jira_project_key VARCHAR(64) NOT NULL, assignee_id VARCHAR(255) NOT NULL,
  assignee_group VARCHAR(255) NULL, recommendation_id CHAR(36) NULL,
  rca_version INT NOT NULL, context_snapshot_id CHAR(36) NOT NULL,
  context_fingerprint VARCHAR(64) NOT NULL, resolution_selection_id CHAR(36) NULL,
  execution_plan_id CHAR(36) NULL, plan_fingerprint VARCHAR(71) NULL,
  approval_expires_at DATETIME(6) NULL, status VARCHAR(32) NOT NULL,
  jira_status VARCHAR(128) NOT NULL, ownership VARCHAR(16) NOT NULL,
  closure_policy JSON NOT NULL, last_jira_updated_at DATETIME(6) NULL,
  last_synced_at DATETIME(6) NULL, binding_version INT NOT NULL DEFAULT 1,
  created_at DATETIME(6) NOT NULL, updated_at DATETIME(6) NOT NULL,
  UNIQUE KEY uq_jira_binding_issue (tenant_id, jira_issue_key),
  UNIQUE KEY uq_jira_binding_version (tenant_id, incident_id, binding_version),
  KEY idx_jira_binding_current (tenant_id, incident_id, status)
);

CREATE TABLE IF NOT EXISTS jira_sync_cursors (
  cursor_id CHAR(36) NOT NULL PRIMARY KEY, tenant_id VARCHAR(128) NOT NULL,
  jira_project_key VARCHAR(64) NOT NULL, last_successful_poll_at DATETIME(6) NULL,
  last_jira_updated_timestamp DATETIME(6) NULL, last_issue_key VARCHAR(64) NULL,
  poll_status VARCHAR(32) NOT NULL, poll_error TEXT NULL, version INT NOT NULL DEFAULT 1,
  created_at DATETIME(6) NOT NULL, updated_at DATETIME(6) NOT NULL,
  UNIQUE KEY uq_jira_sync_cursor (tenant_id, jira_project_key)
);
