-- Forward-only governed human-evidence assignment and Jira synchronization fields.
ALTER TABLE human_evidence_requests
    MODIFY expected_responder VARCHAR(255) NULL,
    ADD COLUMN assignment_source VARCHAR(64) NULL,
    ADD COLUMN assignment_failure_reason VARCHAR(512) NULL,
    ADD COLUMN jira_issue_key VARCHAR(64) NULL,
    ADD COLUMN jira_issue_url VARCHAR(1536) NULL,
    ADD COLUMN jira_version VARCHAR(64) NULL,
    ADD COLUMN jira_assignee_id VARCHAR(255) NULL,
    ADD COLUMN jira_sync_status VARCHAR(32) NULL,
    ADD INDEX ix_human_evidence_assignment (tenant_id, status, expected_responder),
    ADD INDEX ix_human_evidence_jira (tenant_id, jira_issue_key, jira_sync_status);
