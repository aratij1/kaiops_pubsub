from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest
from ai_workbench_common.models import Context
from common.models import Alert, AlertSeverity, Incident
from common.repository import IncidentRepository


def load_context_app_module():
    module_name = "context_agent_strategy_app"
    if module_name in sys.modules:
        return sys.modules[module_name]
    module_path = Path("ai-workbench/src/context-agent/app.py")
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class CountingContextAgent:
    def __init__(self) -> None:
        self.calls = 0

    async def collect_with_runtime(self, alert: Alert, incident: Incident) -> Context:
        self.calls += 1
        return Context(
            tenant_id=alert.tenant_id,
            incident_id=incident.id,
            alert=alert,
            deployment="release-42",
            runbook="Restart the worker and verify queue recovery.",
            dependency_services=["redis"],
            observability={"queue_lag": 42, "source": "test-metric"},
            metadata={
                "collector_call": self.calls,
                "discovery_report": {
                    "evidence": [{"source": "code", "uri": "repository://orders/worker.py"}],
                },
            },
        )


def make_alert() -> Alert:
    return Alert(
        tenant_id="tenant-a",
        source="prometheus",
        name="WorkerQueueLagHigh",
        service="worker",
        environment="prod",
        severity=AlertSeverity.HIGH,
        description="Queue lag is above threshold",
        labels={"application": "orders", "namespace": "production"},
        metadata={"tenant_id": "tenant-a"},
    )


def make_incident(alert: Alert) -> Incident:
    return Incident(
        tenant_id=alert.tenant_id,
        alert_ids=[alert.id],
        service=alert.service,
        environment=alert.environment,
        severity=alert.severity,
        title=alert.name,
    )


@pytest.mark.asyncio
async def test_auto_mode_collects_once_then_reuses_complete_durable_context(sqlite_session_factory) -> None:
    module = load_context_app_module()
    collector = CountingContextAgent()
    module.agent = collector
    module.settings.database_enabled = True
    module.settings.context_strategy = "auto"
    module.settings.context_knowledge_ttl_seconds = 3600
    module.settings.context_resolution_reuse_enabled = True
    module.settings.context_resolution_reuse_min_score = 0.7
    module.app.state.session_factory = sqlite_session_factory

    first_alert = make_alert()
    first = await module._collect_context_with_strategy(module.app, first_alert, make_incident(first_alert))
    async with sqlite_session_factory() as session:
        repo = IncidentRepository(session)
        attached = await repo.attach_context_knowledge_resolution(
            first.metadata["context_knowledge_id"],
            {"root_cause": "A blocked worker exhausted the queue consumer pool", "impact": "Order processing delayed", "confidence": 0.82},
        )
        await session.commit()
    assert attached is True
    second_alert = make_alert()
    second = await module._collect_context_with_strategy(module.app, second_alert, make_incident(second_alert))

    assert collector.calls == 1
    assert first.metadata["context_reused"] is False
    assert second.metadata["context_reused"] is True
    assert second.alert.id == second_alert.id
    assert second.incident_id != first.incident_id
    assert second.metadata["context_source_alert_id"] == str(first_alert.id)
    assert second.metadata["context_knowledge_id"] == first.metadata["context_knowledge_id"]
    assert second.metadata["prior_resolution"]["root_cause"].startswith("A blocked worker")
    assert second.metadata["alert_type_known"] is True
    assert second.metadata["knowledge_route"] == "reuse_validated_context_snapshot"
    assert second.metadata["context_quality"]["reusable"] is True


@pytest.mark.asyncio
async def test_same_alert_family_refreshes_when_subject_scope_changes(sqlite_session_factory) -> None:
    module = load_context_app_module()
    collector = CountingContextAgent()
    module.agent = collector
    module.settings.database_enabled = True
    module.settings.context_strategy = "auto"
    module.settings.context_knowledge_ttl_seconds = 3600
    module.settings.context_resolution_reuse_enabled = True
    module.settings.context_resolution_reuse_min_score = 0.7
    module.app.state.session_factory = sqlite_session_factory

    first_alert = make_alert()
    first = await module._collect_context_with_strategy(module.app, first_alert, make_incident(first_alert))
    async with sqlite_session_factory() as session:
        repo = IncidentRepository(session)
        await repo.attach_context_knowledge_resolution(
            first.metadata["context_knowledge_id"],
            {"root_cause": "Known queue saturation", "impact": "Delayed orders", "confidence": 0.91},
        )
        await session.commit()

    repeated_alert = make_alert().model_copy(
        update={"labels": {"application": "orders-v2", "namespace": "blue", "project": "migration"}}
    )
    repeated = await module._collect_context_with_strategy(
        module.app, repeated_alert, make_incident(repeated_alert)
    )

    assert collector.calls == 2
    assert repeated.metadata["context_reused"] is False
    assert repeated.metadata["context_source"] == "realtime_collection"
    assert repeated.metadata["context_subject_fingerprint"] != first.metadata["context_subject_fingerprint"]


@pytest.mark.asyncio
async def test_auto_mode_reuses_good_context_but_not_low_quality_prior_rca(sqlite_session_factory) -> None:
    module = load_context_app_module()
    collector = CountingContextAgent()
    module.agent = collector
    module.settings.database_enabled = True
    module.settings.context_strategy = "auto"
    module.settings.context_resolution_reuse_enabled = True
    module.settings.context_resolution_reuse_min_score = 0.7
    module.app.state.session_factory = sqlite_session_factory

    first_alert = make_alert()
    first = await module._collect_context_with_strategy(module.app, first_alert, make_incident(first_alert))
    async with sqlite_session_factory() as session:
        repo = IncidentRepository(session)
        await repo.attach_context_knowledge_resolution(
            first.metadata["context_knowledge_id"],
            {"root_cause": "Tentative cause", "impact": "Unknown", "confidence": 0.7},
        )
        await session.commit()

    second_alert = make_alert()
    second = await module._collect_context_with_strategy(module.app, second_alert, make_incident(second_alert))

    assert collector.calls == 1
    assert second.metadata["context_reused"] is True
    assert second.metadata["context_source"] == "periodic_knowledge"
    assert second.metadata["prior_resolution_reusable"] is False
    assert second.metadata["prior_resolution"] == {}


@pytest.mark.asyncio
async def test_realtime_mode_always_refreshes_but_still_updates_knowledge(sqlite_session_factory) -> None:
    module = load_context_app_module()
    collector = CountingContextAgent()
    module.agent = collector
    module.settings.database_enabled = True
    module.settings.context_strategy = "auto"
    module.app.state.session_factory = sqlite_session_factory

    for _ in range(2):
        alert = make_alert()
        context = await module._collect_context_with_strategy(
            module.app,
            alert,
            make_incident(alert),
            "realtime",
        )
        assert context.metadata["context_strategy"] == "realtime"
        assert context.metadata["context_reused"] is False
        assert context.metadata["realtime_collection_performed"] is True

    assert collector.calls == 2


@pytest.mark.asyncio
async def test_historical_cache_miss_never_runs_live_collection(sqlite_session_factory) -> None:
    module = load_context_app_module()
    collector = CountingContextAgent()
    module.agent = collector
    module.settings.database_enabled = True
    module.app.state.session_factory = sqlite_session_factory
    alert = make_alert()

    context = await module._collect_context_with_strategy(
        module.app, alert, make_incident(alert), "historical"
    )

    assert collector.calls == 0
    assert context.metadata["context_source"] == "historical_cache_miss"
    assert context.metadata["realtime_collection_performed"] is False


def test_auto_is_the_default_strategy_and_legacy_names_are_supported() -> None:
    module = load_context_app_module()
    module.settings.context_strategy = "auto"
    assert module._context_strategy() == "auto"
    assert module._context_strategy("continuous") == "auto"
    assert module._context_strategy("immediate") == "realtime"
    assert module._context_strategy("historical") == "historical"
    assert module._context_strategy("unsupported") == "auto"
