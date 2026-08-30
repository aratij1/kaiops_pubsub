ALTER TABLE governed_rag_documents
    MODIFY incident_id CHAR(36) NULL,
    MODIFY alert_id CHAR(36) NULL,
    MODIFY context_snapshot_id CHAR(36) NULL,
    MODIFY context_fingerprint CHAR(64) NULL,
    MODIFY recommendation_id CHAR(36) NULL,
    MODIFY rca_version INT NULL,
    ADD COLUMN source_ref VARCHAR(512) NULL AFTER rca_version,
    ADD COLUMN document_metadata JSON NULL AFTER source_ref;

UPDATE governed_rag_documents SET document_metadata = JSON_OBJECT() WHERE document_metadata IS NULL;
ALTER TABLE governed_rag_documents MODIFY document_metadata JSON NOT NULL;

CREATE TABLE knowledge_rag_drafts (
    draft_id CHAR(36) NOT NULL, tenant_id VARCHAR(128) NOT NULL,
    document_kind VARCHAR(32) NOT NULL, document_version INT NOT NULL,
    source_ref VARCHAR(512) NOT NULL, title VARCHAR(160) NOT NULL,
    content LONGTEXT NOT NULL, content_checksum CHAR(71) NOT NULL,
    metadata_payload JSON NOT NULL, status VARCHAR(32) NOT NULL DEFAULT 'draft',
    created_by VARCHAR(160) NOT NULL, reviewed_by VARCHAR(160) NULL,
    review_notes TEXT NULL, reviewed_at DATETIME(6) NULL,
    approved_by VARCHAR(160) NULL, approved_at DATETIME(6) NULL,
    row_version INT NOT NULL DEFAULT 1, created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL, PRIMARY KEY (draft_id),
    UNIQUE KEY uq_knowledge_rag_draft_version (tenant_id, source_ref, document_kind, document_version),
    KEY ix_knowledge_rag_draft_status (tenant_id, status, updated_at)
);
