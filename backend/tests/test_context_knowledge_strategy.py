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
            incident_id=incident.id,
            alert=alert,
            deployment="release-42",
            runbook="Restart the worker and verify queue recovery.",
            dependency_services=["redis"],
            metadata={"collector_call": self.calls},
        )


def make_alert() -> Alert:
    return Alert(
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
        alert_ids=[alert.id],
        service=alert.service,
        environment=alert.environment,
        severity=alert.severity,
        title=alert.name,
    )


@pytest.mark.asyncio
async def test_continuous_mode_collects_once_then_reuses_durable_context(sqlite_session_factory) -> None:
    module = load_context_app_module()
    collector = CountingContextAgent()
    module.agent = collector
    module.settings.database_enabled = True
    module.settings.context_strategy = "continuous"
    module.settings.context_knowledge_ttl_seconds = 3600
    module.app.state.session_factory = sqlite_session_factory

    first_alert = make_alert()
    first = await module._collect_context_with_strategy(module.app, first_alert, make_incident(first_alert))
    async with sqlite_session_factory() as session:
        repo = IncidentRepository(session)
        attached = await repo.attach_context_knowledge_resolution(
            first.metadata["context_knowledge_id"],
            {"root_cause": "A blocked worker exhausted the queue consumer pool", "impact": "Order processing delayed"},
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


@pytest.mark.asyncio
async def test_immediate_mode_always_refreshes_but_still_updates_knowledge(sqlite_session_factory) -> None:
    module = load_context_app_module()
    collector = CountingContextAgent()
    module.agent = collector
    module.settings.database_enabled = True
    module.settings.context_strategy = "continuous"
    module.app.state.session_factory = sqlite_session_factory

    for _ in range(2):
        alert = make_alert()
        context = await module._collect_context_with_strategy(
            module.app,
            alert,
            make_incident(alert),
            "immediate",
        )
        assert context.metadata["context_strategy"] == "immediate"
        assert context.metadata["context_reused"] is False

    assert collector.calls == 2


def test_continuous_is_the_default_strategy() -> None:
    module = load_context_app_module()
    module.settings.context_strategy = "continuous"
    assert module._context_strategy() == "continuous"
    assert module._context_strategy("immediate") == "immediate"
    assert module._context_strategy("unsupported") == "continuous"
