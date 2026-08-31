-- User Management & RBAC migration (MySQL 8+)

CREATE TABLE IF NOT EXISTS roles (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(50) UNIQUE NOT NULL,
    description VARCHAR(255),
    is_system_role BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS users (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(64) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    first_name VARCHAR(80) NOT NULL,
    last_name VARCHAR(80) NOT NULL,
    role_id BIGINT NOT NULL REFERENCES roles(id),
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    last_login TIMESTAMP NULL,
    failed_login_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until TIMESTAMP NULL,
    password_changed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_sessions (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    jwt_id VARCHAR(128) UNIQUE NOT NULL,
    login_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expiry_time TIMESTAMP NOT NULL,
    ip_address VARCHAR(64),
    device VARCHAR(255),
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- created_at/updated_at are set explicitly rather than relying on a
-- database-level DEFAULT CURRENT_TIMESTAMP: the app's own ORM bootstrap
-- (common/database.py create_schema(), which runs at every service startup
-- and typically creates this table before any migration file is applied by
-- hand) maps TimestampMixin's `default=utc_now` as a Python-side default
-- only — the resulting live DDL has no database-level default on these
-- columns, so an INSERT that omits them fails with "doesn't have a default
-- value" against a table created that way.
INSERT INTO roles (name, description, is_system_role, created_at, updated_at)
VALUES
    ('Administrator', 'Full platform administration', TRUE, NOW(6), NOW(6)),
    ('Executive', 'Read-only executive analytics', TRUE, NOW(6), NOW(6)),
    ('L3 Engineer', 'Advanced investigation and approvals', TRUE, NOW(6), NOW(6)),
    ('L2 Engineer', 'Incident investigation and runbook execution', TRUE, NOW(6), NOW(6)),
    ('L1 Operator', 'Alert triage and escalation', TRUE, NOW(6), NOW(6))
ON DUPLICATE KEY UPDATE name = VALUES(name);
