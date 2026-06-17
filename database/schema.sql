CREATE TABLE IF NOT EXISTS alerts (
    id UUID PRIMARY KEY,
    source VARCHAR(64) NOT NULL,
    name VARCHAR(255) NOT NULL,
    service VARCHAR(128) NOT NULL,
    environment VARCHAR(64) NOT NULL,
    severity VARCHAR(32) NOT NULL,
    fingerprint VARCHAR(255),
    correlation_id VARCHAR(255),
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS incidents (
    id UUID PRIMARY KEY,
    service VARCHAR(128) NOT NULL,
    environment VARCHAR(64) NOT NULL,
    severity VARCHAR(32) NOT NULL,
    status VARCHAR(64) NOT NULL,
    title VARCHAR(255) NOT NULL,
    ticket_id VARCHAR(128),
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS approvals (
    id UUID PRIMARY KEY,
    incident_id UUID NOT NULL,
    recommendation_id UUID NOT NULL,
    decision VARCHAR(32) NOT NULL,
    approver VARCHAR(255),
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS actions (
    id UUID PRIMARY KEY,
    incident_id UUID NOT NULL,
    action_type VARCHAR(128) NOT NULL,
    target VARCHAR(255) NOT NULL,
    status VARCHAR(32) NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS rca_reports (
    id UUID PRIMARY KEY,
    incident_id UUID NOT NULL,
    root_cause VARCHAR(255) NOT NULL,
    impact VARCHAR(255) NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS knowledge_base (
    id UUID PRIMARY KEY,
    service VARCHAR(128) NOT NULL,
    title VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    embedding_ref VARCHAR(255),
    payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id UUID PRIMARY KEY,
    actor VARCHAR(255) NOT NULL,
    action VARCHAR(255) NOT NULL,
    resource_type VARCHAR(128) NOT NULL,
    resource_id VARCHAR(128) NOT NULL,
    payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_alerts_service_severity ON alerts(service, severity);
CREATE INDEX IF NOT EXISTS idx_incidents_status_severity ON incidents(status, severity);
CREATE INDEX IF NOT EXISTS idx_approvals_incident ON approvals(incident_id);
CREATE INDEX IF NOT EXISTS idx_actions_incident ON actions(incident_id);
CREATE INDEX IF NOT EXISTS idx_rca_reports_incident ON rca_reports(incident_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_resource ON audit_logs(resource_type, resource_id);
