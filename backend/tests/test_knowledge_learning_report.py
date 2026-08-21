import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from common.database import LearningAuditRecord, RunbookOutcomeRecord


def load_module():
    name = "knowledge_development_worker_app_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, Path("backend/src/knowledge-development-worker/app.py"))
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def digest(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


@pytest.mark.asyncio
async def test_learning_report_is_tenant_scoped_and_verifies_audit_hashes(sqlite_session_factory) -> None:
    module = load_module()
    module.app.state.session_factory = sqlite_session_factory
    tenant_a_runbook = uuid4()
    tenant_b_runbook = uuid4()
    valid_payload = {"incident_id": "incident-a", "successful": True}
    invalid_payload = {"incident_id": "incident-a", "successful": False}

    async with sqlite_session_factory() as session:
        session.add_all([
            RunbookOutcomeRecord(tenant_id="tenant-a", incident_id="incident-a", runbook_id=tenant_a_runbook, runbook_version=1, reviewed=True, successful=True, validation={"passed": True}),
            RunbookOutcomeRecord(tenant_id="tenant-b", incident_id="incident-b", runbook_id=tenant_b_runbook, runbook_version=2, reviewed=False, successful=False, validation={"passed": False}),
            LearningAuditRecord(sequence_id=1, tenant_id="tenant-a", actor="reviewer-a", action="runbook.execution.recorded", resource_type="runbook", resource_id=str(tenant_a_runbook), payload=valid_payload, payload_sha256=digest(valid_payload)),
            LearningAuditRecord(sequence_id=2, tenant_id="tenant-a", actor="reviewer-a", action="runbook.execution.recorded", resource_type="runbook", resource_id=str(tenant_a_runbook), payload=invalid_payload, payload_sha256="0" * 64),
            LearningAuditRecord(sequence_id=3, tenant_id="tenant-b", actor="reviewer-b", action="runbook.execution.recorded", resource_type="runbook", resource_id=str(tenant_b_runbook), payload={"incident_id": "incident-b"}, payload_sha256="0" * 64),
        ])
        await session.commit()

    result = await module.report(tenant_id="tenant-a")

    assert result["outcome_summary"] == {"total": 1, "reviewed": 1, "successful": 1, "failed": 0, "success_rate": 1.0}
    assert [row["incident_id"] for row in result["outcomes"]] == ["incident-a"]
    assert {row["hash_verified"] for row in result["learning_audit"]} == {True, False}
    assert all(row["actor"] == "reviewer-a" for row in result["learning_audit"])
