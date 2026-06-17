from __future__ import annotations

from fastapi import Body

from common.config import get_settings
from common.models import Alert, AlertSeverity
from common.service import create_app
from common.topics import RAW_ALERTS

settings = get_settings()
settings.service_name = "monitoring-adapter"
app = create_app(title="KaiOps Monitoring Adapter", settings=settings)


@app.post("/alerts", response_model=Alert)
async def ingest_alert(payload: dict = Body(...)) -> Alert:
    alert = Alert(
        source=payload.get("source", payload.get("generatorURL", "unknown")),
        name=payload.get("name", payload.get("alertname", "unknown-alert")),
        service=payload.get("service", payload.get("labels", {}).get("service", "unknown")),
        environment=payload.get("environment", payload.get("labels", {}).get("env", "prod")),
        severity=AlertSeverity(payload.get("severity", payload.get("labels", {}).get("severity", "warning"))),
        description=payload.get("description", payload.get("annotations", {}).get("summary", "")),
        labels=payload.get("labels", {}),
        annotations=payload.get("annotations", {}),
    )
    await app.state.producer.publish(RAW_ALERTS, alert, key=alert.service)
    return alert


@app.post("/sample/payment-latency", response_model=Alert)
async def sample_payment_latency() -> Alert:
    alert = Alert(
        source="prometheus",
        name="PaymentLatencyHigh",
        service="payments",
        severity=AlertSeverity.CRITICAL,
        description="p95 latency above 1200ms for payments checkout path",
        labels={"cluster": "prod-us-east-1", "deployment": "payments-api"},
        annotations={"summary": "Payment latency regression"},
    )
    await app.state.producer.publish(RAW_ALERTS, alert, key=alert.service)
    return alert
