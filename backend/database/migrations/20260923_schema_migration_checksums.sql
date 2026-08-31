-- Make migration identity immutable after the runner has backfilled legacy rows.
-- This historical migration was applied by an earlier release and later removed
-- from the working tree. Its checksum is recovered from immutable Git blob
-- 238f8d1dbe9292d1a77d1e39c2b8ef400a6c1a59 rather than invented at upgrade time.
UPDATE schema_migrations
SET checksum_sha256 = 'da1a966b5c6e6fcdb3c91d808dd86ead928c029574ce7cbdd965eb17280373e4'
WHERE filename = '20260916_complete_context_jira_lifecycle.sql'
  AND checksum_sha256 IS NULL;

ALTER TABLE schema_migrations
    MODIFY COLUMN checksum_sha256 CHAR(64) NOT NULL;

CREATE INDEX ix_schema_migrations_applied_at
    ON schema_migrations (applied_at);
