CREATE TABLE IF NOT EXISTS approval_capacity (
    id CHAR(32) PRIMARY KEY,
    tenant_id VARCHAR(128) NOT NULL DEFAULT 'default',
    username VARCHAR(255) NOT NULL UNIQUE,
    resource_names JSON NOT NULL,
    weekly_hours INT NOT NULL DEFAULT 0,
    timezone VARCHAR(64) NOT NULL DEFAULT 'UTC',
    working_days JSON NOT NULL,
    work_start VARCHAR(5) NOT NULL DEFAULT '09:00',
    work_end VARCHAR(5) NOT NULL DEFAULT '17:00',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    INDEX idx_approval_capacity_tenant (tenant_id),
    INDEX idx_approval_capacity_active (active)
);

CREATE TABLE IF NOT EXISTS approval_assignments (
    id CHAR(32) PRIMARY KEY,
    tenant_id VARCHAR(128) NOT NULL DEFAULT 'default',
    incident_id VARCHAR(128) NOT NULL UNIQUE,
    assignee VARCHAR(255) NOT NULL,
    service VARCHAR(128) NOT NULL,
    estimated_hours INT NOT NULL DEFAULT 1,
    status VARCHAR(32) NOT NULL DEFAULT 'assigned',
    assignment_reason TEXT NOT NULL,
    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    INDEX idx_approval_assignment_assignee (assignee),
    INDEX idx_approval_assignment_status (status),
    INDEX idx_approval_assignment_tenant (tenant_id)
);
