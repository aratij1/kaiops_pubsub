from __future__ import annotations

from typing import Any

from common.config import get_settings
from common.models import Alert, AlertSeverity
from common.service import create_app
from common.topics import RAW_ALERTS
from fastapi import Body

ALERT_BODY = Body(...)

settings = get_settings()
settings.service_name = "monitoring-adapter"
app = create_app(title="KaiOps Monitoring Adapter", settings=settings)


def build_payment_latency_alert() -> Alert:
    return Alert(
        source="prometheus",
        name="PaymentLatencyHigh",
        service="payments",
        severity=AlertSeverity.CRITICAL,
        description="p95 latency above 1200ms for payments checkout path",
        labels={"cluster": "prod-us-east-1", "deployment": "payments-api"},
        annotations={"summary": "Payment latency regression"},
    )


async def run_local_payment_workflow() -> dict[str, Any]:
    """Run the agent workflow in-process for local demos with Kafka disabled."""
    from alert_intelligence import AlertIntelligenceAgent
    from context_agent import ContextIntelligenceAgent
    from orchestrator import OrchestratorAgent
    from resolution_agent import ResolutionIntelligenceAgent

    alert = build_payment_latency_alert()
    enriched_alert, incident = AlertIntelligenceAgent().process(alert)
    decision = OrchestratorAgent().decide_workflow(enriched_alert, incident)
    context = await ContextIntelligenceAgent().collect(enriched_alert, incident)
    recommendation = await ResolutionIntelligenceAgent().resolve(context)

    return {
        "mode": "local-no-kafka",
        "alert": enriched_alert,
        "incident": incident,
        "decision": decision.__dict__,
        "context": context,
        "recommendation": recommendation,
        "next_step": "Approve, reject, or modify the recommendation in the Approval Workflow tab.",
    }


@app.post("/alerts", response_model=Alert)
async def ingest_alert(payload: dict = ALERT_BODY) -> Alert:
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
    alert = build_payment_latency_alert()
    await app.state.producer.publish(RAW_ALERTS, alert, key=alert.service)
    return alert


@app.post("/sample/payment-latency/workflow")
async def sample_payment_latency_workflow() -> dict[str, Any]:
    return await run_local_payment_workflow()
