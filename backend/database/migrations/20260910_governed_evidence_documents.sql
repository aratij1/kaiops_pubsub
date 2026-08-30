CREATE TABLE IF NOT EXISTS evidence_rag_drafts (
    draft_id CHAR(36) NOT NULL, tenant_id VARCHAR(128) NOT NULL,
    project_id VARCHAR(128) NULL, incident_id CHAR(36) NOT NULL,
    alert_id CHAR(36) NOT NULL, analysis_request_id CHAR(36) NOT NULL,
    context_snapshot_id CHAR(36) NOT NULL, context_fingerprint CHAR(64) NOT NULL,
    recommendation_id CHAR(36) NOT NULL, rca_version INT NOT NULL,
    document_kind VARCHAR(32) NOT NULL, document_version INT NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'draft', title VARCHAR(160) NOT NULL,
    content LONGTEXT NOT NULL, content_checksum CHAR(71) NOT NULL,
    evidence_ids JSON NOT NULL, source_uris JSON NOT NULL,
    owner_team VARCHAR(160) NULL, created_by VARCHAR(160) NOT NULL,
    reviewed_by VARCHAR(160) NULL, review_notes TEXT NULL,
    reviewed_at DATETIME(6) NULL, approved_by VARCHAR(160) NULL,
    approved_at DATETIME(6) NULL, indexed_at DATETIME(6) NULL,
    row_version INT NOT NULL DEFAULT 1, created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL, PRIMARY KEY (draft_id),
    UNIQUE KEY uq_evidence_draft_version (tenant_id, alert_id, document_kind, document_version),
    KEY ix_evidence_draft_incident (tenant_id, incident_id, status),
    KEY ix_evidence_draft_alert (tenant_id, alert_id, status),
    KEY ix_evidence_draft_context (tenant_id, context_snapshot_id, recommendation_id)
);

CREATE TABLE IF NOT EXISTS governed_rag_documents (
    document_id CHAR(36) NOT NULL, draft_id CHAR(36) NOT NULL,
    tenant_id VARCHAR(128) NOT NULL, incident_id CHAR(36) NOT NULL,
    alert_id CHAR(36) NOT NULL, context_snapshot_id CHAR(36) NOT NULL,
    context_fingerprint CHAR(64) NOT NULL, recommendation_id CHAR(36) NOT NULL,
    rca_version INT NOT NULL, document_kind VARCHAR(32) NOT NULL,
    document_version INT NOT NULL, title VARCHAR(160) NOT NULL,
    content LONGTEXT NOT NULL, content_checksum CHAR(71) NOT NULL,
    evidence_ids JSON NOT NULL, source_uris JSON NOT NULL,
    corpus_classification VARCHAR(32) NOT NULL, review_status VARCHAR(32) NOT NULL,
    approved_by VARCHAR(160) NOT NULL, approved_at DATETIME(6) NOT NULL,
    index_status VARCHAR(32) NOT NULL DEFAULT 'pending', indexed_at DATETIME(6) NULL,
    created_at DATETIME(6) NOT NULL, PRIMARY KEY (document_id),
    UNIQUE KEY uq_governed_document_version (tenant_id, alert_id, document_kind, document_version),
    UNIQUE KEY uq_governed_document_draft (draft_id),
    KEY ix_governed_rag_retrieval (tenant_id, review_status, index_status, document_kind)
);
