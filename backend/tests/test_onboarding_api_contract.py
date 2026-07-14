import importlib.util
from pathlib import Path

import pytest
from pydantic import ValidationError


def load_monitoring_app_module():
    module_path = Path("backend/src/monitoring-adapter/app.py")
    spec = importlib.util.spec_from_file_location("monitoring_adapter_app", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def valid_payload() -> dict:
    return {
        "project": {
            "name": "payments-platform",
            "owner_team": "platform-ops",
            "environment": "prod",
            "region": "us-east-1",
        },
        "prometheus_url": "https://prometheus.example.com/-/ready",
        "new_relic_url": "https://api.newrelic.com/v2/applications.json",
        "datadog_url": "https://api.datadoghq.com/api/v1/validate",
        "user_assignments": {
            "l2.operator": ["payments-platform", "data-platform"],
            "l3.engineer": ["payments-platform"],
        },
        "provider_statuses": {
            "prometheus": {"ok": True, "message": "Connected"},
            "new_relic": {"ok": False, "message": "401 Unauthorized"},
        },
        "active_provider": "prometheus",
        "updated_at": "2026-07-08 10:30:00",
    }


def valid_gcp_payload() -> dict:
    payload = valid_payload()
    payload["deployment_mode"] = "gcp_cloud"
    payload["prometheus_url"] = ""
    payload["new_relic_url"] = ""
    payload["datadog_url"] = ""
    payload["gcp_project_id"] = "kaiops-prod"
    payload["gcp_region"] = "us-central1"
    payload["pubsub_topic"] = "kaiops-orchestration-events"
    payload["pubsub_subscription"] = "kaiops-orchestration-sub"
    payload["vertex_model_armor_enabled"] = True
    payload["vertex_model_armor_template"] = "projects/kaiops-prod/locations/us-central1/templates/default"
    payload["active_provider"] = "pubsub"
    return payload


@pytest.mark.asyncio
async def test_onboarding_connectivity_preserves_user_assignments(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_monitoring_app_module()

    observed: dict[str, dict] = {}

    def fake_save_onboarding_connectivity(payload: dict) -> dict:
        observed["saved"] = payload
        return {
            "project": payload["project"],
            "prometheus_url": payload["prometheus_url"],
            "new_relic_url": payload["new_relic_url"],
            "datadog_url": payload["datadog_url"],
            "user_assignments": payload["user_assignments"],
            "updated_at": payload["updated_at"],
        }

    async def fake_persist_onboarding_connectivity(payload: dict) -> None:
        observed["persisted"] = payload

    monkeypatch.setattr(module, "save_onboarding_connectivity", fake_save_onboarding_connectivity)
    monkeypatch.setattr(module, "persist_onboarding_connectivity", fake_persist_onboarding_connectivity)

    payload = valid_payload()
    response = await module.post_onboarding_connectivity(payload)

    assert response.connectivity.user_assignments == payload["user_assignments"]
    assert observed["saved"]["user_assignments"] == payload["user_assignments"]
    assert observed["persisted"]["user_assignments"] == payload["user_assignments"]


@pytest.mark.asyncio
async def test_onboarding_connectivity_persists_provider_statuses_for_rehydration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_monitoring_app_module()

    observed: dict[str, dict] = {}

    def fake_save_onboarding_connectivity(payload: dict) -> dict:
        observed["saved"] = payload
        return {
            "project": payload["project"],
            "prometheus_url": payload["prometheus_url"],
            "new_relic_url": payload["new_relic_url"],
            "datadog_url": payload["datadog_url"],
            "user_assignments": payload["user_assignments"],
            "updated_at": payload["updated_at"],
        }

    async def fake_persist_onboarding_connectivity(payload: dict) -> None:
        observed["persisted"] = payload

    monkeypatch.setattr(module, "save_onboarding_connectivity", fake_save_onboarding_connectivity)
    monkeypatch.setattr(module, "persist_onboarding_connectivity", fake_persist_onboarding_connectivity)

    payload = valid_payload()
    await module.post_onboarding_connectivity(payload)

    statuses = observed["persisted"].get("provider_statuses", {})
    assert statuses["prometheus"]["ok"] is True
    assert "Connected" in statuses["prometheus"]["message"]
    assert statuses["new_relic"]["ok"] is False


@pytest.mark.asyncio
async def test_onboarding_connectivity_rejects_invalid_project_and_skips_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_monitoring_app_module()

    write_called = {"save": False, "persist": False}

    def fake_save_onboarding_connectivity(payload: dict) -> dict:
        write_called["save"] = True
        return payload

    async def fake_persist_onboarding_connectivity(payload: dict) -> None:
        write_called["persist"] = True

    monkeypatch.setattr(module, "save_onboarding_connectivity", fake_save_onboarding_connectivity)
    monkeypatch.setattr(module, "persist_onboarding_connectivity", fake_persist_onboarding_connectivity)

    payload = valid_payload()
    payload["project"] = {
        "name": "",
        "owner_team": "platform-ops",
        "environment": "prod",
        "region": "us-east-1",
    }

    with pytest.raises(ValidationError) as exc:
        await module.post_onboarding_connectivity(payload)

    assert "project.name is required" in str(exc.value)
    assert write_called["save"] is False
    assert write_called["persist"] is False


@pytest.mark.asyncio
async def test_onboarding_connectivity_accepts_gcp_cloud_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_monitoring_app_module()

    observed: dict[str, dict] = {}

    def fake_save_onboarding_connectivity(payload: dict) -> dict:
        observed["saved"] = payload
        return payload

    async def fake_persist_onboarding_connectivity(payload: dict) -> None:
        observed["persisted"] = payload

    monkeypatch.setattr(module, "save_onboarding_connectivity", fake_save_onboarding_connectivity)
    monkeypatch.setattr(module, "persist_onboarding_connectivity", fake_persist_onboarding_connectivity)

    payload = valid_gcp_payload()
    response = await module.post_onboarding_connectivity(payload)

    assert response.connectivity.deployment_mode == "gcp_cloud"
    assert response.connectivity.gcp_project_id == "kaiops-prod"
    assert observed["persisted"]["active_provider"] == "pubsub"


@pytest.mark.asyncio
async def test_onboarding_connectivity_requires_gcp_project_in_cloud_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_monitoring_app_module()

    write_called = {"save": False, "persist": False}

    def fake_save_onboarding_connectivity(payload: dict) -> dict:
        write_called["save"] = True
        return payload

    async def fake_persist_onboarding_connectivity(payload: dict) -> None:
        write_called["persist"] = True

    monkeypatch.setattr(module, "save_onboarding_connectivity", fake_save_onboarding_connectivity)
    monkeypatch.setattr(module, "persist_onboarding_connectivity", fake_persist_onboarding_connectivity)

    payload = valid_gcp_payload()
    payload["gcp_project_id"] = ""

    with pytest.raises(ValidationError) as exc:
        await module.post_onboarding_connectivity(payload)

    assert "gcp_project_id is required for gcp_cloud mode" in str(exc.value)
    assert write_called["save"] is False
    assert write_called["persist"] is False
