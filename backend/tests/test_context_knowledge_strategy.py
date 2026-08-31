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
            metadata={
                "collector_call": self.calls,
                "discovery_report": {
                    "evidence": [{"source": "code", "uri": "repository://orders/worker.py"}],
                },
            },
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
    assert second.metadata["knowledge_route"] == "reuse_periodic_knowledge"


@pytest.mark.asyncio
async def test_same_alert_type_reuses_knowledge_across_volatile_labels(sqlite_session_factory) -> None:
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

    assert collector.calls == 1
    assert repeated.metadata["context_reused"] is True
    assert repeated.metadata["context_source"] == "periodic_knowledge"
    assert repeated.metadata["realtime_collection_performed"] is False


@pytest.mark.asyncio
async def test_auto_mode_refreshes_when_prior_rca_score_does_not_exceed_threshold(sqlite_session_factory) -> None:
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

    assert collector.calls == 2
    assert second.metadata["context_reused"] is False
    assert second.metadata["context_source"] == "realtime_collection"


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


def test_identity_normalization_and_failure_families() -> None:
    module = load_context_app_module()
    
    # 1. Timestamped alert names produce the same identity
    alert1 = Alert(source="prometheus", description="Payment latency alert", name="payment-latency-critical-20260813T125502Z", service="rs-payment", environment="prod")
    alert2 = Alert(source="prometheus", description="Payment latency alert", name="payment-latency-critical-2026-08-14T11:54:32Z", service="rs-payment", environment="prod")
    _, _, _, sig1 = module._context_identity(alert1)
    _, _, _, sig2 = module._context_identity(alert2)
    assert sig1 == sig2

    # 2. UUID/numeric/hex suffixes do not create unnecessary new identities
    alert_uuid1 = Alert(source="prometheus", description="Database error alert", name="db-error-f47ac10b-58cc-4372-a567-0e02b2c3d479", service="rs-mysql", environment="prod")
    alert_uuid2 = Alert(source="prometheus", description="Database error alert", name="db-error-e2024b1b-a3af-436e-aa23-3753be4d27f0", service="rs-mysql", environment="prod")
    _, _, _, sig_uuid1 = module._context_identity(alert_uuid1)
    _, _, _, sig_uuid2 = module._context_identity(alert_uuid2)
    assert sig_uuid1 == sig_uuid2

    alert_hex1 = Alert(source="prometheus", description="Payment latency alert", name="payment-latency-ab12cd", service="rs-payment", environment="prod")
    alert_hex2 = Alert(source="prometheus", description="Payment latency alert", name="payment-latency-9876ef", service="rs-payment", environment="prod")
    _, _, _, sig_hex1 = module._context_identity(alert_hex1)
    _, _, _, sig_hex2 = module._context_identity(alert_hex2)
    assert sig_hex1 == sig_hex2

    alert_num1 = Alert(source="prometheus", description="Worker lag alert", name="worker-lag-42", service="worker", environment="prod")
    alert_num2 = Alert(source="prometheus", description="Worker lag alert", name="worker-lag-101", service="worker", environment="prod")
    _, _, _, sig_num1 = module._context_identity(alert_num1)
    _, _, _, sig_num2 = module._context_identity(alert_num2)
    assert sig_num1 == sig_num2

    # 3. Same service + environment + failure family reuses context
    alert_fam1 = Alert(source="prometheus", description="High latency alert", name="HighRequestLatency", service="rs-payment", environment="prod")
    alert_fam2 = Alert(source="prometheus", description="Catalogue latency alert", name="Catalogue latency degraded", service="rs-payment", environment="prod")
    _, _, _, sig_fam1 = module._context_identity(alert_fam1)
    _, _, _, sig_fam2 = module._context_identity(alert_fam2)
    assert sig_fam1 == sig_fam2

    # 4. Same service + environment but different failure families do NOT reuse context
    alert_diff_fam1 = Alert(source="prometheus", description="High latency alert", name="HighRequestLatency", service="rs-payment", environment="prod")
    alert_diff_fam2 = Alert(source="prometheus", description="Payment unavailable alert", name="Payment API unavailable", service="rs-payment", environment="prod")
    _, _, _, sig_diff_fam1 = module._context_identity(alert_diff_fam1)
    _, _, _, sig_diff_fam2 = module._context_identity(alert_diff_fam2)
    assert sig_diff_fam1 != sig_diff_fam2

    # 5. Different services do NOT reuse context
    alert_diff_svc1 = Alert(source="prometheus", description="MySQL replica down alert", name="MySQL replica down", service="rs-mysql", environment="prod")
    alert_diff_svc2 = Alert(source="prometheus", description="Service down alert", name="Service down", service="rs-user", environment="prod")
    _, _, _, sig_diff_svc1 = module._context_identity(alert_diff_svc1)
    _, _, _, sig_diff_svc2 = module._context_identity(alert_diff_svc2)
    assert sig_diff_svc1 != sig_diff_svc2

    # 6. Different environments do NOT reuse context
    alert_diff_env1 = Alert(source="prometheus", description="High latency alert", name="HighRequestLatency", service="rs-payment", environment="prod")
    alert_diff_env2 = Alert(source="prometheus", description="High latency alert", name="HighRequestLatency", service="rs-payment", environment="staging")
    _, _, _, sig_diff_env1 = module._context_identity(alert_diff_env1)
    _, _, _, sig_diff_env2 = module._context_identity(alert_diff_env2)
    assert sig_diff_env1 != sig_diff_env2


@pytest.mark.asyncio
async def test_auto_mode_reuses_valid_cached_context_with_runbook_or_rag(sqlite_session_factory) -> None:
    module = load_context_app_module()
    collector = CountingContextAgent()
    module.agent = collector
    module.settings.database_enabled = True
    module.settings.context_strategy = "auto"
    module.settings.context_knowledge_ttl_seconds = 3600
    module.app.state.session_factory = sqlite_session_factory

    alert = make_alert()
    incident = make_incident(alert)

    async with sqlite_session_factory() as session:
        tenant_id, service, environment, signature = module._context_identity(alert)
        payload = {
            "incident_id": str(incident.id),
            "alert": alert.model_dump(mode="json"),
            "runbook": "Custom recovery runbook",
            "dependency_services": [],
            "metadata": {"rag_documents": 0},
        }
        from common.database import ContextKnowledgeRecord
        record = ContextKnowledgeRecord(
            tenant_id=tenant_id,
            service=service,
            environment=environment,
            alert_name=alert.name,
            alert_signature=signature,
            payload=payload,
            source_alert_id=alert.id,
            source_incident_id=incident.id,
        )
        session.add(record)
        await session.commit()

    context = await module._collect_context_with_strategy(module.app, alert, incident)

    assert collector.calls == 0
    assert context.metadata["context_reused"] is True
    assert context.runbook == "Custom recovery runbook"


@pytest.mark.asyncio
async def test_auto_mode_reuses_valid_cached_context_with_rag_documents(sqlite_session_factory) -> None:
    module = load_context_app_module()
    collector = CountingContextAgent()
    module.agent = collector
    module.settings.database_enabled = True
    module.settings.context_strategy = "auto"
    module.settings.context_knowledge_ttl_seconds = 3600
    module.app.state.session_factory = sqlite_session_factory

    alert = make_alert()
    incident = make_incident(alert)

    async with sqlite_session_factory() as session:
        tenant_id, service, environment, signature = module._context_identity(alert)
        payload = {
            "incident_id": str(incident.id),
            "alert": alert.model_dump(mode="json"),
            "runbook": "",
            "dependency_services": [],
            "metadata": {"rag_documents": 3},
        }
        from common.database import ContextKnowledgeRecord
        record = ContextKnowledgeRecord(
            tenant_id=tenant_id,
            service=service,
            environment=environment,
            alert_name=alert.name,
            alert_signature=signature,
            payload=payload,
            source_alert_id=alert.id,
            source_incident_id=incident.id,
        )
        session.add(record)
        await session.commit()

    context = await module._collect_context_with_strategy(module.app, alert, incident)

    assert collector.calls == 0
    assert context.metadata["context_reused"] is True
