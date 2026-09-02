import pytest
from common.incident_command_contract import build_incident_command_workspace
from pydantic import ValidationError


def test_command_workspace_composes_matching_read_models() -> None:
    workspace = build_incident_command_workspace(
        incident_id="incident-1",
        incident={"incident_id": "incident-1", "updated_at": "2026-09-01T10:00:00Z"},
        operations={"incident_id": "incident-1", "lifecycle_version": 7},
    )

    assert workspace.schema_version == "kaiops.incident-command.v2"
    assert workspace.incident["incident_id"] == "incident-1"
    assert workspace.operations["lifecycle_version"] == 7
    assert len(workspace.revision) == 64


def test_command_workspace_owns_evidence_scores_and_binding_blockers() -> None:
    workspace = build_incident_command_workspace(
        incident_id="incident-1",
        incident={"incident_id": "incident-1"},
        operations={
            "incident_id": "incident-1",
            "context": {"snapshot_id": "snapshot-new", "quality": {"quality_score": 0.82}},
            "investigation_workspace": {
                "binding": {"context_snapshot_id": "snapshot-bound"},
                "evidence_summary": {
                    "latest_context_records": 12,
                    "bound_snapshot_records": 10,
                    "rca_bound_records": 5,
                    "traceable_citations": 4,
                    "unresolved_bindings": 1,
                },
                "rca": {"status": "investigating", "conflicting_evidence": ["conflict"]},
                "requirements": [{"status": "collecting"}, {"status": "resolved"}],
                "resolution": {"status": "blocked"},
            },
        },
    )

    assert workspace.evidence.counts.latest_context_records == 12
    assert workspace.evidence.counts.open_requirements == 1
    assert workspace.evidence.counts.open_conflicts == 1
    assert workspace.evidence.binding_consistent is False
    assert workspace.evidence.scores[0].percent == 82
    assert workspace.evidence.scores[1].ratio is not None
    assert workspace.evidence.scores[1].ratio.percent == 80
    assert "RCA_SNAPSHOT_STALE" in workspace.evidence.blockers
    assert "RCA_EVIDENCE_BINDING_UNRESOLVED" in workspace.evidence.blockers
    assert "RCA_NOT_GROUNDED" in workspace.evidence.blockers
    assert "RESOLUTION_NOT_READY" in workspace.evidence.blockers
    assert workspace.evidence.scores[2].status == "blocked"


def test_command_workspace_rejects_mixed_incident_identity() -> None:
    with pytest.raises(ValidationError, match="operations identity does not match"):
        build_incident_command_workspace(
            incident_id="incident-1",
            incident={"incident_id": "incident-1"},
            operations={"incident_id": "incident-2"},
        )


def test_command_workspace_revision_changes_with_lifecycle_version() -> None:
    first = build_incident_command_workspace(
        incident_id="incident-1",
        incident={"incident_id": "incident-1", "updated_at": "2026-09-01T10:00:00Z"},
        operations={"incident_id": "incident-1", "lifecycle_version": 7},
    )
    second = build_incident_command_workspace(
        incident_id="incident-1",
        incident={"incident_id": "incident-1", "updated_at": "2026-09-01T10:00:00Z"},
        operations={"incident_id": "incident-1", "lifecycle_version": 8},
    )

    assert first.revision != second.revision
