-- Forward-only immutable RCA provenance binding.
ALTER TABLE incident_investigation_bindings
    ADD COLUMN evidence_ids JSON NULL,
    ADD COLUMN evidence_set_digest VARCHAR(71) NULL,
    ADD COLUMN investigation_id CHAR(32) NULL,
    ADD COLUMN model_version VARCHAR(160) NULL,
    ADD COLUMN prompt_version VARCHAR(160) NULL,
    ADD COLUMN tool_versions JSON NULL,
    ADD COLUMN generated_at DATETIME(6) NULL,
    ADD INDEX ix_investigation_binding_evidence_digest (evidence_set_digest),
    ADD INDEX ix_investigation_binding_investigation (investigation_id);

UPDATE incident_investigation_bindings
SET evidence_ids = JSON_ARRAY(),
    evidence_set_digest = 'sha256:4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945',
    model_version = 'legacy-unavailable',
    prompt_version = 'legacy-unavailable',
    tool_versions = JSON_OBJECT(),
    generated_at = created_at
WHERE evidence_set_digest IS NULL;

ALTER TABLE incident_investigation_bindings
    MODIFY evidence_ids JSON NOT NULL,
    MODIFY evidence_set_digest VARCHAR(71) NOT NULL,
    MODIFY model_version VARCHAR(160) NOT NULL,
    MODIFY prompt_version VARCHAR(160) NOT NULL,
    MODIFY tool_versions JSON NOT NULL,
    MODIFY generated_at DATETIME(6) NOT NULL;
