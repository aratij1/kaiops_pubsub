from __future__ import annotations

from datetime import UTC, datetime, timedelta
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
    incident = Incident(
        tenant_id="tenant-a", service="checkout", severity=AlertSeverity.HIGH, title=alert.name,
    )
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


def test_unresolved_latency_investigation_queries_code_before_bulk_inventory() -> None:
    context = make_context()
    context.alert.name = "CheckoutLatencyHigh"
    context.alert.description = "checkout p95 latency is above 2 seconds"
    context.metadata["context_quality"] = {"diagnostic_gaps": ["causal_or_action"]}
    investigator = IterativeInvestigator(client=FakeDiscoveryClient({}))
    evidence = investigator._compile_evidence(context, [{
        "evidence_id": "LOG-IRRELEVANT",
        "source": "log",
        "uri": "log://archive/replayed-alert.json",
        "summary": "historical replayed alert",
        "observed_at": (context.alert.starts_at - timedelta(days=5)).isoformat(),
    }, {
        "evidence_id": "METRIC-LATENCY",
        "source": "telemetry",
        "uri": "prometheus://checkout/latency",
        "summary": "checkout p95 latency is above 2 seconds",
        "observed_at": context.alert.starts_at.isoformat(),
    }])

    selection = investigator._select_tool(
        context=context,
        evidence=evidence,
        hypotheses=investigator._revise_hypotheses([], evidence, context=context),
        tool_counts={"logs.search": 1, "traces.search": 1},
    )

    assert selection is not None
    assert selection[0] == "code.search"


def test_non_operational_log_cannot_seed_hypothesis_and_source_is_accounted() -> None:
    investigator = IterativeInvestigator(client=FakeDiscoveryClient({}))
    context = make_context()
    evidence = investigator._compile_evidence(context, [{
        "evidence_id": "LOG-REPLAY",
        "source": "log",
        "uri": "log://archive/replayed-alert.json",
        "summary": "unrelated historical latency alert",
        "observed_at": (context.alert.starts_at - timedelta(days=5)).isoformat(),
    }, {
        "evidence_id": "METRIC-CURRENT",
        "source": "telemetry",
        "uri": "prometheus://checkout/pool-timeout",
        "summary": "checkout connection pool timeout is active",
        "observed_at": context.alert.starts_at.isoformat(),
    }, {
        "evidence_id": "CODE-REVIEWED",
        "source": "code",
        "uri": "repository://checkout/handler.py#L10",
        "summary": "request handler delegates to the pool",
        "observed_at": context.alert.starts_at.isoformat(),
        "current_operational_evidence": False,
    }])

    hypotheses = investigator._revise_hypotheses([], evidence, context=context)
    assessments = investigator._source_assessments(evidence, hypotheses)

    assert "METRIC-CURRENT" in hypotheses[0]["supporting_evidence_ids"]
    assert "LOG-REPLAY" not in hypotheses[0]["claim"]
    assert assessments["logs"]["disposition"] == "reviewed_no_incident_aligned_evidence"
    assert assessments["code"]["disposition"] == "reviewed_no_causal_match"


def test_root_trace_latency_is_not_mistaken_for_a_causal_mechanism() -> None:
    investigator = IterativeInvestigator(client=FakeDiscoveryClient({}))
    hypothesis = {"claim": "An unhealthy downstream dependency is degrading checkout."}
    trace = {
        "source_type": "trace",
        "metadata": {
            "slowest_spans": [{"service": "checkout", "operation": "GET", "duration_ms": 3200}],
            "dependency_edges": [],
        },
    }

    assert investigator._structured_mechanism_support(hypothesis, trace) is False


def test_healthy_dependency_does_not_contradict_an_observed_latency_signal() -> None:
    investigator = IterativeInvestigator(client=FakeDiscoveryClient({}))
    context = make_context()
    evidence = investigator._compile_evidence(context, [{
        "evidence_id": "METRIC-LATENCY",
        "source": "telemetry",
        "uri": "prometheus://checkout/latency",
        "observed_at": context.alert.starts_at.isoformat(),
        "summary": "checkout latency is above 2 seconds",
    }, {
        "evidence_id": "DEPENDENCY-HEALTHY",
        "source": "dependency",
        "uri": "docker://payments",
        "observed_at": context.alert.starts_at.isoformat(),
        "service": "payments",
        "related_to": "checkout",
        "healthy": True,
        "summary": "checkout dependency payments is healthy",
    }])
    hypotheses = [{
        "hypothesis_id": "observation",
        "claim": "Observed signal requiring causal confirmation: checkout latency is above 2 seconds",
        "source": "derived_observation",
        "confidence": 0.3,
        "supporting_evidence_ids": [],
        "contradicting_evidence_ids": [],
        "affected_resource_ids": [], "causal_sequence": [], "confidence_components": {},
        "falsification_check": {}, "next_evidence_requests": [],
    }]

    revised = investigator._revise_hypotheses(hypotheses, evidence, context=context)
    observed = next(row for row in revised if row["hypothesis_id"] == "observation")

    assert observed["supporting_evidence_ids"] == ["METRIC-LATENCY"]
    assert observed["contradicting_evidence_ids"] == []


def test_slow_cross_service_trace_supports_dependency_candidate() -> None:
    investigator = IterativeInvestigator(client=FakeDiscoveryClient({}))
    hypothesis = {"claim": "An unhealthy downstream dependency is degrading checkout."}
    trace = {
        "source_type": "trace",
        "metadata": {
            "slowest_spans": [{"service": "payments", "operation": "POST /charge", "duration_ms": 910}],
            "dependency_edges": [{"upstream": "checkout", "downstream": "payments"}],
        },
    }

    assert investigator._structured_mechanism_support(hypothesis, trace) is True


def test_incident_window_evidence_remains_temporally_aligned_after_wall_clock_age() -> None:
    investigator = IterativeInvestigator(client=FakeDiscoveryClient({}))
    row = {
        "incident_window_relation": "during",
        "freshness_seconds": 86400,
        "metadata": {"current_operational_evidence": True},
    }

    assert investigator._incident_window_aligned(row) is True


def test_compiled_trace_evidence_is_idempotent_and_keeps_causal_metadata() -> None:
    investigator = IterativeInvestigator(client=FakeDiscoveryClient({}))
    context = make_context()
    raw = [{
        "evidence_id": "TRACE-BOUND",
        "source": "trace",
        "uri": "jaeger://trace/bound",
        "observed_at": context.alert.starts_at.isoformat(),
        "slowest_spans": [{"service": "payments", "operation": "POST /charge", "duration_ms": 910}],
        "dependency_edges": [{"upstream": "checkout", "downstream": "payments"}],
    }]

    first = investigator._compile_evidence(context, raw)
    second = investigator._compile_evidence(context, first)

    assert second == first
    assert second[0]["metadata"]["dependency_edges"][0]["downstream"] == "payments"
    assert "metadata" not in second[0]["metadata"]


def test_structured_trace_binding_includes_traceable_citation() -> None:
    investigator = IterativeInvestigator(client=FakeDiscoveryClient({}))
    context = make_context()
    evidence = investigator._compile_evidence(context, [{
        "evidence_id": "TRACE-CITED",
        "source": "trace",
        "uri": "jaeger://trace/cited",
        "observed_at": context.alert.starts_at.isoformat(),
        "slowest_spans": [{"service": "payments", "operation": "POST /charge", "duration_ms": 910}],
        "dependency_edges": [{"upstream": "checkout", "downstream": "payments"}],
    }])
    hypotheses = [{
        "hypothesis_id": "dependency",
        "claim": "An unhealthy downstream dependency is degrading checkout.",
        "source": "mechanism_candidate",
        "confidence": 0.0,
        "supporting_evidence_ids": [],
        "contradicting_evidence_ids": [],
        "affected_resource_ids": [],
        "causal_sequence": [],
        "confidence_components": {},
        "falsification_check": {},
        "next_evidence_requests": [],
    }]

    revised = investigator._revise_hypotheses(hypotheses, evidence, context=context)
    bound = next(row for row in revised if row["hypothesis_id"] == "dependency")

    assert bound["supporting_evidence_ids"] == ["TRACE-CITED"]
    assert bound["evidence_bindings"][0]["source_uri"] == "jaeger://trace/cited"
    assert bound["independent_sources"] == ["traces"]


def test_structured_metric_evidence_is_summarized_without_raw_json() -> None:
    summary = IterativeInvestigator._human_evidence_summary({
        "source_status": "completed",
        "query": "sum(rate(http_requests_total[5m]))",
        "series": [{"metric": {"service": "checkout"}, "values": [[1, "2"]]}],
        "provenance": {"source": "onboarded-prometheus"},
    })

    assert summary == "Prometheus returned 1 time series for query: sum(rate(http_requests_total[5m]))"
    assert "source_status" not in summary


def test_missing_optional_sources_do_not_cap_independently_corroborated_mechanism() -> None:
    investigator = IterativeInvestigator(client=FakeDiscoveryClient({}))
    context = make_context()
    evidence = investigator._compile_evidence(context, [{
        "evidence_id": "DEPENDENCY-DOWN",
        "source": "dependency",
        "uri": "docker://payments",
        "observed_at": context.alert.starts_at.isoformat(),
        "service": "payments",
        "related_to": "checkout",
        "runtime_state": "exited",
        "healthy": False,
        "summary": "payments dependency exited during the checkout incident",
    }, {
        "evidence_id": "TRACE-PAYMENTS",
        "source": "trace",
        "uri": "jaeger://trace/payments",
        "observed_at": context.alert.starts_at.isoformat(),
        "slowest_spans": [{"service": "payments", "operation": "POST /charge", "duration_ms": 1200}],
        "dependency_edges": [{"upstream": "checkout", "downstream": "payments"}],
        "summary": "checkout trace stalls at payments",
    }])
    hypotheses = investigator._revise_hypotheses([], evidence, context=context)
    dependency = next(row for row in hypotheses if "dependency" in row["claim"].lower())

    assert dependency["independent_sources"] == ["dependency", "traces"]
    assert "required_sources_unavailable" not in dependency["confidence_breakdown"]["ceiling_reasons"]
    assert dependency["status"] == "confirmed"


def test_derived_observation_cannot_be_promoted_to_root_cause() -> None:
    investigator = IterativeInvestigator(client=FakeDiscoveryClient({}))
    context = make_context()
    evidence = investigator._compile_evidence(context, [{
        "evidence_id": "METRIC-1", "source": "telemetry",
        "uri": "prometheus://checkout/latency", "observed_at": context.alert.starts_at.isoformat(),
        "summary": "checkout latency timeout after deployment",
    }, {
        "evidence_id": "LOG-1", "source": "log",
        "uri": "logs://checkout/timeout", "observed_at": context.alert.starts_at.isoformat(),
        "summary": "checkout latency timeout after deployment",
    }])
    hypotheses = investigator._revise_hypotheses([], evidence, context=context)
    observation = next(row for row in hypotheses if row.get("source") == "derived_observation")

    assert observation["independent_source_count"] == 2
    assert observation["status"] != "confirmed"


def test_truncated_structured_metric_evidence_preserves_query_observation() -> None:
    summary = IterativeInvestigator._human_evidence_summary(
        '{"query": "histogram_quantile(0.95, rate(latency_bucket[5m])) > 2", "series": [{"metric":'
    )

    assert summary == (
        "Prometheus observed matching time series for query: "
        "histogram_quantile(0.95, rate(latency_bucket[5m])) > 2"
    )


def test_pre_alert_trace_inside_query_envelope_counts_as_operational_evidence() -> None:
    investigator = IterativeInvestigator(client=FakeDiscoveryClient({}))
    context = make_context()
    observed_at = context.alert.starts_at - timedelta(minutes=3)

    evidence = investigator._compile_evidence(context, [{
        "evidence_id": "TRACE-PRE-ALERT",
        "source": "trace",
        "uri": "jaeger://trace/pre-alert",
        "observed_at": observed_at.isoformat(),
        "slowest_spans": [{"service": "payments", "operation": "POST /charge", "duration_ms": 910}],
        "dependency_edges": [{"upstream": "checkout", "downstream": "payments"}],
    }])

    assert evidence[0]["incident_window_relation"] == "during"
    assert evidence[0]["current_operational_evidence"] is True


def test_current_dependency_snapshot_is_after_historical_incident_window() -> None:
    investigator = IterativeInvestigator(client=FakeDiscoveryClient({}))
    context = make_context()
    evidence = investigator._compile_evidence(context, [{
        "evidence_id": "DEPENDENCY-NOW",
        "source": "dependency",
        "uri": "docker://kaiops/payments",
        "observed_at": (context.alert.starts_at + timedelta(hours=2)).isoformat(),
        "service": "payments",
        "related_to": "checkout",
        "runtime_state": "running",
        "healthy": True,
    }])

    assert evidence[0]["incident_window_relation"] == "after"
    assert evidence[0]["current_operational_evidence"] is False


def test_unhealthy_dependency_in_incident_window_is_typed_support() -> None:
    investigator = IterativeInvestigator(client=FakeDiscoveryClient({}))
    hypothesis = {"claim": "An unhealthy downstream dependency is degrading checkout."}
    dependency = {
        "source_type": "dependency",
        "service": "payments",
        "metadata": {
            "service": "payments", "related_to": "checkout",
            "runtime_state": "exited", "healthy": False,
        },
    }

    assert investigator._structured_mechanism_support(hypothesis, dependency) is True


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
    context = make_context(hypotheses=[hypothesis])
    client = FakeDiscoveryClient({
        "changes.search": [{
            "evidence_id": "LOG-CONTRADICTION",
            "source": "log",
            "snippet": "checkout connection pool healthy and normal",
            "timestamp": context.alert.starts_at.isoformat(),
        }],
    })
    investigator = IterativeInvestigator(client=client)
    investigator.max_steps = 1

    report = await investigator.investigate(context)

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
