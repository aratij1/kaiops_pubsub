-- Resolution reports contain evidence-backed operational narratives. The
-- Pydantic contract permits those narratives to exceed 255 characters, so the
-- durable schema must not silently impose a narrower contract.
ALTER TABLE rca_reports
    MODIFY COLUMN root_cause TEXT NOT NULL,
    MODIFY COLUMN impact TEXT NOT NULL;
