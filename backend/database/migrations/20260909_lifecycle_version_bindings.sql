-- Exact immutable lifecycle bindings. Nullable columns preserve legacy history,
-- but unbound rows are never eligible for current readiness or status.
ALTER TABLE actions
    ADD COLUMN recommendation_id CHAR(32) NULL AFTER incident_id,
    ADD COLUMN resolution_plan_id CHAR(32) NULL AFTER recommendation_id,
    ADD COLUMN plan_fingerprint VARCHAR(71) NULL AFTER resolution_plan_id,
    ADD COLUMN approval_id CHAR(32) NULL AFTER plan_fingerprint,
    ADD KEY idx_actions_lifecycle_binding
        (tenant_id, incident_id, recommendation_id, resolution_plan_id, approval_id, updated_at);

ALTER TABLE rca_reports
    ADD COLUMN recommendation_id CHAR(32) NULL AFTER incident_id,
    ADD COLUMN resolution_plan_id CHAR(32) NULL AFTER recommendation_id,
    ADD COLUMN plan_fingerprint VARCHAR(71) NULL AFTER resolution_plan_id,
    ADD COLUMN approval_id CHAR(32) NULL AFTER plan_fingerprint,
    ADD COLUMN remediation_action_id CHAR(32) NULL AFTER approval_id,
    ADD COLUMN validation_checksum VARCHAR(80) NULL AFTER remediation_action_id,
    ADD COLUMN closure_kind VARCHAR(32) NULL AFTER validation_checksum,
    ADD COLUMN closure_status VARCHAR(32) NULL AFTER closure_kind,
    ADD KEY idx_reports_lifecycle_binding
        (tenant_id, incident_id, recommendation_id, resolution_plan_id, approval_id, remediation_action_id, updated_at);
