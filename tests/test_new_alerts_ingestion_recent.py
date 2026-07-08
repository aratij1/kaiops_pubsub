import importlib.util
from collections import deque
from pathlib import Path

import pytest


class _DummyProducer:
    async def publish(self, *_args, **_kwargs) -> None:
        return None


def load_monitoring_app_module():
    module_path = Path("services/monitoring-adapter/app.py")
    spec = importlib.util.spec_from_file_location("monitoring_adapter_app", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_ingest_alert_exposes_latest_50_alerts_in_recent_feed() -> None:
    module = load_monitoring_app_module()
    original_recent_alerts = getattr(module, "RECENT_ALERTS")

    setattr(module, "RECENT_ALERTS", deque(maxlen=200))
    module.app.state.producer = _DummyProducer()

    try:
        for idx in range(60):
            await module.ingest_alert(
                payload={
                    "source": "prometheus",
                    "name": f"NewAlert-{idx}",
                    "service": "orders",
                    "severity": "warning",
                    "description": f"Synthetic alert {idx}",
                },
                x_trace_id=f"trace-{idx}",
            )

        recent = await module.get_recent_alerts(limit=50)

        assert recent["count"] == 50
        assert len(recent["rows"]) == 50
        assert recent["rows"][0]["name"] == "NewAlert-59"
        assert recent["rows"][0]["trace_id"] == "trace-59"
    finally:
        setattr(module, "RECENT_ALERTS", original_recent_alerts)
