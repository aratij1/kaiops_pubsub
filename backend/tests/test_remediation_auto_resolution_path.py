from importlib import util
from pathlib import Path

import pytest


def load_remediation_app_module():
    module_path = Path("backend/src/remediation-engine/app.py")
    spec = util.spec_from_file_location("remediation_engine_app", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load remediation-engine app module")
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_resolution_requires_approval_prefers_decision_payload() -> None:
    module = load_remediation_app_module()

    payload = {
        "decision": {"requires_approval": False},
        "recommendation": {
            "id": "22222222-2222-2222-2222-222222222222",
            "incident_id": "11111111-1111-1111-1111-111111111111",
        },
    }

    assert module._resolution_requires_approval(payload) is False


def test_resolution_requires_approval_falls_back_to_metadata() -> None:
    module = load_remediation_app_module()

    payload = {
        "recommendation": {
            "id": "22222222-2222-2222-2222-222222222222",
            "incident_id": "11111111-1111-1111-1111-111111111111",
            "metadata": {
                "orchestration_decision": {
                    "requires_approval": False,
                }
            },
        }
    }

    assert module._resolution_requires_approval(payload) is False


def test_build_auto_approval_includes_policy_metadata() -> None:
    module = load_remediation_app_module()

    payload = {
        "decision": {
            "requires_approval": False,
            "policy_version": "policy-v2",
            "policy_reason": "confidence >= threshold",
        },
        "recommendation": {
            "id": "22222222-2222-2222-2222-222222222222",
            "incident_id": "11111111-1111-1111-1111-111111111111",
            "recommended_action": "restart pod deployment",
        },
    }

    approval = module._build_auto_approval(payload)

    assert approval is not None
    assert str(approval.incident_id) == "11111111-1111-1111-1111-111111111111"
    assert str(approval.recommendation_id) == "22222222-2222-2222-2222-222222222222"
    assert approval.approver == "system-auto-approval"
    assert approval.metadata.get("auto_approved") is True
    assert approval.metadata.get("policy_version") == "policy-v2"
    assert approval.metadata.get("policy_reason") == "confidence >= threshold"


def test_build_auto_approval_returns_none_when_identifiers_missing() -> None:
    module = load_remediation_app_module()

    payload = {
        "decision": {"requires_approval": False},
        "recommendation": {"recommended_action": "restart pod deployment"},
    }

    assert module._build_auto_approval(payload) is None


def test_validate_auto_execution_policy_accepts_well_formed_payload() -> None:
    module = load_remediation_app_module()

    payload = {
        "decision": {"requires_approval": False, "risk_tier": "medium"},
        "recommendation": {
            "id": "22222222-2222-2222-2222-222222222222",
            "incident_id": "11111111-1111-1111-1111-111111111111",
            "confidence": 0.93,
            "metadata": {
                "evidence_ids": ["ev-1"],
                "reasoning": "Rollback selected from runbook and deployment timeline.",
                "runbook_id": "rb-checkout-1",
                "runbook_status": "approved",
                "runbook_match_score": 0.93,
            },
        },
    }

    module._validate_auto_execution_policy(payload)


def test_validate_auto_execution_policy_rejects_missing_evidence() -> None:
    module = load_remediation_app_module()

    payload = {
        "decision": {"requires_approval": False, "risk_tier": "medium"},
        "recommendation": {
            "id": "22222222-2222-2222-2222-222222222222",
            "incident_id": "11111111-1111-1111-1111-111111111111",
            "confidence": 0.93,
            "metadata": {
                "reasoning": "Rollback selected from runbook and deployment timeline.",
            },
        },
    }

    with pytest.raises(module.PolicyViolation):
        module._validate_auto_execution_policy(payload)


def test_validate_auto_execution_policy_rejects_new_or_suspended_runbook() -> None:
    module = load_remediation_app_module()
    payload = {
        "decision": {"requires_approval": False, "risk_tier": "low"},
        "recommendation": {
            "confidence": 0.96,
            "metadata": {
                "evidence_ids": ["ev-1"], "reasoning": "matched evidence",
                "runbook_id": "rb-1", "runbook_status": "suspended", "runbook_match_score": 0.96,
            },
        },
    }
    with pytest.raises(module.PolicyViolation, match="approved, active runbook"):
        module._validate_auto_execution_policy(payload)


def test_dry_run_rejects_destructive_plan_even_after_generic_approval() -> None:
    module = load_remediation_app_module()
    from common.models import Approval, ApprovalDecision
    approval = Approval(
        incident_id="11111111-1111-1111-1111-111111111111",
        recommendation_id="22222222-2222-2222-2222-222222222222",
        decision=ApprovalDecision.APPROVED,
        approver="reviewer",
        metadata={"execution_plan": {"commands": ["rm -rf /"]}},
    )
    reasons = module._unsafe_plan_reasons(approval)
    assert reasons and "filesystem deletion" in reasons[0]


def test_build_policy_blocked_action_returns_structured_skip() -> None:
    module = load_remediation_app_module()

    payload = {
        "recommendation": {
            "id": "22222222-2222-2222-2222-222222222222",
            "incident_id": "11111111-1111-1111-1111-111111111111",
        }
    }

    action = module._build_policy_blocked_action(payload, "auto execution blocked: confidence below threshold")

    assert action is not None
    assert str(action.incident_id) == "11111111-1111-1111-1111-111111111111"
    assert action.action_type == "policy-blocked"
    assert action.status.value == "skipped"
    assert action.metadata.get("policy_blocked") is True
