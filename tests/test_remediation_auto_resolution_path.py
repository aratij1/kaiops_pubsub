from importlib import util
from pathlib import Path


def load_remediation_app_module():
    module_path = Path("services/remediation-engine/app.py")
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
