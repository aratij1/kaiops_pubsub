-- Continuous-learning and immutable runbook governance (MySQL 8+ only).
CREATE TABLE IF NOT EXISTS incident_evidence (
    id CHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(128) NOT NULL,
    incident_id VARCHAR(128) NOT NULL,
    issue_signature CHAR(64) NOT NULL,
    service VARCHAR(255) NOT NULL,
    environment VARCHAR(64) NOT NULL,
    alert_type VARCHAR(255) NOT NULL,
    evidence JSON NOT NULL,
    reviewed BOOLEAN NOT NULL DEFAULT FALSE,
    collected_at DATETIME(6) NOT NULL,
    UNIQUE KEY uq_incident_evidence_tenant_incident (tenant_id, incident_id),
    KEY idx_incident_evidence_signature (tenant_id, issue_signature, collected_at)
);

CREATE TABLE IF NOT EXISTS failure_patterns (
    pattern_id CHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(128) NOT NULL,
    issue_signature CHAR(64) NOT NULL,
    service VARCHAR(255) NOT NULL,
    environment VARCHAR(64) NOT NULL,
    analysis JSON NOT NULL,
    confidence DECIMAL(5,4) NOT NULL,
    analyzed_at DATETIME(6) NOT NULL,
    UNIQUE KEY uq_failure_pattern_signature (tenant_id, issue_signature),
    CONSTRAINT chk_failure_pattern_confidence CHECK (confidence BETWEEN 0 AND 1)
);

CREATE TABLE IF NOT EXISTS runbook_versions (
    runbook_id CHAR(36) NOT NULL,
    tenant_id VARCHAR(128) NOT NULL,
    version INT UNSIGNED NOT NULL,
    issue_signature CHAR(64) NOT NULL,
    approval_status ENUM('draft','approved','suspended','retired') NOT NULL DEFAULT 'draft',
    owner VARCHAR(255) NOT NULL,
    risk_level VARCHAR(32) NOT NULL,
    required_approval VARCHAR(32) NOT NULL,
    content JSON NOT NULL,
    success_count INT UNSIGNED NOT NULL DEFAULT 0,
    failure_count INT UNSIGNED NOT NULL DEFAULT 0,
    approved_by VARCHAR(255),
    approved_at DATETIME(6),
    last_validated_at DATETIME(6),
    created_at DATETIME(6) NOT NULL,
    PRIMARY KEY (runbook_id, version),
    KEY idx_runbook_match (tenant_id, issue_signature, approval_status),
    CONSTRAINT chk_runbook_approval_actor CHECK (approval_status <> 'approved' OR (approved_by IS NOT NULL AND approved_at IS NOT NULL))
);

-- Append-only ledger. UPDATE/DELETE are denied by application RBAC and DB grants.
CREATE TABLE IF NOT EXISTS learning_audit_log (
    sequence_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    event_id CHAR(36) NOT NULL UNIQUE,
    tenant_id VARCHAR(128) NOT NULL,
    actor VARCHAR(255) NOT NULL,
    action VARCHAR(128) NOT NULL,
    resource_type VARCHAR(64) NOT NULL,
    resource_id VARCHAR(128) NOT NULL,
    payload JSON NOT NULL,
    payload_sha256 CHAR(64) NOT NULL,
    occurred_at DATETIME(6) NOT NULL,
    KEY idx_learning_audit_resource (tenant_id, resource_type, resource_id, sequence_id)
);

CREATE TABLE IF NOT EXISTS runbook_outcomes (
    outcome_id CHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(128) NOT NULL,
    incident_id VARCHAR(128) NOT NULL,
    runbook_id CHAR(36) NOT NULL,
    runbook_version INT UNSIGNED NOT NULL,
    reviewed BOOLEAN NOT NULL DEFAULT FALSE,
    successful BOOLEAN NOT NULL,
    validation JSON NOT NULL,
    created_at DATETIME(6) NOT NULL,
    UNIQUE KEY uq_runbook_outcome_incident (tenant_id, incident_id, runbook_id, runbook_version),
    CONSTRAINT fk_outcome_runbook FOREIGN KEY (runbook_id, runbook_version) REFERENCES runbook_versions(runbook_id, version)
);
