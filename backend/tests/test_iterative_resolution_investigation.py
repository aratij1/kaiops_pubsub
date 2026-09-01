from __future__ import annotations

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


@pytest.mark.asyncio
async def test_derived_observation_fallback_claim_still_matches_relevant_evidence() -> None:
    # Regression test for a real production bug: when the discovery-agent
    # supplies no upstream hypotheses, the investigator seeds one fallback
    # "derived_observation" hypothesis whose claim is templated as
    # f"Observed signal requiring causal confirmation: {snippet}" (see
    # investigation.py's _revise_hypotheses). The boilerplate prefix words
    # ("observed", "signal", "requiring", "causal", "confirmation") never
    # appear in real evidence text, so before this fix they diluted the
    # token-overlap ratio used to decide whether evidence supports the
    # hypothesis (>=2 overlapping tokens, or >=35% of the claim's tokens).
    # For a snippet with several meaningful tokens (e.g. a JSON fragment
    # naming a real service), one genuinely on-topic, verbatim-matching
    # evidence row only overlapped on 1 of 6+ claim tokens (~17%) and was
    # silently discarded as unsupported -- collapsing confidence to exactly
    # 0.0 even though directly relevant evidence had been collected. This
    # previously produced real 0% RCA Confidence for alerts like the
    # payment-service/ecommerce-platform test alerts seen in production.
    # The fix tokenizes only the raw diagnostic snippet ("match_text") for
    # matching purposes, not the surrounding template wording, so the
    # comparison judges relevance against the actual signal.
    #
    # The derived_observation fallback is only seeded from evidence already
    # present before any tool call runs (_initial_evidence reads
    # context.metadata["context_evidence"]), matching how it actually
    # triggers in production (context-agent-collected evidence, not
    # evidence.search results) -- so the diagnostic row is placed on the
    # context itself rather than behind a FakeDiscoveryClient tool call.
    context = make_context(hypotheses=[])
    context.metadata["context_evidence"] = {
        "logs": [{
            "evidence_id": "LOG-SERVICE-1",
            "source": "log",
            "source_type": "log",
            "snippet": '"service": "payment-service",',
            "reliability_score": 0.65,
            "freshness_seconds": 30,
        }],
    }
    client = FakeDiscoveryClient({})
    investigator = IterativeInvestigator(client=client)
    investigator.max_steps = 2

    report = await investigator.investigate(context)

    assert report["conclusion"]["confidence"] > 0.0
    assert "LOG-SERVICE-1" in report["conclusion"]["evidence_ids"]
    leading = report["hypotheses"][0]
    assert leading["source"] == "derived_observation"
    assert "LOG-SERVICE-1" in leading["supporting_evidence_ids"]


class ToolFailureDiscoveryClient:
    """Simulates a discovery-mcp deployment that has drifted behind the
    investigation-agent's tool catalog: every allow-listed tool it is asked
    for raises, exactly like the real `/mcp` `tools/call` dispatch did in
    production when a stale container's `_call_tool()`/`mcp()` pairing had
    no case for "changes.search" / "runbooks.search" and fell through to
    `raise ValueError(f"unknown MCP tool: {name}")`.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def call(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(tool_name)
        raise ValueError(f"unknown MCP tool: {tool_name}")


@pytest.mark.asyncio
async def test_confidence_is_legitimately_near_zero_when_every_tool_call_fails() -> None:
    # This reproduces the exact production symptom: a discovery client whose
    # tool calls all fail (as happened when discovery-mcp's live container
    # was stale and rejected "changes.search"/"runbooks.search" as unknown).
    # With zero usable evidence returned, confidence correctly stays at/near
    # 0 -- this is the legitimate "insufficient evidence" case, not itself a
    # bug. The bug was that discovery-mcp silently raised on tools it
    # actually implements; see test_discovery_mcp.py for that regression
    # coverage. This test exists to prove the investigator's OWN behavior is
    # correct here, so nobody "fixes" this near-zero case by loosening the
    # confidence formula.
    hypothesis = {"cause": "checkout connection pool exhaustion", "confidence": 0.6}
    client = ToolFailureDiscoveryClient()
    investigator = IterativeInvestigator(client=client)
    investigator.max_steps = 4

    report = await investigator.investigate(make_context(hypotheses=[hypothesis]))

    assert report["status"] == "budget_exhausted"
    assert report["conclusion"]["confidence"] == 0.0
    assert report["conclusion"]["evidence_ids"] == []
    assert report["evidence_count"] == 0


@pytest.mark.asyncio
async def test_richly_corroborated_evidence_yields_meaningfully_higher_confidence_than_tool_failure() -> None:
    # Comparison case proving the pipeline differentiates real alerts by the
    # evidence they actually have, rather than flattening everything to 0.
    # Multiple independent, fresh, on-topic, non-contradicting sources for
    # the same claim should score well above the all-tool-failure case
    # above.
    hypothesis = {"cause": "checkout connection pool exhaustion", "confidence": 0.6}
    rich_client = FakeDiscoveryClient({
        "logs.search": [{
            "evidence_id": "LOG-POOL-1",
            "source": "log",
            "source_type": "log",
            "snippet": "checkout connection pool exhaustion detected in service logs",
            "reliability_score": 0.9,
            "freshness_seconds": 30,
        }],
        "telemetry.search": [{
            "evidence_id": "METRIC-POOL-1",
            "source": "telemetry",
            "source_type": "telemetry",
            "snippet": "checkout connection pool exhaustion metric spike observed",
            "reliability_score": 0.85,
            "freshness_seconds": 30,
        }],
        "topology.search": [{
            "evidence_id": "TOPO-POOL-1",
            "source": "topology",
            "source_type": "topology",
            "snippet": "checkout connection pool exhaustion correlates with dependent service topology",
            "reliability_score": 0.8,
            "freshness_seconds": 30,
        }],
    })
    rich_investigator = IterativeInvestigator(client=rich_client)
    rich_investigator.max_steps = 8

    starved_client = ToolFailureDiscoveryClient()
    starved_investigator = IterativeInvestigator(client=starved_client)
    starved_investigator.max_steps = 8

    rich_report = await rich_investigator.investigate(make_context(hypotheses=[dict(hypothesis)]))
    starved_report = await starved_investigator.investigate(make_context(hypotheses=[dict(hypothesis)]))

    assert rich_report["conclusion"]["confidence"] > starved_report["conclusion"]["confidence"]
    assert starved_report["conclusion"]["confidence"] == 0.0
    assert rich_report["conclusion"]["confidence"] > 0.3
    assert rich_report["conclusion"]["evidence_ids"]
