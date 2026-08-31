ALTER TABLE context_enrichment_jobs
  ADD COLUMN lease_owner VARCHAR(255) NULL AFTER available_at,
  ADD COLUMN lease_expires_at DATETIME(6) NULL AFTER lease_owner,
  ADD KEY idx_context_enrichment_job_claim
    (status, available_at, lease_expires_at, created_at);
