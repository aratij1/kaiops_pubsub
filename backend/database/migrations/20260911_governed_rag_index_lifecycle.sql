ALTER TABLE governed_rag_documents
    ADD COLUMN index_attempts INT NOT NULL DEFAULT 0 AFTER index_status,
    ADD COLUMN index_error TEXT NULL AFTER index_attempts,
    ADD COLUMN index_receipt JSON NULL AFTER index_error,
    ADD COLUMN last_index_attempt_at DATETIME(6) NULL AFTER index_receipt,
    ADD COLUMN next_index_attempt_at DATETIME(6) NULL AFTER last_index_attempt_at,
    ADD KEY ix_governed_rag_next_index_attempt (next_index_attempt_at);
