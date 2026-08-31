ALTER TABLE context_snapshots
    ADD COLUMN parent_snapshot_id CHAR(36) NULL AFTER context_fingerprint,
    ADD COLUMN snapshot_stage VARCHAR(32) NOT NULL DEFAULT 'collected' AFTER parent_snapshot_id,
    ADD COLUMN snapshot_version INT NOT NULL DEFAULT 1 AFTER snapshot_stage,
    ADD COLUMN evidence_ids JSON NULL AFTER snapshot_version,
    ADD COLUMN evidence_checksums JSON NULL AFTER evidence_ids,
    ADD KEY ix_context_snapshot_parent (parent_snapshot_id);

UPDATE context_snapshots SET evidence_ids = JSON_ARRAY() WHERE evidence_ids IS NULL;
UPDATE context_snapshots SET evidence_checksums = JSON_OBJECT() WHERE evidence_checksums IS NULL;
ALTER TABLE context_snapshots
    MODIFY evidence_ids JSON NOT NULL,
    MODIFY evidence_checksums JSON NOT NULL;
