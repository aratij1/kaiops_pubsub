from __future__ import annotations

import json

from common.config import Settings
from common.connection_config import connector_catalog_from_connection_config, load_connection_config
from common.models import Alert, AlertSeverity
from common.orchestration.execution_plan import resolve_execution_plan


def test_connection_config_expands_env_and_normalizes_connectors(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "connections.json"
    config_path.write_text(
        json.dumps(
            {
                "version": "kaiops-connections-v1",
                "environment": "${ENVIRONMENT:-dev}",
                "cloud_provider": "${CLOUD_PROVIDER:-local}",
                "external_applications": {
                    "default_connector": "checkout",
                    "connectors": {
                        "checkout": {
                            "connector_id": "checkout-api",
                            "system": "checkout",
                            "type": "api",
                            "endpoint": "${CHECKOUT_ENDPOINT:-https://checkout.internal}",
                            "secret_ref": "vault://kaiops/${ENVIRONMENT:-dev}/checkout-token",
                            "allowed_operations": ["read_status", "restart_service"],
                        }
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ENVIRONMENT", "qa")
    monkeypatch.setenv("CLOUD_PROVIDER", "aws")
    monkeypatch.setenv("CHECKOUT_ENDPOINT", "https://checkout.prod.internal")

    config = load_connection_config(Settings(ENVIRONMENT="test", CONNECTION_CONFIG_PATH=str(config_path)))
    catalog = connector_catalog_from_connection_config(config)

    assert config["environment"] == "qa"
    assert config["cloud_provider"] == "aws"
    assert catalog["default_connector"] == "checkout"
    assert catalog["connectors"]["checkout"]["endpoint"] == "https://checkout.prod.internal"
    assert catalog["connectors"]["checkout"]["secret_ref"] == "vault://kaiops/qa/checkout-token"
    assert catalog["connectors"]["checkout"]["retry"]["max_attempts"] == 2


def test_execution_plan_includes_standard_connection_architecture() -> None:
    alert = Alert(
        source="prometheus",
        name="DatabaseReplicaLag",
        service="orders-db",
        severity=AlertSeverity.CRITICAL,
        description="orders database replica lag above threshold",
    )

    plan = resolve_execution_plan(
        alert=alert,
        workflow_name="critical-auto-remediation",
        requires_approval=True,
        risk_tier="high",
        execution_mode="human-approval",
    )

    connection = plan["connection"]
    assert connection["architecture"]["mode"] == "externalized-shared-state"
    assert connection["connector"]["connector_id"] == "orders-db-api"
    assert connection["connector"]["timeout_seconds"] == 10
    assert "read_status" in connection["connector"]["allowed_operations"]
    assert connection["platform"]["message_bus"]["provider"]
