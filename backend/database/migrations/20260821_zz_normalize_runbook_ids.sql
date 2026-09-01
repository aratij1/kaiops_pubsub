-- SQLAlchemy's portable UUID type stores UUIDs as 32 hexadecimal characters
-- on MySQL. Normalize the raw governance tables to that same representation
-- so ORM lookups and approval joins address the same immutable runbook.

SET FOREIGN_KEY_CHECKS = 0;

UPDATE runbooks SET runbook_id = REPLACE(runbook_id, '-', '');
UPDATE runbook_versions SET runbook_id = REPLACE(runbook_id, '-', '');
UPDATE runbook_parameters SET runbook_id = REPLACE(runbook_id, '-', '');
UPDATE runbook_approvals SET runbook_id = REPLACE(runbook_id, '-', '');
UPDATE runbook_execution_history SET runbook_id = REPLACE(runbook_id, '-', '');
UPDATE runbook_outcomes SET runbook_id = REPLACE(runbook_id, '-', '');

SET FOREIGN_KEY_CHECKS = 1;
