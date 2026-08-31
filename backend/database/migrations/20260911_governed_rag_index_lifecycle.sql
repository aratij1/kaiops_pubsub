SET @sql := IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'governed_rag_documents' AND column_name = 'index_attempts') = 0,
    'ALTER TABLE governed_rag_documents ADD COLUMN index_attempts INT NOT NULL DEFAULT 0 AFTER index_status', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'governed_rag_documents' AND column_name = 'index_error') = 0,
    'ALTER TABLE governed_rag_documents ADD COLUMN index_error TEXT NULL AFTER index_attempts', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'governed_rag_documents' AND column_name = 'index_receipt') = 0,
    'ALTER TABLE governed_rag_documents ADD COLUMN index_receipt JSON NULL AFTER index_error', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'governed_rag_documents' AND column_name = 'last_index_attempt_at') = 0,
    'ALTER TABLE governed_rag_documents ADD COLUMN last_index_attempt_at DATETIME(6) NULL AFTER index_receipt', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'governed_rag_documents' AND column_name = 'next_index_attempt_at') = 0,
    'ALTER TABLE governed_rag_documents ADD COLUMN next_index_attempt_at DATETIME(6) NULL AFTER last_index_attempt_at', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := IF((SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema = DATABASE() AND table_name = 'governed_rag_documents' AND index_name = 'ix_governed_rag_next_index_attempt') = 0,
    'ALTER TABLE governed_rag_documents ADD KEY ix_governed_rag_next_index_attempt (next_index_attempt_at)', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
