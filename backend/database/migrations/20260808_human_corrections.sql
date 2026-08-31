-- Durable, auditable human feedback for automated triage and analysis decisions.
-- Additive and MySQL 8 compatible. The application also creates this table
-- through SQLAlchemy metadata for new installations.
CREATE TABLE IF NOT EXISTS human_corrections (
    id CHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(128) NOT NULL DEFAULT 'default',
    entity_type VARCHAR(64) NOT NULL,
    entity_id VARCHAR(255) NOT NULL,
    correction_type VARCHAR(64) NOT NULL,
    original_payload JSON NOT NULL,
    corrected_payload JSON NOT NULL,
    reason TEXT NOT NULL,
    actor VARCHAR(255) NOT NULL,
    actor_role VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'recorded',
    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    KEY idx_human_corrections_tenant (tenant_id),
    KEY idx_human_corrections_entity_created (tenant_id, entity_type, entity_id, created_at),
    KEY idx_human_corrections_type_created (tenant_id, correction_type, created_at),
    KEY idx_human_corrections_actor (actor),
    KEY idx_human_corrections_actor_role (actor_role),
    KEY idx_human_corrections_status (status)
);
