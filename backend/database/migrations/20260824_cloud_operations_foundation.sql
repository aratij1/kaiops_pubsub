-- Provider-neutral cloud operations foundation.
-- Adds tenant/project-scoped connection, discovery, inventory, topology,
-- service mapping, readiness, and audit records. Credential values are never
-- stored here; provider_connections.credential_ref must point at an external
-- vault/workload identity/managed identity reference.

CREATE TABLE IF NOT EXISTS provider_connections (
    id CHAR(32) NOT NULL PRIMARY KEY,
    tenant_id VARCHAR(128) NOT NULL,
    project_id VARCHAR(128) NOT NULL,
    provider_type VARCHAR(64) NOT NULL,
    connection_name VARCHAR(255) NOT NULL,
    credential_ref VARCHAR(512) NOT NULL DEFAULT '',
    auth_method VARCHAR(64) NOT NULL DEFAULT 'credential_ref',
    allowed_regions JSON NOT NULL,
    resource_filters JSON NOT NULL,
    discovery_scope JSON NOT NULL,
    read_capability BOOLEAN NOT NULL DEFAULT TRUE,
    write_capability BOOLEAN NOT NULL DEFAULT FALSE,
    connection_owner VARCHAR(255) NOT NULL,
    last_health_check_at DATETIME NULL,
    last_discovery_at DATETIME NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    failure_reason TEXT NULL,
    version INT NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_provider_connections_scope_name (tenant_id, project_id, connection_name),
    KEY idx_provider_connections_scope_status (tenant_id, project_id, provider_type, status),
    KEY idx_provider_connections_owner (connection_owner)
);

CREATE TABLE IF NOT EXISTS connection_health_checks (
    id CHAR(32) NOT NULL PRIMARY KEY,
    connection_id CHAR(32) NOT NULL,
    tenant_id VARCHAR(128) NOT NULL,
    project_id VARCHAR(128) NOT NULL,
    provider_type VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    connectivity_ok BOOLEAN NOT NULL DEFAULT FALSE,
    authentication_ok BOOLEAN NOT NULL DEFAULT FALSE,
    requested_permissions JSON NOT NULL,
    granted_permissions JSON NOT NULL,
    missing_permissions JSON NOT NULL,
    payload JSON NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_connection_health_scope_created (tenant_id, project_id, connection_id, created_at),
    KEY idx_connection_health_status (status)
);

CREATE TABLE IF NOT EXISTS discovery_runs (
    id CHAR(32) NOT NULL PRIMARY KEY,
    tenant_id VARCHAR(128) NOT NULL,
    project_id VARCHAR(128) NOT NULL,
    connection_id CHAR(32) NOT NULL,
    provider_type VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'started',
    requested_by VARCHAR(255) NOT NULL,
    discovery_scope JSON NOT NULL,
    resource_count INT NOT NULL DEFAULT 0,
    relationship_count INT NOT NULL DEFAULT 0,
    started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME NULL,
    failure_reason TEXT NULL,
    payload JSON NOT NULL,
    version INT NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_discovery_runs_scope_started (tenant_id, project_id, provider_type, started_at),
    KEY idx_discovery_runs_connection_started (connection_id, started_at),
    KEY idx_discovery_runs_status (status)
);

CREATE TABLE IF NOT EXISTS discovered_resources (
    id CHAR(32) NOT NULL PRIMARY KEY,
    tenant_id VARCHAR(128) NOT NULL,
    project_id VARCHAR(128) NOT NULL,
    service_id VARCHAR(128) NOT NULL,
    environment VARCHAR(64) NOT NULL,
    provider VARCHAR(64) NOT NULL,
    provider_account_id VARCHAR(255) NOT NULL,
    region VARCHAR(128) NOT NULL,
    provider_resource_id VARCHAR(768) NOT NULL,
    provider_resource_key CHAR(64) NOT NULL,
    resource_type VARCHAR(128) NOT NULL,
    display_name VARCHAR(255) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    tags JSON NOT NULL,
    owner VARCHAR(255) NULL,
    configuration JSON NOT NULL,
    health JSON NOT NULL,
    cost JSON NOT NULL,
    discovered_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at DATETIME NULL,
    version INT NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_discovered_resources_provider_key (tenant_id, project_id, provider_resource_key),
    KEY idx_discovered_resources_scope_type (tenant_id, project_id, provider, resource_type),
    KEY idx_discovered_resources_service_env (tenant_id, service_id, environment),
    KEY idx_discovered_resources_status (tenant_id, project_id, status)
);

CREATE TABLE IF NOT EXISTS resource_relationships (
    id CHAR(32) NOT NULL PRIMARY KEY,
    tenant_id VARCHAR(128) NOT NULL,
    project_id VARCHAR(128) NOT NULL,
    source_resource_id VARCHAR(128) NOT NULL,
    target_resource_id VARCHAR(128) NOT NULL,
    relationship_type VARCHAR(128) NOT NULL,
    source VARCHAR(128) NOT NULL,
    confidence DECIMAL(5,4) NOT NULL DEFAULT 0,
    owner_confirmed BOOLEAN NOT NULL DEFAULT FALSE,
    discovered_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version INT NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_resource_relationship_edge (tenant_id, project_id, source_resource_id, target_resource_id, relationship_type),
    KEY idx_resource_relationships_scope_type (tenant_id, project_id, relationship_type)
);

CREATE TABLE IF NOT EXISTS service_resource_mappings (
    id CHAR(32) NOT NULL PRIMARY KEY,
    tenant_id VARCHAR(128) NOT NULL,
    project_id VARCHAR(128) NOT NULL,
    service_id VARCHAR(128) NOT NULL,
    environment VARCHAR(64) NOT NULL,
    resource_id VARCHAR(128) NOT NULL,
    owner VARCHAR(255) NOT NULL,
    mapping_source VARCHAR(64) NOT NULL DEFAULT 'operator',
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    version INT NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_service_resource_mapping (tenant_id, project_id, service_id, environment, resource_id),
    KEY idx_service_resource_mappings_service (tenant_id, project_id, service_id, environment)
);

CREATE TABLE IF NOT EXISTS service_readiness_scores (
    id CHAR(32) NOT NULL PRIMARY KEY,
    tenant_id VARCHAR(128) NOT NULL,
    project_id VARCHAR(128) NOT NULL,
    service_id VARCHAR(128) NOT NULL,
    environment VARCHAR(64) NOT NULL,
    readiness_state VARCHAR(32) NOT NULL DEFAULT 'DRAFT',
    overall_score DECIMAL(5,4) NOT NULL DEFAULT 0,
    scores JSON NOT NULL,
    version INT NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_service_readiness_scope (tenant_id, project_id, service_id, environment),
    KEY idx_service_readiness_state (tenant_id, project_id, readiness_state)
);

CREATE TABLE IF NOT EXISTS cloud_audit_events (
    id CHAR(32) NOT NULL PRIMARY KEY,
    tenant_id VARCHAR(128) NOT NULL,
    project_id VARCHAR(128) NOT NULL,
    actor VARCHAR(255) NOT NULL,
    action VARCHAR(128) NOT NULL,
    resource_type VARCHAR(128) NOT NULL,
    resource_id VARCHAR(255) NOT NULL,
    payload JSON NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_cloud_audit_scope_created (tenant_id, project_id, created_at),
    KEY idx_cloud_audit_resource_action (resource_type, resource_id, action)
);
