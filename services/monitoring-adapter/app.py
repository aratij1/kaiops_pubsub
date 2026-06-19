from __future__ import annotations

import asyncio
from typing import Any

from common.config import get_settings
from common.models import Alert, AlertSeverity, Approval, ApprovalDecision
from common.service import create_app
from common.topics import RAW_ALERTS
from fastapi import Body, Header

ALERT_BODY = Body(...)

settings = get_settings()
settings.service_name = "monitoring-adapter"
app = create_app(title="KaiOps Monitoring Adapter", settings=settings)

SCENARIOS: dict[str, dict[str, Any]] = {
    "payment-latency": {
        "title": "Payment latency after deployment",
        "source": "prometheus",
        "name": "PaymentLatencyHigh",
        "service": "payments",
        "severity": AlertSeverity.CRITICAL,
        "description": "p95 latency above 1200ms for payments checkout path after Deployment 2.5",
        "labels": {"cluster": "prod-us-east-1", "deployment": "payments-api", "team": "payments-sre"},
        "annotations": {"summary": "Payment latency regression"},
        "root_cause": "Deployment 2.5",
        "impact": "Payment latency",
        "recommended_action": "Rollback deployment",
        "remediation_comment": "Rollback deployment",
    },
    "checkout-pod-crash": {
        "title": "Checkout pod crash loop",
        "source": "kubernetes",
        "name": "CheckoutPodCrashLoop",
        "service": "checkout",
        "severity": AlertSeverity.HIGH,
        "description": "checkout-api pods are crash looping after config reload",
        "labels": {"cluster": "prod-us-east-1", "deployment": "checkout-api", "team": "checkout-sre"},
        "annotations": {"summary": "Checkout pods restarting"},
        "root_cause": "Bad runtime config reload",
        "impact": "Checkout availability degradation",
        "recommended_action": "Restart pod",
        "remediation_comment": "Restart pod",
    },
    "inventory-cpu": {
        "title": "Inventory CPU saturation",
        "source": "datadog",
        "name": "InventoryCpuSaturation",
        "service": "inventory",
        "severity": AlertSeverity.HIGH,
        "description": "inventory service CPU above 92 percent during catalog sync",
        "labels": {"cluster": "prod-us-east-1", "deployment": "inventory-api", "team": "commerce-sre"},
        "annotations": {"summary": "Inventory CPU saturation"},
        "root_cause": "Catalog sync traffic spike",
        "impact": "Inventory lookup latency",
        "recommended_action": "Scale deployment",
        "remediation_comment": "Scale deployment",
    },
    "redis-cache": {
        "title": "Redis cache saturation",
        "source": "grafana",
        "name": "RedisCacheSaturation",
        "service": "cache",
        "severity": AlertSeverity.WARNING,
        "description": "redis cache memory pressure causing elevated misses",
        "labels": {"cluster": "prod-us-east-1", "deployment": "redis-cache", "team": "platform-sre"},
        "annotations": {"summary": "Cache memory pressure"},
        "root_cause": "Hot keys and stale cache entries",
        "impact": "API latency from cache misses",
        "recommended_action": "Clear cache",
        "remediation_comment": "Clear cache",
    },
    "database-replica-lag": {
        "title": "Database replica lag",
        "source": "azure monitor",
        "name": "DatabaseReplicaLag",
        "service": "orders-db",
        "severity": AlertSeverity.CRITICAL,
        "description": "orders database replica lag above 180 seconds",
        "labels": {"cluster": "prod-us-east-1", "deployment": "orders-postgres", "team": "database-sre"},
        "annotations": {"summary": "Replica lag impacting reads"},
        "root_cause": "Primary database write saturation",
        "impact": "Stale order reads",
        "recommended_action": "Failover database",
        "remediation_comment": "Failover database",
    },
    "auth-errors": {
        "title": "Authentication error spike",
        "source": "splunk",
        "name": "AuthErrorRateHigh",
        "service": "auth",
        "severity": AlertSeverity.HIGH,
        "description": "auth 5xx errors increased after secret rotation",
        "labels": {"cluster": "prod-us-east-1", "deployment": "auth-api", "team": "identity-sre"},
        "annotations": {"summary": "Auth failures after rotation"},
        "root_cause": "Secret rotation mismatch",
        "impact": "Login failures",
        "recommended_action": "Restart service",
        "remediation_comment": "Restart service",
    },
    "search-memory": {
        "title": "Search memory leak",
        "source": "prometheus",
        "name": "SearchMemoryHigh",
        "service": "search",
        "severity": AlertSeverity.HIGH,
        "description": "search service memory increasing steadily after index refresh",
        "labels": {"cluster": "prod-us-east-1", "deployment": "search-api", "team": "search-sre"},
        "annotations": {"summary": "Memory leak suspected"},
        "root_cause": "Index refresh memory leak",
        "impact": "Search latency and OOM risk",
        "recommended_action": "Restart service",
        "remediation_comment": "Restart service",
    },
    "billing-terraform": {
        "title": "Billing infrastructure regression",
        "source": "terraform",
        "name": "BillingInfraRegression",
        "service": "billing",
        "severity": AlertSeverity.CRITICAL,
        "description": "billing private endpoint unreachable after terraform apply",
        "labels": {"cluster": "prod-us-east-1", "deployment": "billing-network", "team": "finops-sre"},
        "annotations": {"summary": "Terraform network regression"},
        "root_cause": "Terraform security group change",
        "impact": "Billing job failures",
        "recommended_action": "Terraform rollback",
        "remediation_comment": "Terraform rollback",
    },
    "fraud-api": {
        "title": "Fraud API dependency timeout",
        "source": "datadog",
        "name": "FraudApiTimeouts",
        "service": "fraud",
        "severity": AlertSeverity.HIGH,
        "description": "fraud scoring API timeout rate above threshold",
        "labels": {"cluster": "prod-us-east-1", "deployment": "fraud-api", "team": "risk-sre"},
        "annotations": {"summary": "Fraud scoring timeouts"},
        "root_cause": "Dependency pool exhaustion",
        "impact": "Checkout risk checks delayed",
        "recommended_action": "API execution",
        "remediation_comment": "API execution",
    },
    "cdn-errors": {
        "title": "CDN error rate increase",
        "source": "grafana",
        "name": "CdnErrorRateHigh",
        "service": "cdn",
        "severity": AlertSeverity.WARNING,
        "description": "cdn 5xx error rate elevated in edge region",
        "labels": {"cluster": "global-edge", "deployment": "cdn-rules", "team": "edge-sre"},
        "annotations": {"summary": "Edge errors elevated"},
        "root_cause": "Bad edge rule propagation",
        "impact": "Static asset failures",
        "recommended_action": "API execution",
        "remediation_comment": "API execution",
    },
}


def list_scenarios() -> list[dict[str, str]]:
    return [
        {
            "id": scenario_id,
            "title": scenario["title"],
            "service": scenario["service"],
            "severity": scenario["severity"].value,
            "recommended_action": scenario["recommended_action"],
        }
        for scenario_id, scenario in SCENARIOS.items()
    ]


def build_sample_alert(flow_id: str = "payment-latency", trace_id: str | None = None) -> Alert:
    scenario = SCENARIOS.get(flow_id, SCENARIOS["payment-latency"])
    return Alert(
        source=scenario["source"],
        name=scenario["name"],
        service=scenario["service"],
        severity=scenario["severity"],
        description=scenario["description"],
        labels=scenario["labels"],
        annotations=scenario["annotations"],
        trace_id=trace_id,
    )


def build_payment_latency_alert(trace_id: str | None = None) -> Alert:
    return build_sample_alert("payment-latency", trace_id)


async def run_local_payment_workflow(
    trace_id: str | None = None,
    flow_id: str = "payment-latency",
    model_router: Any | None = None,
) -> dict[str, Any]:
    """Run the agent workflow in-process for local demos with Kafka disabled."""
    from alert_intelligence import AlertIntelligenceAgent
    from closure_service import ClosureValidationAgent
    from context_agent import ContextIntelligenceAgent
    from model_router import ModelRouter, ModelTask
    from orchestrator import OrchestratorAgent
    from remediation_engine import RemediationEngine
    from resolution_agent import ResolutionIntelligenceAgent

    scenario = SCENARIOS.get(flow_id, SCENARIOS["payment-latency"])
    router = model_router or ModelRouter()
    alert = build_sample_alert(flow_id, trace_id=trace_id)
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
    recommendation = await ResolutionIntelligenceAgent(model_router=router).resolve(context)
    recommendation.root_cause = scenario["root_cause"]
    recommendation.impact = scenario["impact"]
    recommendation.recommended_action = scenario["recommended_action"]
    recommendation.rationale = (
        f"Scenario evidence links {scenario['root_cause']} to {scenario['impact']}; "
        f"recommended action is {scenario['recommended_action']}."
    )
    recommendation.trace_id = trace_id
    model_usage = list(recommendation.metadata.get("model_usage", []))
    model_errors: list[dict[str, str]] = []
    comparison_calls = [
        (
            "gemini",
            ModelTask.SUMMARIZATION,
            "Summarize the incident for an executive FinOps and SRE audience",
        ),
        ("groq", ModelTask.GENERAL, "Generate a fast triage communication note"),
    ]
    comparison_payload = {
        "service": enriched_alert.service,
        "incident": incident.title,
        "root_cause": scenario["root_cause"],
        "recommended_action": scenario["recommended_action"],
    }
    comparison_results = await asyncio.gather(
        *[
            router.route_provider(
                provider_name=provider_name,
                task=task,
                prompt=prompt,
                payload=comparison_payload,
            )
            for provider_name, task, prompt in comparison_calls
        ],
        return_exceptions=True,
    )
    for (provider_name, task, _), result in zip(comparison_calls, comparison_results, strict=True):
        try:
            if isinstance(result, Exception):
                raise result
            model_usage.append(result["usage"])
        except Exception as exc:
            model_errors.append({"provider": provider_name, "task": task.value, "error": str(exc)})
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
    approval = Approval(
        incident_id=incident.id,
        recommendation_id=recommendation.id,
        decision=ApprovalDecision.APPROVED,
        approver="kaiops-demo",
        channel="web",
        comment=scenario["remediation_comment"],
        trace_id=trace_id,
    )
    approval_event = {
        "sequence": 5,
        "agent": "Human Approval Layer",
        "action": "Auto-approved demo recommendation",
        "input": recommendation.recommended_action,
        "decision": approval.decision.value,
        "output": f"Approved by {approval.approver} on {approval.channel}",
        "communicates_to": "Remediation Automation Engine via approval-events",
        "metrics": {"approval_required": decision.requires_approval, "channel": approval.channel},
    }
    engine = RemediationEngine()
    action = engine.build_action(approval)
    action.parameters.update({"root_cause": recommendation.root_cause, "impact": recommendation.impact})
    action = await engine.execute(action)
    action.trace_id = trace_id
    remediation_event = {
        "sequence": 6,
        "agent": "Remediation Automation Engine",
        "action": "Executed remediation strategy plugin",
        "input": approval.comment,
        "decision": f"Selected plugin action {action.action_type}",
        "output": action.output,
        "communicates_to": "Closure & Validation via remediation-events",
        "metrics": {"status": action.status.value, "target": action.target},
    }
    closure_report = await ClosureValidationAgent().validate(action)
    closure_report.trace_id = trace_id
    closure_event = {
        "sequence": 7,
        "agent": "Closure & Validation",
        "action": "Validated health and generated closure report",
        "input": action.output,
        "decision": "Health restored" if closure_report.health_restored else "Health not restored",
        "output": closure_report.knowledge_base_entry,
        "communicates_to": "Knowledge Base and audit log",
        "metrics": {
            "alerts_cleared": closure_report.alerts_cleared,
            "health_restored": closure_report.health_restored,
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
        "agent_handoffs": 6,
        "approval_required": decision.requires_approval,
        "remediation_status": action.status.value,
        "health_restored": closure_report.health_restored,
        "alerts_cleared": closure_report.alerts_cleared,
    }
    finops = build_finops_summary(model_usage, model_errors)

    return {
        "mode": "local-no-kafka",
        "scenario": {
            "id": flow_id,
            "title": scenario["title"],
            "recommended_action": scenario["recommended_action"],
        },
        "alert": enriched_alert,
        "incident": incident,
        "decision": decision.__dict__,
        "context": context,
        "recommendation": recommendation,
        "approval": approval,
        "remediation_action": action,
        "closure_report": closure_report,
        "metrics": metrics,
        "finops": finops,
        "events": [
            alert_event,
            orchestrator_event,
            context_event,
            resolution_event,
            approval_event,
            remediation_event,
            closure_event,
        ],
        "next_step": "Incident closed in local demo. Review closure report and lessons learned.",
    }


def build_finops_summary(model_usage: list[dict[str, Any]], model_errors: list[dict[str, str]]) -> dict[str, Any]:
    totals = {
        "input_tokens": sum(int(item.get("input_tokens", 0)) for item in model_usage),
        "output_tokens": sum(int(item.get("output_tokens", 0)) for item in model_usage),
        "total_tokens": sum(int(item.get("total_tokens", 0)) for item in model_usage),
        "total_cost_usd": round(sum(float(item.get("total_cost_usd", 0.0)) for item in model_usage), 8),
        "calls": len(model_usage),
        "failed_calls": len(model_errors),
    }
    by_provider: dict[str, dict[str, Any]] = {}
    for item in model_usage:
        provider = str(item.get("provider", "unknown"))
        row = by_provider.setdefault(
            provider,
            {"provider": provider, "calls": 0, "total_tokens": 0, "total_cost_usd": 0.0},
        )
        row["calls"] += 1
        row["total_tokens"] += int(item.get("total_tokens", 0))
        row["total_cost_usd"] = round(float(row["total_cost_usd"]) + float(item.get("total_cost_usd", 0.0)), 8)
    return {
        "totals": totals,
        "by_provider": list(by_provider.values()),
        "calls": model_usage,
        "errors": model_errors,
        "currency": "USD",
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


@app.get("/sample/flows")
async def sample_flows() -> dict[str, Any]:
    return {"flows": list_scenarios()}


@app.post("/sample/payment-latency/workflow")
async def sample_payment_latency_workflow(x_trace_id: str | None = Header(default=None)) -> dict[str, Any]:
    return await run_local_payment_workflow(trace_id=x_trace_id)


@app.post("/sample/{flow_id}/workflow")
async def sample_flow_workflow(flow_id: str, x_trace_id: str | None = Header(default=None)) -> dict[str, Any]:
    return await run_local_payment_workflow(trace_id=x_trace_id, flow_id=flow_id)
