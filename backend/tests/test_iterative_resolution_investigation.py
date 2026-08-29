from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from ai_workbench_common.models import Context
from common.models import Alert, AlertSeverity, Incident
from resolution_agent.investigation import IterativeInvestigator, ReadOnlyDiscoveryClient


class FakeDiscoveryClient:
    def __init__(self, results: dict[str, list[dict[str, Any]]]) -> None:
        self.results = results
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((tool_name, arguments))
        return {"tool": tool_name, "evidence": self.results.get(tool_name, [])}


def test_investigation_honors_configured_step_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESOLUTION_INVESTIGATION_MAX_STEPS", "5")

    assert IterativeInvestigator(client=FakeDiscoveryClient({})).max_steps == 5


def make_context(*, hypotheses: list[dict[str, Any]] | None = None) -> Context:
    alert = Alert(
        tenant_id="tenant-a",
        source="prometheus",
        name="CheckoutPoolTimeout",
        service="checkout",
        severity=AlertSeverity.HIGH,
        description="checkout connection pool timeout after deployment",
    )
    incident = Incident(tenant_id="tenant-a", service="checkout", severity=AlertSeverity.HIGH, title=alert.name)
    return Context(
        tenant_id=alert.tenant_id,
        incident_id=incident.id,
        alert=alert,
        metadata={
            "discovery_report": {"report": {"hypotheses": hypotheses or []}},
            "context_evidence": {},
        },
    )


@pytest.mark.asyncio
async def test_investigation_queries_missing_sources_and_returns_inconclusive() -> None:
    client = FakeDiscoveryClient({})
    investigator = IterativeInvestigator(client=client)
    investigator.max_steps = 2

    report = await investigator.investigate(make_context())

    assert report["status"] == "budget_exhausted"
    assert report["conclusive"] is False
    assert report["steps_used"] == 2
    assert len(client.calls) == 2
    assert all(name in ReadOnlyDiscoveryClient.ALLOWED_TOOLS for name, _ in client.calls)
    assert report["next_evidence"]
    assert report["outcome"] == "INSUFFICIENT_EVIDENCE"
    assert report["rca_result"]["root_cause"] is None
    assert report["investigation_plan"]["questions_to_answer"]
    assert report["investigation_plan"]["recommended_tool_calls"]
    assert report["correlation_id"]
    assert all("start_time" in arguments and "end_time" in arguments for _, arguments in client.calls)


def test_generic_change_candidate_does_not_override_latency_evidence_priority() -> None:
    context = make_context(hypotheses=[{"cause": "A recent configuration change affected checkout"}])
    context.alert.name = "CheckoutLatencyHigh"
    context.alert.description = "checkout p99 latency is above threshold"
    investigator = IterativeInvestigator(client=FakeDiscoveryClient({}))

    selection = investigator._select_tool(
        context=context,
        evidence=[],
        hypotheses=investigator._initial_hypotheses(context),
        tool_counts={},
    )

    assert selection is not None
    tool_name, arguments = selection
    assert tool_name == "logs.search"
    assert datetime.fromisoformat(arguments["start_time"]).tzinfo == UTC
    assert datetime.fromisoformat(arguments["end_time"]) > datetime.fromisoformat(arguments["start_time"])


@pytest.mark.asyncio
async def test_keyword_overlap_alone_cannot_confirm_a_hypothesis() -> None:
    hypothesis = {"cause": "checkout connection pool exhaustion", "confidence": 0.6}
    client = FakeDiscoveryClient({
        "code.search": [{
            "evidence_id": "CODE-POOL",
            "source": "code",
            "snippet": "checkout connection pool exhaustion occurs when pool size is two",
        }],
        "logs.search": [{
            "evidence_id": "LOG-POOL",
            "source": "log",
            "snippet": "checkout connection pool exhaustion timeout",
        }],
    })
    investigator = IterativeInvestigator(client=client)
    investigator.max_steps = 4

    report = await investigator.investigate(make_context(hypotheses=[hypothesis]))

    assert report["status"] == "budget_exhausted"
    assert report["conclusive"] is False
    assert report["steps_used"] == 4
    assert report["conclusion"]["confidence"] < investigator.conclusive_threshold
    tested = next(row for row in report["hypotheses"] if row["claim"] == hypothesis["cause"])
    collected_ids = {row["evidence_id"] for row in report["evidence"]}
    assert {"CODE-POOL", "LOG-POOL"} <= collected_ids, (client.calls, report["steps"])
    assert tested["status"] != "confirmed"
    assert report["rca_result"]["outcome"] == "INSUFFICIENT_EVIDENCE"
    assert report["rca_result"]["root_cause"] is None
    assert len(report["typed_hypotheses"]) >= 3


@pytest.mark.asyncio
async def test_alert_label_never_becomes_confirmed_root_cause_without_corroboration() -> None:
    context = make_context(hypotheses=[{
        "cause": "checkout connection pool timeout after deployment",
        "confidence": 0.99,
    }])
    investigator = IterativeInvestigator(client=FakeDiscoveryClient({}))
    investigator.max_steps = 1

    report = await investigator.investigate(context)

    assert report["conclusive"] is False
    assert report["rca_result"]["root_cause"] is None
    assert report["rca_result"]["outcome"] == "INSUFFICIENT_EVIDENCE"


@pytest.mark.asyncio
async def test_conflicting_operational_evidence_is_surfaced_and_blocks_root_cause() -> None:
    hypothesis = {"cause": "checkout connection pool exhaustion", "confidence": 0.8}
    client = FakeDiscoveryClient({
        "changes.search": [{
            "evidence_id": "LOG-CONTRADICTION",
            "source": "log",
            "snippet": "checkout connection pool healthy and normal",
            "timestamp": "2026-08-20T09:59:30Z",
        }],
    })
    investigator = IterativeInvestigator(client=client)
    investigator.max_steps = 1

    report = await investigator.investigate(make_context(hypotheses=[hypothesis]))

    assert report["rca_result"]["outcome"] == "CONFLICTING_EVIDENCE"
    assert report["rca_result"]["root_cause"] is None
    assert "LOG-CONTRADICTION" in report["rca_result"]["contradicting_evidence_ids"]
    assert "unresolved_contradicting_evidence" in report["evidence_graph"]["data_gaps"]


@pytest.mark.asyncio
async def test_discovery_client_rejects_mutating_or_unknown_tools() -> None:
    client = ReadOnlyDiscoveryClient()

    with pytest.raises(ValueError, match="not read-only"):
        await client.call("kubectl.restart", {"service": "checkout"})


@pytest.mark.asyncio
async def test_investigation_emits_durable_events_in_order() -> None:
    events: list[tuple[str, dict[str, Any]]] = []
    client = FakeDiscoveryClient({})
    investigator = IterativeInvestigator(client=client)
    investigator.max_steps = 1

    async def persist(event: str, payload: dict[str, Any]) -> None:
        events.append((event, payload))

    report = await investigator.investigate(make_context(), persist=persist)

    assert [event for event, _ in events] == ["started", "step", "completed"]
    assert events[0][1]["investigation_id"] == report["investigation_id"]
    assert events[0][1]["investigation_plan"]["schema_version"] == "kaims.investigation-plan.v1"
    assert events[1][1]["sequence_no"] == 1
    assert events[-1][1]["status"] == "budget_exhausted"
