from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from common.incident_investigation import IncidentInvestigationContract
from common.repository import IncidentRepository
from pydantic import ValidationError


def investigation_payload() -> dict:
    collected_at = datetime.now(UTC)
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
            "context_ready": False,
            "rca_ready": False,
            "resolution_ready": False,
            "approval_ready": False,
            "execution_ready": False,
            "validation_ready": False,
            "closure_ready": False,
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


def test_repository_normalizes_iterative_status_and_authoritative_evidence_uri() -> None:
    expected = investigation_payload()
    expected["context_quality"].update({
        "coverage_score": 0.85,
        "source_coverage_score": 0.375,
        "rca_readiness_score": 0.46,
        "impact_readiness_score": 0.41,
        "rca_ready": False,
        "impact_ready": False,
    })
    evidence = {
        "evidence_id": "metric-1", "source": "prometheus", "service": "payments",
        "uri": "prometheus://query/payments-latency", "freshness": "Fresh",
        "provenance": {
            "primary_source": "prometheus://query/payments-latency",
            "generated_at": expected["context_collected_at"],
        },
    }
    recommendation = {
        "id": str(uuid4()),
        "metadata": {
            "analysis_request_id": expected["analysis_request_id"],
            "rca_version": 1, "rca_status": "insufficient_evidence", "evidence_ids": [],
            "rca_analysis": {"evidence_used": [], "missing_evidence": ["traces"]},
            "iterative_investigation": {
                "investigation_id": expected["investigation_id"],
                "status": "budget_exhausted", "conclusive": False,
            },
            "execution_plan": {
                "plan_id": str(uuid4()), "plan_fingerprint": f"sha256:{'b' * 64}",
                "execution_ready": False, "mutating": False,
                "readiness_blocks": ["diagnostic only"],
            },
        },
    }
    context_snapshot = {
        "snapshot_id": expected["context_snapshot_id"],
        "context_fingerprint": expected["context_fingerprint"],
        "contract_version": expected["context_contract_version"],
        "collected_at": expected["context_collected_at"],
        "expires_at": expected["context_expires_at"],
        "context": {
            "alert": {"service": "payments"},
            "metadata": {
                "context_quality": expected["context_quality"],
                "context_sources": {
                    "metrics": {"status": "fresh", "collected_at": expected["context_collected_at"]},
                    "rag": {"status": "no_matches", "collected_at": expected["context_collected_at"]},
                },
                "context_evidence": {"metrics": [evidence]},
            },
        },
    }

    contract = IncidentRepository.build_incident_investigation_contract(
        tenant_id=expected["tenant_id"], project_id=expected["project_id"],
        incident_id=expected["incident_id"], alert_id=expected["alert_id"],
        recommendation=recommendation, context_snapshot=context_snapshot,
    )

    assert contract["investigation_status"] == "inconclusive"
    assert contract["context_evidence"][0]["citation"] == evidence["uri"]
    assert [source["status"] for source in contract["context_sources"]] == ["completed", "empty"]
    assert contract["context_quality"]["category_coverage"] == 0.375
    assert contract["context_quality"]["rca_readiness_score"] == 0.46
    assert contract["context_quality"]["impact_readiness_score"] == 0.41
    assert contract["execution_ready"] is False
