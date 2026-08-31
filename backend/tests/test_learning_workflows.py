from datetime import UTC, datetime

import pytest
from common.continuous_learning import ApprovalRequirement, IncidentEvidence
from common.learning_workflows import Mode01Workflow, Mode02Worker


class Store:
    def __init__(self) -> None:
        self.evidence = []
        self.patterns = []
        self.cursors = {}

    async def save_evidence(self, evidence):
        self.evidence.append(evidence)

    async def list_evidence(self):
        return self.evidence

    async def replace_patterns(self, patterns):
        self.patterns = list(patterns)

    async def list_approved_runbooks(self, *, service):
        return []

    async def record_connector_cursor(self, connector_id, cursor):
        self.cursors[connector_id] = cursor

    async def save_runbook_draft(self, runbook):
        self.runbook_drafts = [*getattr(self, "runbook_drafts", []), runbook]


class Connector:
    connector_id = "jira"
    source_type = "ticket"
    read_only = True

    async def collect(self, *, since_cursor=None):
        return [
            IncidentEvidence(
                incident_id="i-1",
                service="api",
                environment="prod",
                alert_type="latency",
                timestamps=[datetime.now(UTC)],
            )
        ], "next"


@pytest.mark.asyncio
async def test_mode02_collects_and_analyzes() -> None:
    store = Store()
    result = await Mode02Worker(store, [Connector()]).run_once()
    assert result.collected == 1 and len(result.patterns) == 1
    assert store.cursors == {"jira": "next"}


@pytest.mark.asyncio
async def test_mode02_creates_review_only_drafts_from_supported_patterns() -> None:
    class RichConnector:
        connector_id = "history"
        source_type = "incident"
        read_only = True

        async def collect(self, *, since_cursor=None):
            from common.models import EvidenceReference
            refs = [
                EvidenceReference(evidence_id="log-1", source="logs", uri="log://1", summary="error"),
                EvidenceReference(evidence_id="ticket-1", source="jira", uri="jira://1", summary="confirmed"),
            ]
            return [
                IncidentEvidence(incident_id=incident_id, service="api", environment="prod", alert_type="latency", symptoms=["p99 high"], timestamps=[datetime.now(UTC)], logs=[refs[0]], related_tickets=[refs[1]], resolution="restart bounded worker pool", resolution_successful=True, reviewed=True)
                for incident_id in ("i-2", "i-3")
            ], "next"

    store = Store()
    result = await Mode02Worker(store, [RichConnector()]).run_once()
    assert len(result.runbook_drafts) == 1
    assert result.runbook_drafts[0].approval_status.value == "draft"
    assert result.runbook_drafts[0].required_approval == ApprovalRequirement.MANDATORY


@pytest.mark.asyncio
async def test_mode01_abstains_without_independent_root_cause_confidence() -> None:
    async def validate(_evidence):
        return {"confidence": 0.2, "root_cause": "unknown", "risk": "low", "blast_radius": "small"}

    decision = await Mode01Workflow(Store(), validate).resolve(
        IncidentEvidence(incident_id="i-1", service="api", environment="prod", alert_type="latency")
    )
    assert decision.abstained
    assert decision.approval_requirement == ApprovalRequirement.ESCALATE
