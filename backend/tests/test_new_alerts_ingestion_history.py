import importlib.util
from collections import deque
from pathlib import Path

import pytest


def load_monitoring_app_module():
    module_path = Path("backend/src/monitoring-adapter/app.py")
    spec = importlib.util.spec_from_file_location("monitoring_adapter_app", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_get_all_alerts_supports_historical_window_limit() -> None:
    module = load_monitoring_app_module()
    original_recent_alerts = getattr(module, "RECENT_ALERTS")

    setattr(module, "RECENT_ALERTS", deque(maxlen=200))
    for idx in range(120):
        getattr(module, "RECENT_ALERTS").appendleft(
            {
                "id": f"alert-{idx}",
                "trace_id": f"trace-{idx}",
                "source": "prometheus",
                "name": f"HistoricalAlert-{idx}",
                "service": "orders",
                "severity": "warning",
                "description": "historical",
                "created_at": f"2026-07-01T00:{idx % 60:02d}:00+00:00",
            }
        )

    try:
        full_window = await module.get_all_alerts(limit=120)
        narrow_window = await module.get_all_alerts(limit=30)

        assert full_window["count"] == 120
        assert len(full_window["rows"]) == 120
        assert narrow_window["count"] == 30
        assert len(narrow_window["rows"]) == 30
    finally:
        setattr(module, "RECENT_ALERTS", original_recent_alerts)
