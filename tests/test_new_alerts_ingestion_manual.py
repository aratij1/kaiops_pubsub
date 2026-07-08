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
async def test_manual_ingestion_endpoint_returns_worker_result() -> None:
    module = load_monitoring_app_module()

    async def fake_run_ingestion_once(*, reason: str):
        assert reason == "manual"
        return {
            "status": "ok",
            "reason": reason,
            "processed_files": 2,
            "processed_alerts": 4,
            "failed_files": 0,
            "details": [],
        }

    original_runner = module._run_ingestion_once
    module._run_ingestion_once = fake_run_ingestion_once

    try:
        response = await module.run_ingestion_now()
    finally:
        module._run_ingestion_once = original_runner

    assert response["result"]["status"] == "ok"
    assert response["result"]["processed_alerts"] == 4
    assert response["result"]["reason"] == "manual"
