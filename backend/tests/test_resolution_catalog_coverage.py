import pytest
from resolution_agent.catalog import (
    RESOLUTION_CATALOG,
    prepare_resolution_plan,
    register_global_knowledge,
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
