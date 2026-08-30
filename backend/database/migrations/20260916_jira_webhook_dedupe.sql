CREATE TABLE IF NOT EXISTS jira_webhook_events (
  id CHAR(36) NOT NULL PRIMARY KEY,
  tenant_id VARCHAR(128) NOT NULL,
  event_id VARCHAR(64) NOT NULL,
  jira_issue_key VARCHAR(64) NOT NULL,
  action VARCHAR(32) NOT NULL,
  actor_id VARCHAR(255) NULL,
  outcome VARCHAR(32) NOT NULL,
  payload_checksum VARCHAR(64) NOT NULL,
  processed_at DATETIME(6) NOT NULL,
  UNIQUE KEY uq_jira_webhook_event (tenant_id, event_id),
  KEY idx_jira_webhook_issue (tenant_id, jira_issue_key, processed_at)
);
