from __future__ import annotations

import pytest
from common.models import Alert, AlertSeverity, Incident
from context_agent.connectors import GitHubConnector, VectorDBConnector


@pytest.mark.asyncio
async def test_github_connector_reports_explicit_unavailable_state() -> None:
    """GitHubConnector has no real VCS access in this environment (no .git
    checkout, no GitHub API credentials reach it). It must report that
    explicitly rather than returning a fixed, unrelated fake commit that
    would be presented as real deployment history in the RCA evidence panel.
    """
    connector = GitHubConnector()
    alert = Alert(
        source="prometheus",
        name="ApprovalServiceUnavailable",
        service="approval-service",
        severity=AlertSeverity.CRITICAL,
        description="approval-service is unreachable",
    )
    incident = Incident(service="approval-service", severity=AlertSeverity.CRITICAL, title="approval-service unreachable")

    result = await connector.fetch(alert, incident)

    assert result["recent_commits"] == []
    assert result["recent_commits_unavailable"] is True
    assert "sha" not in str(result)
    assert "abc1234" not in str(result)


def test_service_matches_rejects_runbook_tagged_for_a_different_service() -> None:
    """This is the exact case that surfaced a MySQL runbook as "evidence" for
    an approval-service alert: the runbook document declares services=["mysql"],
    which must not match an alert for a different service."""
    connector = VectorDBConnector()
    mysql_runbook = {"kind": "runbook", "services": ["mysql"], "content": "KaiOps MySQL Alerts Table Rows High Runbook"}

    assert connector._service_matches(mysql_runbook, "approval-service") is False
    assert connector._service_matches(mysql_runbook, "mysql") is True


def test_service_matches_still_allows_untagged_runbook() -> None:
    """A runbook with no services field is treated as general-purpose and
    must keep matching every alert, preserving prior behavior for untagged
    documents."""
    connector = VectorDBConnector()
    general_runbook = {"kind": "runbook", "content": "General incident triage checklist"}

    assert connector._service_matches(general_runbook, "approval-service") is True
    assert connector._service_matches(general_runbook, "mysql") is True


def test_assemble_context_runbook_selection_skips_unrelated_service(monkeypatch) -> None:
    """Reproduces the assemble_context runbook lookup directly: given a vector
    match list containing both an unrelated MySQL runbook and no matching
    runbook for the alert's own service, the selected runbook content must not
    be the unrelated one."""
    connector = VectorDBConnector()
    vector_matches = [
        {"kind": "runbook", "services": ["mysql"], "content": "KaiOps MySQL Alerts Table Rows High Runbook"},
        {"kind": "incident", "services": ["approval-service"], "content": "unrelated"},
    ]

    selected = next(
        (
            doc["content"]
            for doc in vector_matches
            if doc["kind"] == "runbook" and connector._service_matches(doc, "approval-service")
        ),
        "",
    )

    assert selected == ""


def test_assemble_context_runbook_selection_finds_matching_runbook() -> None:
    """A runbook correctly tagged for the alert's own service must still be
    selected -- the fix must not suppress genuinely relevant runbooks."""
    connector = VectorDBConnector()
    vector_matches = [
        {"kind": "runbook", "services": ["mysql"], "content": "unrelated mysql runbook"},
        {"kind": "runbook", "services": ["approval-service"], "content": "approval-service runbook"},
    ]

    selected = next(
        (
            doc["content"]
            for doc in vector_matches
            if doc["kind"] == "runbook" and connector._service_matches(doc, "approval-service")
        ),
        "",
    )

    assert selected == "approval-service runbook"


def test_read_metadata_normalizes_singular_service_frontmatter_key(tmp_path: Path) -> None:
    """Runbooks using singular 'service: mysql' frontmatter field must normalize to 'services': ['mysql']."""
    runbook = tmp_path / "mysql-test-runbook.md"
    runbook.write_text(
        "---\nservice: mysql\ntitle: MySQL Test Runbook\n---\n# MySQL Remediation\nSteps...",
        encoding="utf-8",
    )
    connector = VectorDBConnector(rag_root=tmp_path)
    metadata = connector._read_metadata(runbook)

    assert metadata["services"] == ["mysql"]
    assert metadata["title"] == "MySQL Test Runbook"


def test_load_full_document_normalizes_singular_service_frontmatter_key(tmp_path: Path) -> None:
    runbooks_dir = tmp_path / "runbooks"
    runbooks_dir.mkdir(parents=True, exist_ok=True)
    runbook = runbooks_dir / "mysql-alerts-test.md"
    runbook.write_text(
        "---\nservice: mysql\ntitle: MySQL Alerts Test\n---\n# Content\nBody text...",
        encoding="utf-8",
    )
    connector = VectorDBConnector(rag_root=tmp_path)
    document = connector._load_full_document(str(runbook))

    assert document["services"] == ["mysql"]
    assert document["title"] == "MySQL Alerts Test"
