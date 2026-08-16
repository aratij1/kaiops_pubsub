from importlib import util
from pathlib import Path

import pytest
from common.models import Approval, ApprovalDecision


def load_remediation_app_module():
    module_path = Path("backend/src/remediation-engine/app.py")
    spec = util.spec_from_file_location("remediation_engine_app", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load remediation-engine app module")
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_live_execution_rejects_incomplete_jenkins_connector() -> None:
    module = load_remediation_app_module()
    approval = Approval(
        incident_id="11111111-1111-1111-1111-111111111111",
        recommendation_id="22222222-2222-2222-2222-222222222222",
        decision=ApprovalDecision.APPROVED,
        approver="sre-user",
        comment="rollback deployment",
    )
    action = module.engine.build_action(approval)

    with pytest.raises(module.HTTPException, match="Jenkins connector is incomplete") as exc_info:
        module._require_live_executor_configuration(action)

    assert exc_info.value.status_code == 409


def test_live_execution_accepts_complete_jenkins_connector() -> None:
    module = load_remediation_app_module()
    approval = Approval(
        incident_id="11111111-1111-1111-1111-111111111111",
        recommendation_id="22222222-2222-2222-2222-222222222222",
        decision=ApprovalDecision.APPROVED,
        approver="sre-user",
        comment="rollback deployment",
        metadata={
            "connection_profile": {
                "executor_type": "jenkins",
                "endpoint_url": "http://jenkins:8080",
                "job_name": "kaiops-auto-remediation",
                "credential_ref": "vault://kaiops/local/jenkins#api-token",
            }
        },
    )
    action = module.engine.build_action(approval)

    module._require_live_executor_configuration(action)


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


def test_resolution_requires_approval_auto_completes_when_both_confidences_meet_threshold() -> None:
    """Arch's auto-completion rule: RCA confidence and resolution confidence
    both >= threshold (default 0.70) skips manual approval, even overriding a
    severity-based decision that would otherwise require it."""
    module = load_remediation_app_module()

    payload = {
        "decision": {"requires_approval": True},
        "recommendation": {
            "id": "22222222-2222-2222-2222-222222222222",
            "incident_id": "11111111-1111-1111-1111-111111111111",
            "confidence": 0.80,
            "metadata": {"rca_analysis": {"confidence_score": 0.85}},
        },
    }

    assert module._resolution_requires_approval(payload) is False


def test_resolution_requires_approval_keeps_existing_flow_when_resolution_confidence_below_threshold() -> None:
    module = load_remediation_app_module()

    payload = {
        "decision": {"requires_approval": True},
        "recommendation": {
            "id": "22222222-2222-2222-2222-222222222222",
            "incident_id": "11111111-1111-1111-1111-111111111111",
            "confidence": 0.60,
            "metadata": {"rca_analysis": {"confidence_score": 0.85}},
        },
    }

    assert module._resolution_requires_approval(payload) is True


def test_resolution_requires_approval_keeps_existing_flow_when_rca_confidence_below_threshold() -> None:
    module = load_remediation_app_module()

    payload = {
        "decision": {"requires_approval": False},
        "recommendation": {
            "id": "22222222-2222-2222-2222-222222222222",
            "incident_id": "11111111-1111-1111-1111-111111111111",
            "confidence": 0.90,
            "metadata": {"rca_analysis": {"confidence_score": 0.55}},
        },
    }

    # Neither confidence clears the threshold as a pair, so this falls through
    # to the existing decision payload unchanged (still honors decision=False here).
    assert module._resolution_requires_approval(payload) is False


def test_resolution_requires_approval_threshold_is_configurable() -> None:
    module = load_remediation_app_module()
    original_threshold = module.settings.rca_resolution_auto_complete_threshold
    try:
        module.settings.rca_resolution_auto_complete_threshold = 0.95
        payload = {
            "decision": {"requires_approval": True},
            "recommendation": {
                "id": "22222222-2222-2222-2222-222222222222",
                "incident_id": "11111111-1111-1111-1111-111111111111",
                "confidence": 0.80,
                "metadata": {"rca_analysis": {"confidence_score": 0.85}},
            },
        }
        # Same 0.80/0.85 confidences that auto-completed against the 0.70
        # default no longer clear a raised 0.95 threshold, so the existing
        # (severity-mandated) approval flow applies.
        assert module._resolution_requires_approval(payload) is True
    finally:
        module.settings.rca_resolution_auto_complete_threshold = original_threshold


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


def test_build_auto_approval_preserves_resolution_executor_profile() -> None:
    module = load_remediation_app_module()
    payload = {
        "incident": {"service": "checkout", "environment": "prod", "application": "storefront"},
        "decision": {"requires_approval": False},
        "recommendation": {
            "id": "22222222-2222-2222-2222-222222222222",
            "incident_id": "11111111-1111-1111-1111-111111111111",
            "recommended_action": "restart checkout",
            "metadata": {
                "connection_profile": {
                    "endpoint_url": "https://jenkins.storefront.example",
                    "job_name": "storefront-checkout-remediation",
                    "credential_ref": "vault://storefront/prod/jenkins#token",
                    "namespace": "storefront-prod",
                }
            },
        },
    }

    approval = module._build_auto_approval(payload)

    assert approval is not None
    profile = approval.metadata["connection_profile"]
    assert profile["application"] == "storefront"
    assert profile["service"] == "checkout"
    assert profile["endpoint_url"] == "https://jenkins.storefront.example"
    assert profile["job_name"] == "storefront-checkout-remediation"
    assert profile["credential_ref"] == "vault://storefront/prod/jenkins#token"
    assert profile["namespace"] == "storefront-prod"


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
            "commands": ["kubectl rollout undo deployment/checkout -n prod"],
            "metadata": {
                "evidence_ids": ["ev-1"],
                "reasoning": "Rollback selected from runbook and deployment timeline.",
                "rca_analysis": {"confidence_score": 0.82},
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
                "rca_analysis": {"confidence_score": 0.82},
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
                "rca_analysis": {"confidence_score": 0.96},
                "runbook_id": "rb-1", "runbook_status": "suspended", "runbook_match_score": 0.96,
            },
        },
    }
    with pytest.raises(module.PolicyViolation, match="approved, active runbook"):
        module._validate_auto_execution_policy(payload)


def test_context_and_resolution_scores_at_configured_threshold_allow_auto_execution() -> None:
    module = load_remediation_app_module()
    payload = {
        "context": {"confidence_score": 0.74},
        "recommendation": {
            "confidence": 0.76,
            "commands": ["kubectl rollout restart deployment/api-gateway -n prod"],
            "metadata": {"evidence_ids": ["metric-1"], "reasoning": "Error rate followed the deployment."},
        },
    }
    module._validate_auto_execution_policy(payload)


def test_context_score_below_configured_threshold_blocks_auto_execution() -> None:
    module = load_remediation_app_module()
    payload = {
        "context": {"confidence_score": 0.69},
        "recommendation": {
            "confidence": 0.91,
            "commands": ["kubectl rollout restart deployment/api-gateway -n prod"],
            "metadata": {"evidence_ids": ["metric-1"], "reasoning": "Error rate followed the deployment."},
        },
    }
    with pytest.raises(module.PolicyViolation, match="threshold"):
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


def test_validation_only_plan_is_detected_before_live_execution() -> None:
    module = load_remediation_app_module()
    from common.models import Approval, ApprovalDecision
    approval = Approval(
        incident_id="11111111-1111-1111-1111-111111111111",
        recommendation_id="22222222-2222-2222-2222-222222222222",
        decision=ApprovalDecision.APPROVED,
        approver="reviewer",
        metadata={"execution_plan": {"scripts": ["sh scripts/remediation/check.sh --dry-run true"]}},
    )

    assert module._plan_is_validation_only(approval) is True


def test_live_plan_is_not_misclassified_as_validation_only() -> None:
    module = load_remediation_app_module()
    from common.models import Approval, ApprovalDecision
    approval = Approval(
        incident_id="11111111-1111-1111-1111-111111111111",
        recommendation_id="22222222-2222-2222-2222-222222222222",
        decision=ApprovalDecision.APPROVED,
        approver="reviewer",
        metadata={"execution_plan": {"scripts": ["sh scripts/remediation/restart.sh --dry-run false"]}},
    )

    assert module._plan_is_validation_only(approval) is False


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
