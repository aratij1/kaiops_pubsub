from __future__ import annotations

import asyncio
import json
import re
import time as _time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from common.config import get_settings
from common.database import create_engine, create_schema, create_session_factory
from common.models import Alert, AlertSeverity, Approval, ApprovalDecision, Recommendation
from common.repository import IncidentRepository
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

FLOW_CATALOG_FILE = "flows.json"
ONBOARDING_CONNECTIVITY_FILE = "onboarding/connectivity.json"

# ---------------------------------------------------------------------------
# In-process TTL caches
# ---------------------------------------------------------------------------
_SCENARIOS_CACHE_TTL: float = 60.0
_ONBOARDING_CACHE_TTL: float = 30.0
_scenarios_cache: dict[str, Any] = {}
_scenarios_cache_ts: float = 0.0
_onboarding_cache: dict[str, Any] = {}
_onboarding_cache_ts: float = 0.0


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "flow"


def rag_root_path() -> Path:
    here = Path(__file__).resolve()
    candidates = [here.parents[2] / "rag", Path.cwd() / "rag", Path("/app/rag")]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    fallback = candidates[0]
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def flow_catalog_path() -> Path:
    return rag_root_path() / FLOW_CATALOG_FILE


def onboarding_connectivity_path() -> Path:
    return rag_root_path() / ONBOARDING_CONNECTIVITY_FILE


def load_onboarding_connectivity() -> dict[str, Any]:
    global _onboarding_cache, _onboarding_cache_ts
    now = _time.monotonic()
    if _onboarding_cache and now - _onboarding_cache_ts < _ONBOARDING_CACHE_TTL:
        return dict(_onboarding_cache)
    path = onboarding_connectivity_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            _onboarding_cache = dict(payload)
            _onboarding_cache_ts = now
            return dict(payload)
    except (OSError, json.JSONDecodeError):
        return {}
    return {}


def save_onboarding_connectivity(payload: dict[str, Any]) -> dict[str, Any]:
    global _onboarding_cache, _onboarding_cache_ts
    path = onboarding_connectivity_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    sanitized = {
        "project": payload.get("project", {}),
        "prometheus_url": payload.get("prometheus_url", ""),
        "new_relic_url": payload.get("new_relic_url", ""),
        "datadog_url": payload.get("datadog_url", ""),
        "updated_at": payload.get("updated_at"),
    }
    path.write_text(json.dumps(sanitized, indent=2), encoding="utf-8")
    _onboarding_cache = dict(sanitized)
    _onboarding_cache_ts = _time.monotonic()
    return sanitized


def _normalize_project_name(project: dict[str, Any]) -> str:
    project_name = str(project.get("name", "")).strip()
    return project_name or "untitled-project"


def _normalize_provider_name(provider_name: str) -> str:
    return provider_name.strip().lower().replace(" ", "_")


async def persist_onboarding_connectivity(payload: dict[str, Any]) -> None:
    session_factory = getattr(app.state, "session_factory", None)
    if not settings.database_enabled or session_factory is None:
        return

    project = payload.get("project", {}) if isinstance(payload.get("project"), dict) else {}
    if not isinstance(project, dict):
        project = {}

    project_name = _normalize_project_name(project)
    provider_statuses = payload.get("provider_statuses", {}) if isinstance(payload.get("provider_statuses"), dict) else {}
    connectivity_payload = {
        "prometheus_url": str(payload.get("prometheus_url", "")).strip(),
        "new_relic_url": str(payload.get("new_relic_url", "")).strip(),
        "datadog_url": str(payload.get("datadog_url", "")).strip(),
        "updated_at": payload.get("updated_at"),
        "active_provider": _normalize_provider_name(str(payload.get("active_provider", ""))) if payload.get("active_provider") else None,
    }
    selected_provider = _normalize_provider_name(str(payload.get("active_provider", "project")))
    now = datetime.now(timezone.utc)

    async with session_factory() as session:
        repo = IncidentRepository(session)
        await repo.save_onboarding_state(
            project_name=project_name,
            provider_name="project",
            owner_team=str(project.get("owner_team", "")).strip() or None,
            environment=str(project.get("environment", "")).strip() or None,
            region=str(project.get("region", "")).strip() or None,
            endpoint_url=None,
            test_status="saved",
            test_message="Project configuration saved",
            project_payload=project,
            connectivity_payload=connectivity_payload,
            last_tested_at=None,
        )

        for provider_name, endpoint_key in (("prometheus", "prometheus_url"), ("new_relic", "new_relic_url"), ("datadog", "datadog_url")):
            provider_state = provider_statuses.get(provider_name, {}) if isinstance(provider_statuses, dict) else {}
            has_test_result = isinstance(provider_state, dict) and ("ok" in provider_state or "message" in provider_state)
            ok = bool(provider_state.get("ok", False)) if has_test_result else False
            message = None
            if has_test_result:
                message = str(provider_state.get("message", "")).strip() or None
            await repo.save_onboarding_state(
                project_name=project_name,
                provider_name=provider_name,
                owner_team=str(project.get("owner_team", "")).strip() or None,
                environment=str(project.get("environment", "")).strip() or None,
                region=str(project.get("region", "")).strip() or None,
                endpoint_url=str(payload.get(endpoint_key, "")).strip() or None,
                test_status="connected" if ok else ("failed" if has_test_result else None),
                test_message=message,
                project_payload=project,
                connectivity_payload={
                    "provider": provider_name,
                    "endpoint_url": str(payload.get(endpoint_key, "")).strip(),
                    "state": provider_state,
                    "selected_provider": selected_provider,
                    "updated_at": payload.get("updated_at"),
                },
                last_tested_at=now if has_test_result else None,
            )

        await session.commit()


def default_flow_catalog_entries() -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for scenario_id, scenario in SCENARIOS.items():
        entries.append(
            {
                "id": scenario_id,
                "alert_id": str(scenario.get("alert_id", "")).upper() or scenario_id.upper(),
                "alert_name": str(scenario.get("alert_name", scenario["title"])),
                "alert_type": str(scenario.get("alert_type", "")),
                "title": str(scenario["title"]),
                "service": str(scenario["service"]),
                "severity": str(scenario["severity"].value).upper(),
                "recommended_action": str(scenario["recommended_action"]),
                "description": str(scenario["description"]),
                "root_cause": str(scenario["root_cause"]),
                "impact": str(scenario["impact"]),
            }
        )
    return entries


def ensure_flow_catalog_exists() -> list[dict[str, str]]:
    path = flow_catalog_path()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return [item for item in data if isinstance(item, dict)]
        except (OSError, json.JSONDecodeError):
            pass
    entries = default_flow_catalog_entries()
    path.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    return entries


def severity_from_string(value: str | None) -> AlertSeverity:
    normalized = (value or "HIGH").strip().upper()
    mapping = {
        "CRITICAL": AlertSeverity.CRITICAL,
        "HIGH": AlertSeverity.HIGH,
        "WARNING": AlertSeverity.WARNING,
    }
    return mapping.get(normalized, AlertSeverity.HIGH)


def merged_scenarios() -> dict[str, dict[str, Any]]:
    global _scenarios_cache, _scenarios_cache_ts
    now = _time.monotonic()
    if _scenarios_cache and now - _scenarios_cache_ts < _SCENARIOS_CACHE_TTL:
        return dict(_scenarios_cache)
    scenarios: dict[str, dict[str, Any]] = dict(SCENARIOS)
    for item in ensure_flow_catalog_exists():
        title = str(item.get("title", "")).strip()
        if not title:
            continue
        flow_id = slugify(str(item.get("id") or title))
        service = str(item.get("service", "unknown")).strip() or "unknown"
        severity = severity_from_string(str(item.get("severity", "HIGH")))
        recommended_action = str(item.get("recommended_action", "Investigate issue")).strip() or "Investigate issue"
        description = str(item.get("description", f"Observed issue for service {service}")).strip()
        root_cause = str(item.get("root_cause", item.get("deployment", "Operational change"))).strip()
        impact = str(item.get("impact", title)).strip()

        scenarios[flow_id] = {
            "alert_id": str(item.get("alert_id", flow_id)).strip() or flow_id.upper(),
            "alert_name": title,
            "alert_type": str(item.get("alert_type", "")).strip(),
            "title": title,
            "source": str(item.get("source", "rag-catalog")),
            "name": str(item.get("name", f"{flow_id.replace('-', ' ').title().replace(' ', '')}Alert")),
            "service": service,
            "severity": severity,
            "description": description,
            "labels": {
                "cluster": str(item.get("cluster", "prod-us-east-1")),
                "deployment": str(item.get("deployment", service)),
                "team": str(item.get("team", f"{service}-sre")),
            },
            "annotations": {"summary": str(item.get("summary", title))},
            "root_cause": root_cause,
            "impact": impact,
            "recommended_action": recommended_action,
            "remediation_comment": str(item.get("remediation_comment", recommended_action)),
        }
    _scenarios_cache.clear()
    _scenarios_cache.update(scenarios)
    _scenarios_cache_ts = _time.monotonic()
    return dict(scenarios)


def list_scenarios() -> list[dict[str, str]]:
    scenarios = merged_scenarios()
    rows = [
        {
            "id": scenario_id,
            "alert_id": scenario.get("alert_id", scenario_id.upper()),
            "alert_name": scenario.get("alert_name", scenario["title"]),
            "alert_type": scenario.get("alert_type", ""),
            "title": scenario["title"],
            "service": scenario["service"],
            "severity": scenario["severity"].value,
            "recommended_action": scenario["recommended_action"],
        }
        for scenario_id, scenario in scenarios.items()
    ]
    return sorted(rows, key=lambda item: (str(item.get("service", "")).lower(), str(item.get("title", "")).lower()))


def build_sample_alert(flow_id: str = "payment-latency", trace_id: str | None = None) -> Alert:
    scenarios = merged_scenarios()
    scenario = scenarios.get(flow_id, scenarios["payment-latency"])
    return Alert(
        source=scenario["source"],
        name=str(scenario.get("alert_name") or scenario["name"]),
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
    run_comparison: bool = True,
) -> dict[str, Any]:
    """Run the agent workflow in-process for local demos with Kafka disabled."""
    from alert_intelligence import AlertIntelligenceAgent
    from closure_service import ClosureValidationAgent
    from context_agent import ContextIntelligenceAgent
    from model_router import ModelRouter, ModelTask
    from orchestrator import OrchestratorAgent
    from remediation_engine import RemediationEngine
    from resolution_agent import ResolutionIntelligenceAgent

    agent_order = [
        "Alert Intelligence Agent",
        "Orchestrator Agent",
        "Context Intelligence Agent",
        "Resolution Intelligence Agent",
        "Human Approval Layer",
        "Remediation Automation Engine",
        "Closure & Validation",
    ]

    async def persist_step(*operations: Any) -> None:
        session_factory = getattr(app.state, "session_factory", None)
        engine = None
        if not settings.database_enabled:
            return
        if session_factory is None:
            engine = create_engine(settings)
            session_factory = create_session_factory(engine)
            await create_schema(engine)
        try:
            async with session_factory() as session:
                repo = IncidentRepository(session)
                for operation in operations:
                    await operation(repo)
                await session.commit()
        finally:
            if engine is not None:
                await engine.dispose()

    def track_agent_work_operation(
        *,
        incident_id: Any,
        agent_name: str,
        work_item: str,
        status: str,
        sequence: int,
        trace_id: str | None,
        ticket_id: str | None,
        details: dict[str, Any] | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
    ):
        async def _operation(repo: IncidentRepository) -> None:
            await repo.save_agent_work_item(
                incident_id=incident_id,
                agent_name=agent_name,
                work_item=work_item,
                status=status,
                sequence=sequence,
                trace_id=trace_id,
                ticket_id=ticket_id,
                details=details or {},
                started_at=started_at,
                completed_at=completed_at,
            )

        return _operation

    scenarios = merged_scenarios()
    scenario = scenarios.get(flow_id, scenarios["payment-latency"])
    router = model_router or ModelRouter()
    alert = build_sample_alert(flow_id, trace_id=trace_id)
    enriched_alert, incident = AlertIntelligenceAgent().process(alert)
    incident.trace_id = trace_id
    await persist_step(lambda repo: repo.save_alert(enriched_alert), lambda repo: repo.save_incident(incident))
    now = datetime.now(timezone.utc)
    await persist_step(
        *[
            track_agent_work_operation(
                incident_id=incident.id,
                agent_name=agent_name,
                work_item="Assigned to incident workflow",
                status="pending",
                sequence=index,
                trace_id=trace_id,
                ticket_id=incident.ticket_id,
                details={"assigned_by": "orchestrator", "flow_id": flow_id},
                started_at=now,
                completed_at=None,
            )
            for index, agent_name in enumerate(agent_order, start=1)
        ]
    )
    alert_event = {
        "sequence": 1,
        "agent": "Alert Intelligence Agent",
        "action": "Deduplicated, correlated, classified, and enriched alert",
        "input": {
            "flow_id": flow_id,
            "source": alert.source,
            "name": alert.name,
            "service": alert.service,
            "severity": alert.severity.value,
            "description": alert.description,
            "labels": alert.labels,
            "annotations": alert.annotations,
        },
        "decision": f"Severity classified as {enriched_alert.severity}; correlation ID {enriched_alert.correlation_id}",
        "output": "Created incident and enriched alert event",
        "communicates_to": "Orchestrator Agent via enriched-alerts",
        "metrics": {
            "deduplicated_count": enriched_alert.deduplicated_count,
            "metadata_fields": len(enriched_alert.metadata),
        },
    }
    await persist_step(
        track_agent_work_operation(
            incident_id=incident.id,
            agent_name="Alert Intelligence Agent",
            work_item="Deduplicate, correlate, classify, and enrich alert",
            status="completed",
            sequence=1,
            trace_id=trace_id,
            ticket_id=incident.ticket_id,
            details={"decision": alert_event["decision"], "metrics": alert_event["metrics"]},
            started_at=now,
            completed_at=datetime.now(timezone.utc),
        )
    )
    context_task = asyncio.create_task(ContextIntelligenceAgent().collect(enriched_alert, incident))
    decision_task = asyncio.to_thread(OrchestratorAgent().decide_workflow, enriched_alert, incident)
    context, decision = await asyncio.gather(context_task, decision_task)
    context.trace_id = trace_id
    orchestrator_event = {
        "sequence": 2,
        "agent": "Orchestrator Agent",
        "action": "Selected incident workflow and downstream agents",
        "input": {
            "incident_id": incident.id,
            "service": incident.service,
            "severity": incident.severity.value,
            "title": incident.title,
        },
        "decision": decision.workflow,
        "output": f"Next action: {decision.next_action}; approval required: {decision.requires_approval}",
        "communicates_to": ", ".join(decision.downstream_agents),
        "metrics": {
            "downstream_agents": len(decision.downstream_agents),
            "requires_approval": decision.requires_approval,
        },
    }
    await persist_step(
        track_agent_work_operation(
            incident_id=incident.id,
            agent_name="Orchestrator Agent",
            work_item="Select workflow and downstream agents",
            status="completed",
            sequence=2,
            trace_id=trace_id,
            ticket_id=incident.ticket_id,
            details={"decision": orchestrator_event["decision"], "metrics": orchestrator_event["metrics"]},
            started_at=now,
            completed_at=datetime.now(timezone.utc),
        )
    )
    context_event = {
        "sequence": 3,
        "agent": "Context Intelligence Agent",
        "action": "Collected operational context and RAG evidence",
        "input": {
            "incident_id": incident.id,
            "alert_service": enriched_alert.service,
            "alert_severity": enriched_alert.severity.value,
            "deployment_label": enriched_alert.labels.get("deployment"),
            "trace_id": trace_id,
        },
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
    await persist_step(
        track_agent_work_operation(
            incident_id=incident.id,
            agent_name="Context Intelligence Agent",
            work_item="Collect context and RAG evidence",
            status="completed",
            sequence=3,
            trace_id=trace_id,
            ticket_id=incident.ticket_id,
            details={"decision": context_event["decision"], "metrics": context_event["metrics"]},
            started_at=now,
            completed_at=datetime.now(timezone.utc),
        )
    )
    model_errors: list[dict[str, str]] = []
    try:
        recommendation = await ResolutionIntelligenceAgent(model_router=router).resolve(context)
    except Exception as exc:
        recommendation = Recommendation(
            incident_id=incident.id,
            root_cause=scenario["root_cause"],
            confidence=0.72,
            impact=scenario["impact"],
            recommended_action=scenario["recommended_action"],
            severity=enriched_alert.severity,
            rationale=(
                "RCA model route failed; recommendation is based on retrieved RAG context "
                "and scenario evidence. See FinOps errors for provider details."
            ),
            commands=[],
            risk="high" if enriched_alert.severity == AlertSeverity.CRITICAL else "medium",
        )
        model_errors.append(
            {
                "provider": "router",
                "task": "resolution",
                "prompt": "Resolution Intelligence Agent LangGraph workflow",
                "payload": str({"alert": enriched_alert.description, "context": context.metadata}),
                "error": str(exc),
            }
        )
    recommendation.root_cause = scenario["root_cause"]
    recommendation.impact = scenario["impact"]
    recommendation.recommended_action = scenario["recommended_action"]
    recommendation.rationale = (
        f"Scenario evidence links {scenario['root_cause']} to {scenario['impact']}; "
        f"recommended action is {scenario['recommended_action']}."
    )
    recommendation.trace_id = trace_id
    await persist_step(lambda repo: repo.save_recommendation_as_audit(recommendation))
    model_usage = list(recommendation.metadata.get("model_usage", []))
    model_calls = list(recommendation.metadata.get("model_calls", []))
    if run_comparison:
        comparison_payload = {
            "service": enriched_alert.service,
            "incident": incident.title,
            "root_cause": scenario["root_cause"],
            "recommended_action": scenario["recommended_action"],
        }
        comparison_prompt = "Summarize root cause, impact, and next action in 2 concise operational sentences."
        comparison_candidates = ["gpt-5", "gpt-4o"]
        if settings.local_llm_enabled:
            comparison_candidates.append("local-llama")

        comparison_calls = [
            (provider_name, ModelTask.SUMMARIZATION, comparison_prompt)
            for provider_name in comparison_candidates
            if provider_name in router.providers
        ]
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
                model_calls.append(
                    {
                        "task": task.value,
                        "provider": provider_name,
                        "model": result["usage"].get("model"),
                        "prompt": next(prompt for name, _, prompt in comparison_calls if name == provider_name),
                        "payload": comparison_payload,
                        "response": result["content"],
                        "usage": result["usage"],
                    }
                )
            except Exception as exc:
                model_errors.append(
                    {
                        "provider": provider_name,
                        "task": task.value,
                        "prompt": next(prompt for name, _, prompt in comparison_calls if name == provider_name),
                        "payload": str(comparison_payload),
                        "error": str(exc),
                    }
                )
    resolution_event = {
        "sequence": 4,
        "agent": "Resolution Intelligence Agent",
        "action": "Ran LangGraph RCA workflow",
        "input": {
            "incident_id": incident.id,
            "severity": enriched_alert.severity.value,
            "deployment": context.deployment,
            "related_incidents": len(context.related_incidents),
        },
        "decision": f"Root cause: {recommendation.root_cause}; action: {recommendation.recommended_action}",
        "output": "Recommendation with impact, rationale, commands, confidence, and risk",
        "communicates_to": "Human Approval Layer via resolution-events",
        "metrics": {
            "confidence": recommendation.confidence,
            "commands": len(recommendation.commands),
            "risk": recommendation.risk,
        },
        "llm_calls": model_calls,
        "llm_errors": model_errors,
    }
    await persist_step(
        track_agent_work_operation(
            incident_id=incident.id,
            agent_name="Resolution Intelligence Agent",
            work_item="Run RCA and produce recommendation",
            status="completed",
            sequence=4,
            trace_id=trace_id,
            ticket_id=incident.ticket_id,
            details={"decision": resolution_event["decision"], "metrics": resolution_event["metrics"]},
            started_at=now,
            completed_at=datetime.now(timezone.utc),
        )
    )
    approval = Approval(
        incident_id=incident.id,
        recommendation_id=recommendation.id,
        decision=ApprovalDecision.APPROVED,
        approver="kaiops-demo",
        channel="web",
        comment=scenario["remediation_comment"],
        trace_id=trace_id,
    )
    await persist_step(lambda repo: repo.save_approval(approval))
    approval_event = {
        "sequence": 5,
        "agent": "Human Approval Layer",
        "action": "Auto-approved demo recommendation",
        "input": {
            "incident_id": incident.id,
            "recommendation_id": recommendation.id,
            "recommended_action": recommendation.recommended_action,
            "channel": approval.channel,
        },
        "decision": approval.decision.value,
        "output": f"Approved by {approval.approver} on {approval.channel}",
        "communicates_to": "Remediation Automation Engine via approval-events",
        "metrics": {"approval_required": decision.requires_approval, "channel": approval.channel},
    }
    await persist_step(
        track_agent_work_operation(
            incident_id=incident.id,
            agent_name="Human Approval Layer",
            work_item="Review and approve recommendation",
            status="completed",
            sequence=5,
            trace_id=trace_id,
            ticket_id=incident.ticket_id,
            details={"decision": approval_event["decision"], "metrics": approval_event["metrics"]},
            started_at=now,
            completed_at=datetime.now(timezone.utc),
        )
    )
    engine = RemediationEngine()
    action = engine.build_action(approval)
    action.parameters.update({"root_cause": recommendation.root_cause, "impact": recommendation.impact})
    action = await engine.execute(action)
    action.trace_id = trace_id
    await persist_step(lambda repo: repo.save_action(action))
    remediation_event = {
        "sequence": 6,
        "agent": "Remediation Automation Engine",
        "action": "Executed remediation strategy plugin",
        "input": {
            "approval_id": approval.id,
            "comment": approval.comment,
            "action_type": action.action_type,
            "target": action.target,
        },
        "decision": f"Selected plugin action {action.action_type}",
        "output": action.output,
        "communicates_to": "Closure & Validation via remediation-events",
        "metrics": {"status": action.status.value, "target": action.target},
    }
    await persist_step(
        track_agent_work_operation(
            incident_id=incident.id,
            agent_name="Remediation Automation Engine",
            work_item="Execute remediation strategy",
            status="completed" if action.status.value == "succeeded" else action.status.value,
            sequence=6,
            trace_id=trace_id,
            ticket_id=incident.ticket_id,
            details={"decision": remediation_event["decision"], "metrics": remediation_event["metrics"]},
            started_at=now,
            completed_at=datetime.now(timezone.utc),
        )
    )
    closure_report = await ClosureValidationAgent().validate(action)
    closure_report.trace_id = trace_id
    await persist_step(
        lambda repo: repo.save_report(closure_report),
        lambda repo: repo.save_knowledge_base(closure_report, service=incident.service),
    )
    closure_event = {
        "sequence": 7,
        "agent": "Closure & Validation",
        "action": "Validated health and generated closure report",
        "input": {
            "remediation_action_id": action.id,
            "status": action.status.value,
            "output": action.output,
        },
        "decision": "Health restored" if closure_report.health_restored else "Health not restored",
        "output": closure_report.knowledge_base_entry,
        "communicates_to": "Knowledge Base and audit log",
        "metrics": {
            "alerts_cleared": closure_report.alerts_cleared,
            "health_restored": closure_report.health_restored,
        },
    }
    await persist_step(
        track_agent_work_operation(
            incident_id=incident.id,
            agent_name="Closure & Validation",
            work_item="Validate recovery and close incident",
            status="completed" if closure_report.health_restored else "failed",
            sequence=7,
            trace_id=trace_id,
            ticket_id=incident.ticket_id,
            details={"decision": closure_event["decision"], "metrics": closure_event["metrics"]},
            started_at=now,
            completed_at=datetime.now(timezone.utc),
        )
    )
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
        "alert": enriched_alert.model_dump(mode="json"),
        "incident": incident.model_dump(mode="json"),
        "decision": decision.__dict__,
        "context": context.model_dump(mode="json"),
        "recommendation": recommendation.model_dump(mode="json"),
        "approval": approval.model_dump(mode="json"),
        "remediation_action": action.model_dump(mode="json"),
        "closure_report": closure_report.model_dump(mode="json"),
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


@app.get("/onboarding/connectivity")
async def get_onboarding_connectivity() -> dict[str, Any]:
    return {"connectivity": load_onboarding_connectivity()}


@app.get("/onboarding/state")
async def get_onboarding_state() -> dict[str, Any]:
    session_factory = getattr(app.state, "session_factory", None)
    if not settings.database_enabled or session_factory is None:
        return {"rows": []}

    async with session_factory() as session:
        repo = IncidentRepository(session)
        rows = await repo.list_onboarding_state()
    return {"rows": rows}


@app.get("/agent-work/items")
async def get_agent_work_items(limit: int = 100) -> dict[str, Any]:
    session_factory = getattr(app.state, "session_factory", None)
    if not settings.database_enabled or session_factory is None:
        return {"rows": []}

    async with session_factory() as session:
        repo = IncidentRepository(session)
        rows = await repo.list_agent_work_items(limit=limit)
    return {"rows": rows}


@app.post("/onboarding/connectivity")
async def post_onboarding_connectivity(payload: dict[str, Any] = ALERT_BODY) -> dict[str, Any]:
    sanitized = save_onboarding_connectivity(payload)
    await persist_onboarding_connectivity(payload)
    return {"connectivity": sanitized}


@app.post("/sample/payment-latency/workflow")
async def sample_payment_latency_workflow(
    fast_mode: bool = False,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await run_local_payment_workflow(trace_id=x_trace_id, run_comparison=not fast_mode)


@app.post("/sample/{flow_id}/workflow")
async def sample_flow_workflow(
    flow_id: str,
    fast_mode: bool = False,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await run_local_payment_workflow(trace_id=x_trace_id, flow_id=flow_id, run_comparison=not fast_mode)
