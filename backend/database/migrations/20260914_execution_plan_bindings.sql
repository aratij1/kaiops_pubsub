-- Bind canonical execution plans to the exact RCA and operator selection.
ALTER TABLE execution_plans
    ADD COLUMN rca_version INTEGER NULL AFTER recommendation_id,
    ADD COLUMN context_snapshot_id CHAR(36) NULL AFTER rca_version,
    ADD COLUMN context_fingerprint CHAR(64) NULL AFTER context_snapshot_id,
    ADD COLUMN resolution_selection_id CHAR(36) NULL AFTER context_fingerprint,
    ADD COLUMN policy_version VARCHAR(64) NULL AFTER resolution_selection_id,
    ADD KEY idx_execution_plan_binding (
        tenant_id, incident_id, recommendation_id, rca_version, resolution_selection_id
    );
