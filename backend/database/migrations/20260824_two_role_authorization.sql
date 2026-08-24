-- Phase 9: introduce the canonical two-role model without deleting or
-- rewriting historical role assignments.
INSERT INTO roles (name, description, is_system_role, created_at, updated_at)
SELECT 'ADMIN', 'Platform administration and governance', TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
WHERE NOT EXISTS (SELECT 1 FROM roles WHERE name = 'ADMIN');

INSERT INTO roles (name, description, is_system_role, created_at, updated_at)
SELECT 'HITL_APPROVER', 'Human review, approval, modification, and escalation', TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
WHERE NOT EXISTS (SELECT 1 FROM roles WHERE name = 'HITL_APPROVER');

-- Compatibility mappings are enforced in common.authorization:
-- Administrator -> ADMIN; L2/L3 -> HITL_APPROVER.
-- Executive and L1 Operator intentionally retain no operational write role.
