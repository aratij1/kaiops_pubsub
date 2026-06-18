from __future__ import annotations

from typing import Any

from common.config import get_settings
from common.models import Alert, AlertSeverity
from common.service import create_app
from common.topics import RAW_ALERTS
from fastapi import Body, Header

ALERT_BODY = Body(...)

settings = get_settings()
settings.service_name = "monitoring-adapter"
app = create_app(title="KaiOps Monitoring Adapter", settings=settings)


def build_payment_latency_alert(trace_id: str | None = None) -> Alert:
    return Alert(
        source="prometheus",
        name="PaymentLatencyHigh",
        service="payments",
        severity=AlertSeverity.CRITICAL,
        description="p95 latency above 1200ms for payments checkout path",
        labels={"cluster": "prod-us-east-1", "deployment": "payments-api"},
        annotations={"summary": "Payment latency regression"},
        trace_id=trace_id,
    )


async def run_local_payment_workflow(trace_id: str | None = None) -> dict[str, Any]:
    """Run the agent workflow in-process for local demos with Kafka disabled."""
    from alert_intelligence import AlertIntelligenceAgent
    from context_agent import ContextIntelligenceAgent
    from orchestrator import OrchestratorAgent
    from resolution_agent import ResolutionIntelligenceAgent

    alert = build_payment_latency_alert(trace_id=trace_id)
    enriched_alert, incident = AlertIntelligenceAgent().process(alert)
    incident.trace_id = trace_id
    alert_event = {
        "sequence": 1,
        "agent": "Alert Intelligence Agent",
        "action": "Deduplicated, correlated, classified, and enriched alert",
        "input": "Prometheus sample alert",
        "decision": f"Severity classified as {enriched_alert.severity}; correlation ID {enriched_alert.correlation_id}",
        "output": "Created incident and enriched alert event",
        "communicates_to": "Orchestrator Agent via enriched-alerts",
        "metrics": {
            "deduplicated_count": enriched_alert.deduplicated_count,
            "metadata_fields": len(enriched_alert.metadata),
        },
    }
    decision = OrchestratorAgent().decide_workflow(enriched_alert, incident)
    orchestrator_event = {
        "sequence": 2,
        "agent": "Orchestrator Agent",
        "action": "Selected incident workflow and downstream agents",
        "input": f"Incident {incident.id} for service {incident.service}",
        "decision": decision.workflow,
        "output": f"Next action: {decision.next_action}; approval required: {decision.requires_approval}",
        "communicates_to": ", ".join(decision.downstream_agents),
        "metrics": {
            "downstream_agents": len(decision.downstream_agents),
            "requires_approval": decision.requires_approval,
        },
    }
    context = await ContextIntelligenceAgent().collect(enriched_alert, incident)
    context.trace_id = trace_id
    context_event = {
        "sequence": 3,
        "agent": "Context Intelligence Agent",
        "action": "Collected operational context and RAG evidence",
        "input": "Incident, alert, service, deployment labels",
        "decision": f"Most relevant deployment: {context.deployment}",
        "output": "Context object with runbook, related incidents, dependencies, metrics, and changes",
        "communicates_to": "Resolution Intelligence Agent via context-events",
        "metrics": {
            "related_incidents": len(context.related_incidents),
            "dependency_services": len(context.dependency_services),
            "recent_changes": len(context.recent_changes),
            "runbook_found": bool(context.runbook),
        },
    }
    recommendation = await ResolutionIntelligenceAgent().resolve(context)
    recommendation.trace_id = trace_id
    resolution_event = {
        "sequence": 4,
        "agent": "Resolution Intelligence Agent",
        "action": "Ran LangGraph RCA workflow",
        "input": "Collected context and alert severity",
        "decision": f"Root cause: {recommendation.root_cause}; action: {recommendation.recommended_action}",
        "output": "Recommendation with impact, rationale, commands, confidence, and risk",
        "communicates_to": "Human Approval Layer via resolution-events",
        "metrics": {
            "confidence": recommendation.confidence,
            "commands": len(recommendation.commands),
            "risk": recommendation.risk,
        },
    }
    metrics = {
        "alerts_processed": 1,
        "deduplicated_count": enriched_alert.deduplicated_count,
        "severity": enriched_alert.severity.value,
        "related_incidents": len(context.related_incidents),
        "dependency_services": len(context.dependency_services),
        "recent_changes": len(context.recent_changes),
        "recommendation_confidence": recommendation.confidence,
        "agent_handoffs": 3,
        "approval_required": decision.requires_approval,
    }

    return {
        "mode": "local-no-kafka",
        "alert": enriched_alert,
        "incident": incident,
        "decision": decision.__dict__,
        "context": context,
        "recommendation": recommendation,
        "metrics": metrics,
        "events": [alert_event, orchestrator_event, context_event, resolution_event],
        "next_step": "Approve, reject, or modify the recommendation in the Approval Workflow tab.",
    }


@app.post("/alerts", response_model=Alert)
async def ingest_alert(payload: dict = ALERT_BODY, x_trace_id: str | None = Header(default=None)) -> Alert:
    alert = Alert(
        source=payload.get("source", payload.get("generatorURL", "unknown")),
        name=payload.get("name", payload.get("alertname", "unknown-alert")),
        service=payload.get("service", payload.get("labels", {}).get("service", "unknown")),
        environment=payload.get("environment", payload.get("labels", {}).get("env", "prod")),
        severity=AlertSeverity(payload.get("severity", payload.get("labels", {}).get("severity", "warning"))),
        description=payload.get("description", payload.get("annotations", {}).get("summary", "")),
        labels=payload.get("labels", {}),
        annotations=payload.get("annotations", {}),
        trace_id=x_trace_id,
    )
    await app.state.producer.publish(RAW_ALERTS, alert, key=alert.service)
    return alert


@app.post("/sample/payment-latency", response_model=Alert)
async def sample_payment_latency(x_trace_id: str | None = Header(default=None)) -> Alert:
    alert = build_payment_latency_alert(trace_id=x_trace_id)
    await app.state.producer.publish(RAW_ALERTS, alert, key=alert.service)
    return alert


@app.post("/sample/payment-latency/workflow")
async def sample_payment_latency_workflow(x_trace_id: str | None = Header(default=None)) -> dict[str, Any]:
    return await run_local_payment_workflow(trace_id=x_trace_id)
