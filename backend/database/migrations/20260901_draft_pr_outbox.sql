CREATE TABLE IF NOT EXISTS draft_pull_request_outbox (
    job_id CHAR(36) NOT NULL PRIMARY KEY,
    idempotency_key VARCHAR(128) NOT NULL UNIQUE,
    tenant_id VARCHAR(128) NOT NULL,
    proposal_id CHAR(36) NOT NULL,
    request_payload JSON NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    next_attempt_at DATETIME(6) NOT NULL,
    provider_response JSON NULL,
    last_error TEXT NULL,
    completed_at DATETIME(6) NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    KEY idx_draft_pr_outbox_due (status, next_attempt_at, created_at),
    KEY idx_draft_pr_outbox_tenant_proposal (tenant_id, proposal_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
