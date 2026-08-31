-- Seed the immutable, globally governed executable catalog. Tenant-specific
-- versions override these rows at lookup time; execution never trusts the RAG
-- document alone.

INSERT INTO runbooks (runbook_id, tenant_id, slug, owner, service, alert_family)
VALUES
  ('5747665d13ac46b09d21f45907f75a96', 'global', 'kaiops-service-down-playbook', 'kaiops-platform-sre', 'api-gateway', 'availability'),
  ('020a0cbfa6224fc3b41b8d02126f6852', 'global', 'kaiops-high-latency-playbook', 'kaiops-platform-sre', 'api-gateway', 'latency'),
  ('9e19e6433a8d4384934924b2890c6569', 'global', 'kaiops-low-throughput-playbook', 'kaiops-platform-sre', 'api-gateway', 'throughput'),
  ('7df50cc542e94496b2014065a8404799', 'global', 'kaiops-mysql-alert-table-growth-playbook', 'kaiops-platform-sre', 'mysql', 'database-growth'),
  ('04b1247f7c454ae7b0d4ff6fa80432c0', 'global', 'etl-data-quality-rejected-rows-playbook', 'kaiops-platform-sre', 'etl', 'data-quality'),
  ('04da83e9822b419eabb9daf5f569cedd', 'global', 'policy-engine-unavailable-playbook', 'kaiops-platform-sre', 'policy-engine', 'availability'),
  ('076e4d2ad0b34bdbbe2767cc25d41702', 'global', 'workflow-execution-failure-playbook', 'kaiops-platform-sre', 'workflow-engine', 'workflow-failure')
ON DUPLICATE KEY UPDATE
  runbook_id = VALUES(runbook_id), tenant_id = VALUES(tenant_id), slug = VALUES(slug), owner = VALUES(owner),
  service = VALUES(service), alert_family = VALUES(alert_family);

INSERT INTO runbook_versions (
  runbook_id, tenant_id, version, issue_signature, approval_status, owner,
  risk_level, required_approval, content, success_count, failure_count,
  approved_by, approved_at, last_validated_at, created_at
)
VALUES
  ('5747665d13ac46b09d21f45907f75a96', 'global', 1, SHA2('kaiops-service-down-playbook', 256), 'approved', 'kaiops-platform-sre', 'high', 'mandatory', JSON_OBJECT('slug', 'kaiops-service-down-playbook', 'status', 'approved', 'checksum_sha256', 'sha256:a44d34783f26059077d4496073e48ad93ee45fa2f99aa2d148aea03caf6e89b1', 'approval_expires_at', '2027-08-21T00:00:00Z', 'source', 'backend/rag/execution/playbooks.json'), 0, 0, 'release-owner', '2026-08-21 00:00:00.000000', '2026-08-21 00:00:00.000000', '2026-08-21 00:00:00.000000'),
  ('020a0cbfa6224fc3b41b8d02126f6852', 'global', 1, SHA2('kaiops-high-latency-playbook', 256), 'approved', 'kaiops-platform-sre', 'medium', 'mandatory', JSON_OBJECT('slug', 'kaiops-high-latency-playbook', 'status', 'approved', 'checksum_sha256', 'sha256:4fbcbd8dc8f8d147bb96bba2827e1c7685dc98419e6e171b95293e21d52ed982', 'approval_expires_at', '2027-08-21T00:00:00Z', 'source', 'backend/rag/execution/playbooks.json'), 0, 0, 'release-owner', '2026-08-21 00:00:00.000000', '2026-08-21 00:00:00.000000', '2026-08-21 00:00:00.000000'),
  ('9e19e6433a8d4384934924b2890c6569', 'global', 1, SHA2('kaiops-low-throughput-playbook', 256), 'approved', 'kaiops-platform-sre', 'medium', 'mandatory', JSON_OBJECT('slug', 'kaiops-low-throughput-playbook', 'status', 'approved', 'checksum_sha256', 'sha256:7c724b07be70c4d5777dc78dce32ecc3e6a1702f8e422f8c4910603fb4f76e76', 'approval_expires_at', '2027-08-21T00:00:00Z', 'source', 'backend/rag/execution/playbooks.json'), 0, 0, 'release-owner', '2026-08-21 00:00:00.000000', '2026-08-21 00:00:00.000000', '2026-08-21 00:00:00.000000'),
  ('7df50cc542e94496b2014065a8404799', 'global', 1, SHA2('kaiops-mysql-alert-table-growth-playbook', 256), 'approved', 'kaiops-platform-sre', 'medium', 'mandatory', JSON_OBJECT('slug', 'kaiops-mysql-alert-table-growth-playbook', 'status', 'approved', 'checksum_sha256', 'sha256:8a325b802afad2956d7d8a5456ab7d31acc04ab0a9d198ec4257b67a69f92ea9', 'approval_expires_at', '2027-08-21T00:00:00Z', 'source', 'backend/rag/execution/playbooks.json'), 0, 0, 'release-owner', '2026-08-21 00:00:00.000000', '2026-08-21 00:00:00.000000', '2026-08-21 00:00:00.000000'),
  ('04b1247f7c454ae7b0d4ff6fa80432c0', 'global', 1, SHA2('etl-data-quality-rejected-rows-playbook', 256), 'approved', 'kaiops-platform-sre', 'medium', 'mandatory', JSON_OBJECT('slug', 'etl-data-quality-rejected-rows-playbook', 'status', 'approved', 'checksum_sha256', 'sha256:191bb04e31bba20fe365c663a43cefc995a7da08a7ec5d5581993da922fc8c7f', 'approval_expires_at', '2027-08-21T00:00:00Z', 'source', 'backend/rag/execution/playbooks.json'), 0, 0, 'release-owner', '2026-08-21 00:00:00.000000', '2026-08-21 00:00:00.000000', '2026-08-21 00:00:00.000000'),
  ('04da83e9822b419eabb9daf5f569cedd', 'global', 1, SHA2('policy-engine-unavailable-playbook', 256), 'approved', 'kaiops-platform-sre', 'high', 'mandatory', JSON_OBJECT('slug', 'policy-engine-unavailable-playbook', 'status', 'approved', 'checksum_sha256', 'sha256:fc2104b337cd3e5137a64c65e00529937952ae206c997d96e116e98744723f5a', 'approval_expires_at', '2027-08-21T00:00:00Z', 'source', 'backend/rag/execution/playbooks.json'), 0, 0, 'release-owner', '2026-08-21 00:00:00.000000', '2026-08-21 00:00:00.000000', '2026-08-21 00:00:00.000000'),
  ('076e4d2ad0b34bdbbe2767cc25d41702', 'global', 1, SHA2('workflow-execution-failure-playbook', 256), 'approved', 'kaiops-platform-sre', 'high', 'mandatory', JSON_OBJECT('slug', 'workflow-execution-failure-playbook', 'status', 'approved', 'checksum_sha256', 'sha256:b6599bc053e5fa36975b00fdeedadc9e6e323ed510be45ce9b886145034e7cc9', 'approval_expires_at', '2027-08-21T00:00:00Z', 'source', 'backend/rag/execution/playbooks.json'), 0, 0, 'release-owner', '2026-08-21 00:00:00.000000', '2026-08-21 00:00:00.000000', '2026-08-21 00:00:00.000000')
ON DUPLICATE KEY UPDATE
  tenant_id = VALUES(tenant_id), approval_status = VALUES(approval_status),
  owner = VALUES(owner), risk_level = VALUES(risk_level),
  required_approval = VALUES(required_approval), content = VALUES(content),
  approved_by = VALUES(approved_by), approved_at = VALUES(approved_at),
  last_validated_at = VALUES(last_validated_at);

INSERT INTO runbook_approvals (
  approval_id, runbook_id, version, status, approver, approver_role, reason, approved_at
)
VALUES
  ('a0000000-0000-4000-8000-000000000001', '5747665d13ac46b09d21f45907f75a96', 1, 'approved', 'release-owner', 'release-owner', 'Immutable catalog approval', '2026-08-21 00:00:00.000000'),
  ('a0000000-0000-4000-8000-000000000002', '020a0cbfa6224fc3b41b8d02126f6852', 1, 'approved', 'release-owner', 'release-owner', 'Immutable catalog approval', '2026-08-21 00:00:00.000000'),
  ('a0000000-0000-4000-8000-000000000003', '9e19e6433a8d4384934924b2890c6569', 1, 'approved', 'release-owner', 'release-owner', 'Immutable catalog approval', '2026-08-21 00:00:00.000000'),
  ('a0000000-0000-4000-8000-000000000004', '7df50cc542e94496b2014065a8404799', 1, 'approved', 'release-owner', 'release-owner', 'Immutable catalog approval', '2026-08-21 00:00:00.000000'),
  ('a0000000-0000-4000-8000-000000000005', '04b1247f7c454ae7b0d4ff6fa80432c0', 1, 'approved', 'release-owner', 'release-owner', 'Immutable catalog approval', '2026-08-21 00:00:00.000000'),
  ('a0000000-0000-4000-8000-000000000006', '04da83e9822b419eabb9daf5f569cedd', 1, 'approved', 'release-owner', 'release-owner', 'Immutable catalog approval', '2026-08-21 00:00:00.000000'),
  ('a0000000-0000-4000-8000-000000000007', '076e4d2ad0b34bdbbe2767cc25d41702', 1, 'approved', 'release-owner', 'release-owner', 'Immutable catalog approval', '2026-08-21 00:00:00.000000')
ON DUPLICATE KEY UPDATE
  status = VALUES(status), approver = VALUES(approver),
  approver_role = VALUES(approver_role), reason = VALUES(reason),
  approved_at = VALUES(approved_at);
