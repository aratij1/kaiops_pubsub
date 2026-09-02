import pytest
from resolution_agent.catalog import (
    RESOLUTION_CATALOG,
    prepare_resolution_plan,
    register_global_knowledge,
    register_learned_runbooks,
    relevant_resolutions,
)


def test_catalog_contains_exactly_one_thousand_unique_governed_options() -> None:
    assert len(RESOLUTION_CATALOG) == 1000
    assert len({row["id"] for row in RESOLUTION_CATALOG}) == 1000
    assert {row["family"] for row in RESOLUTION_CATALOG} >= {
        "availability",
        "database-contention",
        "security-event",
        "observability-gap",
    }
    assert all(row["requires_evidence"] and row["requires_operator_review"] for row in RESOLUTION_CATALOG)
    assert not any(row["execution_eligible"] for row in RESOLUTION_CATALOG)


def test_matching_prioritizes_issue_family_and_platform() -> None:
    rows = relevant_resolutions(issue="Kubernetes pods are OOMKilled due to memory pressure", service="checkout")
    assert rows
    assert rows[0]["family"] == "memory-pressure"
    assert rows[0]["platform"] == "kubernetes"
    assert rows[0]["relevance"] >= 0.35


def test_global_knowledge_is_review_only_and_cannot_execute() -> None:
    rows = register_global_knowledge(
        tenant_id="tenant-a",
        matches=[
            {
                "title": "Vendor recovery guide",
                "path": "global/runbooks/vendor.md",
                "score": 0.92,
                "preview": "Validate vendor health and fail over.",
            }
        ]
    )
    assert rows[0]["relevance"] == 0.6
    plan = prepare_resolution_plan(
        tenant_id="tenant-a", option_id=rows[0]["id"],
        issue="unknown vendor fault", service="payments",
    )
    assert plan["agent_status"] == "knowledge_candidate_requires_validation"
    assert plan["execution_eligible"] is False
    assert "Do not execute directly" in plan["steps"][0]

    with pytest.raises(ValueError, match="Unknown resolution option"):
        prepare_resolution_plan(
            tenant_id="tenant-b", option_id=rows[0]["id"],
            issue="unknown vendor fault", service="payments",
        )


def test_only_approved_successful_low_risk_learned_runbook_can_self_heal() -> None:
    base = {
        "runbook_id": "11111111-1111-1111-1111-111111111111", "version": 2,
        "approval_status": "approved", "risk_level": "low", "success_count": 1, "failure_count": 0,
        "content": {
            "name": "Recover checkout latency", "service_scope": ["checkout"],
            "prerequisites": ["Confirm latency signature"], "diagnostic_steps": ["Check p99 latency"],
            "remediation_steps": ["Restart the confirmed unhealthy checkout replica"],
            "validation_steps": ["Confirm p99 is within SLO"], "rollback_steps": ["Restore prior replica"],
        },
    }
    rows = register_learned_runbooks(tenant_id="tenant-a", runbooks=[base], issue="checkout p99 latency", service="checkout")
    assert rows[0]["self_heal_eligible"] is True
    plan = prepare_resolution_plan(tenant_id="tenant-a", option_id=rows[0]["id"], issue="latency", service="checkout")
    assert plan["agent_status"] == "self_heal_candidate"
    assert plan["execution_eligible"] is True

    unsafe = {**base, "runbook_id": "22222222-2222-2222-2222-222222222222", "failure_count": 1}
    blocked = register_learned_runbooks(tenant_id="tenant-a", runbooks=[unsafe], issue="checkout latency", service="checkout")
    assert blocked[0]["self_heal_eligible"] is False
