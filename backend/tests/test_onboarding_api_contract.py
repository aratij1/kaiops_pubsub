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


def valid_azure_payload() -> dict:
    payload = valid_payload()
    payload["deployment_mode"] = "azure_cloud"
    payload["prometheus_url"] = ""
    payload["new_relic_url"] = ""
    payload["datadog_url"] = ""
    payload["azure_subscription_id"] = "00000000-0000-0000-0000-000000000000"
    payload["azure_resource_group"] = "rg-kaiops-prod"
    payload["azure_service_bus_namespace"] = "sb-kaiops-prod"
    payload["azure_service_bus_topic"] = "kaiops-orchestration-events"
    payload["azure_service_bus_subscription"] = "kaiops-orchestration-sub"
    payload["azure_content_safety_enabled"] = True
    payload["azure_content_safety_endpoint"] = "https://kaiops-cs.cognitiveservices.azure.com"
    payload["active_provider"] = "azure_service_bus"
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
async def test_onboarding_connectivity_accepts_azure_cloud_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_monitoring_app_module()

    observed: dict[str, dict] = {}

    def fake_save_onboarding_connectivity(payload: dict) -> dict:
        observed["saved"] = payload
        return payload

    async def fake_persist_onboarding_connectivity(payload: dict) -> None:
        observed["persisted"] = payload

    monkeypatch.setattr(module, "save_onboarding_connectivity", fake_save_onboarding_connectivity)
    monkeypatch.setattr(module, "persist_onboarding_connectivity", fake_persist_onboarding_connectivity)

    payload = valid_azure_payload()
    response = await module.post_onboarding_connectivity(payload)

    assert response.connectivity.deployment_mode == "azure_cloud"
    assert response.connectivity.azure_subscription_id == "00000000-0000-0000-0000-000000000000"
    assert observed["persisted"]["active_provider"] == "azure_service_bus"


@pytest.mark.asyncio
async def test_onboarding_connectivity_requires_azure_subscription_in_cloud_mode(
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

    payload = valid_azure_payload()
    payload["azure_subscription_id"] = ""

    with pytest.raises(ValidationError) as exc:
        await module.post_onboarding_connectivity(payload)

    assert "azure_subscription_id is required for azure_cloud mode" in str(exc.value)
    assert write_called["save"] is False
    assert write_called["persist"] is False


def test_generated_onboarding_documents_use_rag_metadata_contract() -> None:
    module = load_monitoring_app_module()
    connectivity = module.OnboardingConnectivityPayload.model_validate(valid_payload())
    workflow_result = {
        "workflow_id": "workflow-1",
        "onboarding_id": "onboarding-1",
        "trace_id": "trace-1",
        "generated_rules": [
            {
                "name": "payments-null-customer-id-critical-prometheus",
                "platform": "prometheus",
                "expression": "null_customer_id_ratio > 2",
            }
        ],
    }

    documents = module._build_onboarding_rag_documents(
        connectivity=connectivity,
        selected_tool="prometheus",
        workflow_result=workflow_result,
        requirements=["Generate a critical data quality alert for null customer IDs"],
        source_documents=[
            {
                "kind": "rca",
                "name": "dq-rca.md",
                "excerpt": "Null customer ID ratio exceeded threshold.",
            }
        ],
    )

    assert {document["kind"] for document in documents} == {"incident", "runbook", "dependency", "change"}
    for document in documents:
        assert all(isinstance(value, str) for value in document.get("metadata", {}).values())
