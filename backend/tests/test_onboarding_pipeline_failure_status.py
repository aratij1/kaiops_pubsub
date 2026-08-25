"""C3: a stage failure in the application-onboarding pipeline must record
ApplicationStatus.FAILED (and a failure audit row) instead of silently
freezing the application's status at its last successful stage.

Each of the six onboarding services (discovery-service,
metrics-validation-agent, rule-generation-agent, prometheus-config-service,
validation-agent, dashboard-generator) defines a RabbitMQ message handler
named `handle` as a closure inside `startup(app)`. These tests capture that
closure by monkeypatching consume_rabbitmq_forever (so no real RabbitMQ
connection is made), force the stage's own agent/downstream call to raise,
and invoke `handle(payload)` directly against a real sqlite-backed
IncidentRepository. Two things are asserted for every service:

1. The persisted ApplicationRecord.status is "failed", with a payload entry
   describing the error, and a MonitoringAuditEvent/AuditLogRecord row using
   the stage's own "<topic>.failed" event_type exists (proving
   evidence.get(step.event) on the frontend's stepper does NOT mistake this
   for the stage's success event).
2. The original exception still propagates out of handle() -- this is the
   signal consume_forever's existing retry/backoff/DLQ logic depends on, and
   the fix must not swallow it.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from common.database import ApplicationRecord, OnboardingHistoryRecord
from common.models import (
    ApplicationDiscoveryResult,
    ApplicationRegistration,
    MetricsValidationResult,
    MonitoringValidationResult,
    PrometheusUpdateResult,
    RulesGeneratedResult,
)
from common.repository import IncidentRepository
from sqlalchemy import select


class _FakeProducer:
    def __init__(self) -> None:
        self.published: list[tuple[str, object, str | None]] = []

    async def publish(self, topic: str, event, key: str | None = None) -> None:
        self.published.append((topic, event, key))


class _FakeAppState:
    pass


class _FakeApp:
    def __init__(self, session_factory) -> None:
        self.state = _FakeAppState()
        self.state.session_factory = session_factory
        self.state.producer = _FakeProducer()


def _load_service_module(service_dir: str, module_name: str):
    """Each onboarding service is its own top-level `app.py` (like the
    api-gateway convention in test_api_gateway_safety.py's
    load_api_gateway_app_module), so it must be given a distinct
    sys.modules key per service or the second import silently reuses the
    first service's already-executed module object.
    """
    cache_key = f"kaiops_onboarding_{module_name}"
    existing = sys.modules.get(cache_key)
    if existing is not None:
        return existing
    module_path = Path(f"backend/src/{service_dir}/app.py")
    spec = importlib.util.spec_from_file_location(cache_key, module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[cache_key] = module
    spec.loader.exec_module(module)
    return module


async def _capture_handler(module, monkeypatch, fake_app: _FakeApp):
    """Runs the service's real startup(app) with consume_rabbitmq_forever
    replaced by a stub that captures the `handle` closure instead of
    connecting to RabbitMQ, then returns that closure."""
    captured: dict[str, object] = {}

    async def fake_consume_forever(consumer, handler):
        captured["handle"] = handler

    monkeypatch.setattr(module, "consume_rabbitmq_forever", fake_consume_forever)
    await module.startup(fake_app)
    # startup() schedules consume_rabbitmq_forever(...) via asyncio.create_task
    # rather than awaiting it directly, so the task body (which populates
    # `captured`) only runs once this coroutine yields control back to the
    # event loop.
    await asyncio.sleep(0)
    return captured["handle"]


def make_application(**overrides) -> ApplicationRegistration:
    defaults = dict(
        tenant_id="tenant-a",
        name="checkout-api",
        owner_team="payments-sre",
        owner_email="payments@example.com",
        environment="prod",
        namespace="payments",
        region="us-east-1",
        technology="python-fastapi",
        metrics_endpoint="http://checkout-api.payments.svc.cluster.local:8000/metrics",
    )
    defaults.update(overrides)
    return ApplicationRegistration(**defaults)


async def _seed_application(sqlite_session_factory, application: ApplicationRegistration) -> None:
    async with sqlite_session_factory() as session:
        repo = IncidentRepository(session)
        await repo.save_application(application)
        await session.commit()


async def _fetch_application_record(sqlite_session_factory, application_id) -> ApplicationRecord:
    async with sqlite_session_factory() as session:
        return await session.get(ApplicationRecord, application_id)


async def _fetch_failure_history_rows(sqlite_session_factory, application_id) -> list[OnboardingHistoryRecord]:
    async with sqlite_session_factory() as session:
        result = await session.execute(
            select(OnboardingHistoryRecord).where(
                OnboardingHistoryRecord.application_id == application_id,
                OnboardingHistoryRecord.event_type.like("%.failed"),
            )
        )
        return list(result.scalars().all())


@pytest.mark.asyncio
async def test_discovery_service_records_failed_status_and_reraises(monkeypatch, sqlite_session_factory) -> None:
    module = _load_service_module("discovery-service", "discovery_service")
    application = make_application()
    # application-onboarding creates this row before publishing
    # APPLICATION_ONBOARD_REQUESTED, which is what discovery-service consumes.
    await _seed_application(sqlite_session_factory, application)

    async def failing_run(_application):
        raise RuntimeError("target namespace unreachable")

    monkeypatch.setattr(module.agent, "run", failing_run)
    fake_app = _FakeApp(sqlite_session_factory)
    handle = await _capture_handler(module, monkeypatch, fake_app)

    with pytest.raises(RuntimeError, match="target namespace unreachable"):
        await handle(application.model_dump(mode="json"))

    record = await _fetch_application_record(sqlite_session_factory, application.id)
    assert record is not None
    assert record.status == "failed"
    assert record.payload["discovery"]["failed"] is True
    assert "target namespace unreachable" in record.payload["discovery"]["error"]

    failure_rows = await _fetch_failure_history_rows(sqlite_session_factory, application.id)
    assert len(failure_rows) == 1
    assert failure_rows[0].event_type == "application.discovery.completed.failed"


@pytest.mark.asyncio
async def test_metrics_validation_agent_records_failed_status_and_reraises(monkeypatch, sqlite_session_factory) -> None:
    module = _load_service_module("metrics-validation-agent", "metrics_validation_agent")
    application_id = uuid4()
    discovery = ApplicationDiscoveryResult(
        application_id=application_id,
        tenant_id="tenant-a",
        name="checkout-api",
        namespace="payments",
        technology="python-fastapi",
        metrics_endpoint="http://checkout-api.payments.svc.cluster.local:8000/metrics",
    )

    async def failing_run(_discovery):
        raise RuntimeError("metrics endpoint timed out")

    monkeypatch.setattr(module.agent, "run", failing_run)
    fake_app = _FakeApp(sqlite_session_factory)
    handle = await _capture_handler(module, monkeypatch, fake_app)

    await _seed_application(
        sqlite_session_factory,
        ApplicationRegistration(
            id=application_id,
            tenant_id="tenant-a",
            name="checkout-api",
            owner_team="payments-sre",
            environment="prod",
            namespace="payments",
            technology="python-fastapi",
            metrics_endpoint="http://checkout-api.payments.svc.cluster.local:8000/metrics",
        ),
    )

    with pytest.raises(RuntimeError, match="metrics endpoint timed out"):
        await handle(discovery.model_dump(mode="json"))

    record = await _fetch_application_record(sqlite_session_factory, application_id)
    assert record is not None
    assert record.status == "failed"
    assert record.payload["metrics_validation"]["failed"] is True

    failure_rows = await _fetch_failure_history_rows(sqlite_session_factory, application_id)
    assert len(failure_rows) == 1
    assert failure_rows[0].event_type == "application.metrics.validated.failed"


@pytest.mark.asyncio
async def test_rule_generation_agent_records_failed_status_and_reraises(monkeypatch, sqlite_session_factory) -> None:
    module = _load_service_module("rule-generation-agent", "rule_generation_agent")
    application = make_application()
    await _seed_application(sqlite_session_factory, application)

    validation = MetricsValidationResult(
        application_id=application.id,
        tenant_id=application.tenant_id,
        metrics_endpoint=application.metrics_endpoint,
        metrics_available=True,
    )

    async def failing_run(_application, _discovery, _validation):
        raise RuntimeError("rule template rendering failed")

    monkeypatch.setattr(module.agent, "run", failing_run)
    fake_app = _FakeApp(sqlite_session_factory)
    handle = await _capture_handler(module, monkeypatch, fake_app)

    with pytest.raises(RuntimeError, match="rule template rendering failed"):
        await handle(validation.model_dump(mode="json"))

    record = await _fetch_application_record(sqlite_session_factory, application.id)
    assert record is not None
    assert record.status == "failed"
    assert record.payload["rules_generation"]["failed"] is True

    failure_rows = await _fetch_failure_history_rows(sqlite_session_factory, application.id)
    assert len(failure_rows) == 1
    assert failure_rows[0].event_type == "application.rules.generated.failed"


@pytest.mark.asyncio
async def test_prometheus_config_service_records_failed_status_and_reraises(monkeypatch, sqlite_session_factory) -> None:
    module = _load_service_module("prometheus-config-service", "prometheus_config_service")
    application = make_application()
    await _seed_application(sqlite_session_factory, application)

    result = RulesGeneratedResult(
        application_id=application.id,
        tenant_id=application.tenant_id,
        scrape_config={"job_name": "checkout-api", "targets": ["checkout-api:8000"]},
    )

    def failing_write_artifacts(_application, _result):
        raise RuntimeError("disk write denied")

    monkeypatch.setattr(module, "write_prometheus_artifacts", failing_write_artifacts)
    fake_app = _FakeApp(sqlite_session_factory)
    handle = await _capture_handler(module, monkeypatch, fake_app)

    with pytest.raises(RuntimeError, match="disk write denied"):
        await handle(result.model_dump(mode="json"))

    record = await _fetch_application_record(sqlite_session_factory, application.id)
    assert record is not None
    assert record.status == "failed"
    assert record.payload["prometheus_update"]["failed"] is True

    failure_rows = await _fetch_failure_history_rows(sqlite_session_factory, application.id)
    assert len(failure_rows) == 1
    assert failure_rows[0].event_type == "application.prometheus.updated.failed"


@pytest.mark.asyncio
async def test_validation_agent_records_failed_status_and_reraises(monkeypatch, sqlite_session_factory) -> None:
    module = _load_service_module("validation-agent", "validation_agent")
    application = make_application()
    await _seed_application(sqlite_session_factory, application)

    update = PrometheusUpdateResult(application_id=application.id, tenant_id=application.tenant_id, reload_ok=True)

    async def failing_validate(_prometheus_url, _application):
        raise RuntimeError("prometheus API unreachable")

    monkeypatch.setattr(module, "validate_prometheus_application", failing_validate)
    fake_app = _FakeApp(sqlite_session_factory)
    handle = await _capture_handler(module, monkeypatch, fake_app)

    with pytest.raises(RuntimeError, match="prometheus API unreachable"):
        await handle(update.model_dump(mode="json"))

    record = await _fetch_application_record(sqlite_session_factory, application.id)
    assert record is not None
    assert record.status == "failed"
    assert record.payload["validation"]["failed"] is True

    failure_rows = await _fetch_failure_history_rows(sqlite_session_factory, application.id)
    assert len(failure_rows) == 1
    assert failure_rows[0].event_type == "application.validation.completed.failed"


@pytest.mark.asyncio
async def test_dashboard_generator_records_failed_status_and_reraises(monkeypatch, sqlite_session_factory) -> None:
    module = _load_service_module("dashboard-generator", "dashboard_generator")
    application = make_application()
    await _seed_application(sqlite_session_factory, application)

    validation = MonitoringValidationResult(application_id=application.id, tenant_id=application.tenant_id, target_up=True)

    def failing_build_dashboard(_application, _validation):
        raise RuntimeError("grafana API rejected payload")

    monkeypatch.setattr(module, "build_dashboard", failing_build_dashboard)
    fake_app = _FakeApp(sqlite_session_factory)
    handle = await _capture_handler(module, monkeypatch, fake_app)

    with pytest.raises(RuntimeError, match="grafana API rejected payload"):
        await handle(validation.model_dump(mode="json"))

    record = await _fetch_application_record(sqlite_session_factory, application.id)
    assert record is not None
    assert record.status == "failed"
    assert record.payload["dashboard"]["failed"] is True

    failure_rows = await _fetch_failure_history_rows(sqlite_session_factory, application.id)
    assert len(failure_rows) == 1
    assert failure_rows[0].event_type == "application.dashboard.created.failed"


@pytest.mark.asyncio
async def test_discovery_service_success_path_is_unaffected(monkeypatch, sqlite_session_factory) -> None:
    """Guard against the fix accidentally changing the happy path: a
    successful run must still record its own (non-failed) status and must
    NOT create a `.failed` audit row."""
    module = _load_service_module("discovery-service", "discovery_service")
    application = make_application()
    await _seed_application(sqlite_session_factory, application)

    from common.models import ApplicationDiscoveryResult as _ApplicationDiscoveryResult

    async def succeeding_run(app_registration):
        return _ApplicationDiscoveryResult(
            application_id=app_registration.id,
            tenant_id=app_registration.tenant_id,
            name=app_registration.name,
            namespace=app_registration.namespace,
            technology=app_registration.technology,
            metrics_endpoint=app_registration.metrics_endpoint,
        )

    monkeypatch.setattr(module.agent, "run", succeeding_run)
    fake_app = _FakeApp(sqlite_session_factory)
    handle = await _capture_handler(module, monkeypatch, fake_app)

    await handle(application.model_dump(mode="json"))

    record = await _fetch_application_record(sqlite_session_factory, application.id)
    assert record is not None
    assert record.status == "discovered"

    failure_rows = await _fetch_failure_history_rows(sqlite_session_factory, application.id)
    assert failure_rows == []
    assert fake_app.state.producer.published
