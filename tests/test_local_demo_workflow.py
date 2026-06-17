import importlib.util
from pathlib import Path

import pytest


def load_monitoring_app_module():
    module_path = Path("services/monitoring-adapter/app.py")
    spec = importlib.util.spec_from_file_location("monitoring_adapter_app", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_local_payment_workflow_generates_recommendation() -> None:
    module = load_monitoring_app_module()

    workflow = await module.run_local_payment_workflow()

    assert workflow["mode"] == "local-no-kafka"
    assert workflow["alert"].severity == "critical"
    assert workflow["incident"].service == "payments"
    assert workflow["decision"]["workflow"] == "critical-auto-remediation"
    assert workflow["context"].deployment == "Deployment 2.5"
    assert workflow["recommendation"].recommended_action == "Rollback deployment"
