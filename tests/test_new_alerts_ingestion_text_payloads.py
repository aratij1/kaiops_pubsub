import importlib.util
from pathlib import Path


def load_monitoring_app_module():
    module_path = Path("services/monitoring-adapter/app.py")
    spec = importlib.util.spec_from_file_location("monitoring_adapter_app", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_text_alert_file_parses_prometheus_and_new_relic_blocks(tmp_path) -> None:
    module = load_monitoring_app_module()
    source_file = tmp_path / "prometheus-newrelic-alerts.txt"
    source_file.write_text(
        """
source=prometheus
alertname=OrdersReplicaLag
service=orders-db
severity=critical
description=Replica lag above threshold

source: newrelic
incident_title: Payments API Error Rate Spike
service: payments-api
priority: high
description: Error rate exceeded 5%
""".strip()
        + "\n",
        encoding="utf-8",
    )

    payloads = module._read_alert_file(source_file)

    assert len(payloads) == 2
    assert payloads[0]["source"] == "prometheus"
    assert payloads[0]["name"] == "OrdersReplicaLag"
    assert payloads[0]["severity"] == "critical"
    assert payloads[1]["source"] == "newrelic"
    assert payloads[1]["name"] == "Payments API Error Rate Spike"
    assert payloads[1]["severity"] == "high"
