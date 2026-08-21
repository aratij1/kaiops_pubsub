from common.models import Approval, ApprovalDecision
from remediation_engine import RemediationEngine


def test_build_action_prefers_recommended_commands_for_action_type() -> None:
    approval = Approval(
        incident_id="11111111-1111-1111-1111-111111111111",
        recommendation_id="22222222-2222-2222-2222-222222222222",
        decision=ApprovalDecision.APPROVED,
        approver="sre@example.com",
        comment="Proceed",
        metadata={
            "service": "checkout-api",
            "recommended_action": "Scale service to absorb traffic",
            "recommended_commands": [
                "kubectl scale deployment/checkout-api --replicas=4 -n prod",
            ],
        },
    )

    action = RemediationEngine().build_action(approval)

    assert action.action_type == "scale_deployment"
    assert action.target == "checkout-api"


def test_build_action_rewrites_uuid_target_to_service() -> None:
    approval = Approval(
        incident_id="11111111-1111-1111-1111-111111111111",
        recommendation_id="22222222-2222-2222-2222-222222222222",
        decision=ApprovalDecision.APPROVED,
        approver="sre@example.com",
        comment="Restart service",
        metadata={
            "target": "33333333-3333-4333-9333-333333333333",
            "service": "payments-api",
        },
    )

    action = RemediationEngine().build_action(approval)

    assert action.target == "payments-api"


def test_catalog_docker_restart_is_not_mislabeled_as_rollback() -> None:
    approval = Approval(
        incident_id="11111111-1111-1111-1111-111111111111",
        recommendation_id="22222222-2222-2222-2222-222222222222",
        decision=ApprovalDecision.APPROVED,
        approver="sre@example.com",
        comment="execute exact reviewed plan",
        metadata={
            "service": "kaiops-discovery-mcp",
            "recommended_action": "Restart the kaiops-discovery-mcp service and validate its health.",
            "execution_plan": {
                "commands": [
                    "curl -X POST http://docker-socket-proxy:2375/containers/kaiops_pubsub-discovery-mcp-1/restart?t=30"
                ],
                "validation_commands": ["curl http://discovery-mcp:8000/healthz"],
            },
            "connection_profile": {
                "executor_type": "jenkins",
                "allowed_operations": ["restart_service"],
            },
        },
    )

    action = RemediationEngine().build_action(approval)

    assert action.action_type == "restart_service"
