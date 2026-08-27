from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from common.incident_investigation import IncidentInvestigationContract


def investigation_payload() -> dict:
    collected_at = datetime.now(timezone.utc)
    return {
        "contract_version": "kaiops.incident-investigation.v1",
        "tenant_id": "tenant-a",
        "project_id": "project-a",
        "incident_id": uuid4(),
        "alert_id": uuid4(),
        "analysis_request_id": uuid4(),
        "context_snapshot_id": uuid4(),
        "context_fingerprint": "a" * 64,
        "context_contract_version": "kaiops.context.v1",
        "context_collected_at": collected_at,
        "context_expires_at": collected_at + timedelta(minutes=15),
        "context_quality": {
            "evidence_count": 0,
            "category_coverage": 0,
            "freshness_score": 0,
            "provenance_score": 0,
            "independent_source_count": 0,
            "direct_observation_count": 0,
            "valid": False,
            "blocking_reasons": ["no_current_observations"],
        },
        "context_sources": [],
        "context_evidence": [],
        "investigation_id": uuid4(),
        "investigation_status": "inconclusive",
        "investigation_conclusive": False,
        "rca_version": 1,
        "rca_status": "insufficient_evidence",
        "accepted_evidence_ids": [],
        "missing_evidence": ["service_telemetry"],
        "conflicting_evidence": [],
        "recommendation_id": None,
        "resolution_plan_id": None,
        "plan_fingerprint": None,
        "execution_ready": False,
        "readiness_blocks": ["insufficient_evidence"],
        "approval_status": "not_ready",
        "remediation_status": "not_started",
        "validation_status": "not_started",
        "readiness": {
            "investigation_ready": False,
            "rca_ready": False,
            "resolution_ready": False,
            "execution_ready": False,
            "blocking_reasons": ["insufficient_evidence"],
        },
    }


def test_accepts_explicit_inconclusive_investigation() -> None:
    contract = IncidentInvestigationContract.model_validate(investigation_payload())
    assert contract.rca_status == "insufficient_evidence"
    assert contract.execution_ready is False


@pytest.mark.parametrize("mutation", ["extra", "foreign_evidence", "contradictory_execution", "expired"])
def test_rejects_invalid_cross_stage_contract(mutation: str) -> None:
    payload = deepcopy(investigation_payload())
    if mutation == "extra":
        payload["undeclared"] = True
    elif mutation == "foreign_evidence":
        payload["accepted_evidence_ids"] = ["evidence-not-in-snapshot"]
    elif mutation == "contradictory_execution":
        payload["execution_ready"] = True
    else:
        payload["context_expires_at"] = payload["context_collected_at"]

    with pytest.raises(ValidationError):
        IncidentInvestigationContract.model_validate(payload)
