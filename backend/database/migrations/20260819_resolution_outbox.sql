-- Atomic lifecycle-to-broker handoff for resolution and closure events.
-- Producers insert here in the same transaction as the incident projection;
-- a retry-safe dispatcher marks rows published only after broker acceptance.

CREATE TABLE IF NOT EXISTS resolution_outbox (
    event_id VARCHAR(160) PRIMARY KEY,
    tenant_id VARCHAR(128) NOT NULL DEFAULT 'default',
    aggregate_id VARCHAR(128) NOT NULL,
    topic VARCHAR(255) NOT NULL,
    partition_key VARCHAR(255) NOT NULL,
    payload JSON NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    published_at DATETIME(6),
    last_error TEXT,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    KEY idx_resolution_outbox_pending (status, next_attempt_at, created_at),
    KEY idx_resolution_outbox_aggregate (tenant_id, aggregate_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS resolution_inbox (
    consumer VARCHAR(128) NOT NULL,
    event_id VARCHAR(160) NOT NULL,
    aggregate_id VARCHAR(128) NOT NULL,
    state_version INTEGER,
    processed_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    result VARCHAR(32) NOT NULL DEFAULT 'processed',
    PRIMARY KEY (consumer, event_id),
    KEY idx_resolution_inbox_aggregate (aggregate_id, state_version, processed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
