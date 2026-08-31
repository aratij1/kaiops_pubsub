CREATE TABLE IF NOT EXISTS jira_ticket_links (
    id CHAR(32) PRIMARY KEY,
    fingerprint VARCHAR(255) NOT NULL,
    jira_issue_key VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'open',
    source VARCHAR(64) NOT NULL,
    occurrence_count INTEGER NOT NULL DEFAULT 1,
    first_seen_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    last_seen_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    UNIQUE KEY uq_jira_ticket_links_fingerprint (fingerprint),
    KEY idx_jira_ticket_links_issue_key (jira_issue_key),
    KEY idx_jira_ticket_links_status (status),
    KEY idx_jira_ticket_links_source (source),
    KEY idx_jira_ticket_links_last_seen (last_seen_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
