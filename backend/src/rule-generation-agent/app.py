from __future__ import annotations

import asyncio
from time import perf_counter
from typing import Any

import httpx
from common.config import get_settings
from common.logging import get_logger
from common.models import ApplicationRegistration, MetricsValidationResult, MonitoringAuditEvent, RulesGeneratedResult
from common.monitoring_onboarding import RuleGenerationAgent, application_from_row
from common.rabbitmq import RabbitMQConsumer, consume_forever as consume_rabbitmq_forever
from common.repository import IncidentRepository
from common.service import create_app
from common.telemetry import ONBOARDING_SUCCESS, RULE_GENERATION_DURATION
from common.topics import APPLICATION_METRICS_VALIDATED, APPLICATION_RULES_GENERATED
from fastapi import FastAPI

settings = get_settings()
settings.service_name = "rule-generation-agent"
logger = get_logger(__name__)
agent = RuleGenerationAgent()
tasks: list[asyncio.Task] = []

_SEVERITY_RANK = {"critical": 3, "high": 2, "warning": 1, "info": 0}

_RULE_GUIDANCE = {
    "target-down": [
        "Confirm the service process is running and healthy.",
        "Check recent deploys/restarts for this service.",
        "Verify network connectivity between Prometheus and the target.",
    ],
    "cpu-high": [
        "Inspect recent traffic spikes or inefficient code paths.",
        "Check for runaway background jobs or retry storms.",
        "Consider scaling out if load is legitimate.",
    ],
    "memory-high": [
        "Check for memory leaks via recent deploys.",
        "Inspect cache sizes and unbounded in-memory collections.",
        "Consider a rolling restart if growth is unbounded.",
    ],
    "latency-p95-high": [
        "Check downstream dependency latency (DB, cache, upstream APIs).",
        "Inspect recent deploys for regressions.",
        "Review connection pool / thread pool saturation.",
    ],
    "http-5xx-rate": [
        "Check application error logs for stack traces.",
        "Verify downstream dependency health.",
        "Roll back the most recent deployment if errors started after it.",
    ],
}


def _rule_kind(rule_name: str, slug: str) -> str:
    suffix = rule_name[len(slug) + 1 :] if rule_name.startswith(f"{slug}-") else rule_name
    return suffix


async def _discover_similar_ticket_context(
    application: ApplicationRegistration,
    result: RulesGeneratedResult,
) -> list[dict[str, Any]]:
    """Retrieve incident/ticket evidence without using existing runbooks as source context."""
    rule_terms = " ".join(
        str((rule.annotations or {}).get("summary") or rule.name)
        for rule in result.alert_rules[:8]
    )
    query = " ".join(
        part
        for part in (
            application.name,
            application.environment,
            application.technology,
            application.namespace,
            rule_terms,
        )
        if str(part or "").strip()
    )
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            search_response = await client.get(
                f"{settings.context_agent_url}/rag/search",
                params={"query": query, "kind": "incident", "limit": 5},
            )
            search_response.raise_for_status()
            matches = search_response.json().get("matches", [])
            tickets: list[dict[str, Any]] = []
            for match in matches[:3]:
                if str(match.get("kind") or "").strip().lower() != "incident":
                    continue
                path = str(match.get("path") or "").strip()
                if not path:
                    continue
                detail_response = await client.get(
                    f"{settings.context_agent_url}/rag/documents/content",
                    params={"path": path},
                )
                detail_response.raise_for_status()
                detail = detail_response.json()
                tickets.append(
                    {
                        "title": str(detail.get("title") or match.get("title") or "Historical incident"),
                        "summary": str(detail.get("summary") or "").strip(),
                        "content": str(detail.get("content") or "").strip(),
                        "path": path,
                        "score": float(match.get("score") or 0.0),
                    }
                )
            return tickets
    except Exception as exc:
        logger.warning(
            "similar ticket discovery failed; using baseline rule guidance",
            extra={"application": application.name, "error": str(exc)},
        )
        return []


def _build_runbook_document_payload(
    application: ApplicationRegistration,
    result: RulesGeneratedResult,
    similar_tickets: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    slug = str(application.name or "").strip().lower().replace(" ", "-") or "application"
    similar_tickets = similar_tickets or []
    highest_severity = "info"
    sections: list[str] = [
        f"Auto-generated monitoring runbook for **{application.name}**.",
        "",
        f"- Tenant: {application.tenant_id}",
        f"- Environment: {application.environment}",
        f"- Namespace: {application.namespace}",
        f"- Owner team: {application.owner_team}",
        "",
        "## Historical Ticket Context",
    ]
    if similar_tickets:
        sections.append(
            "The following similar resolved incidents were discovered before this runbook was generated:"
        )
        for ticket in similar_tickets:
            evidence = str(ticket.get("summary") or ticket.get("content") or "").strip()
            evidence = " ".join(evidence.split())[:700]
            sections.append(f"### {ticket.get('title') or 'Historical incident'}")
            sections.append(f"- Similarity: {float(ticket.get('score') or 0.0):.3f}")
            sections.append(f"- Evidence: {evidence or 'Historical incident metadata matched this service and alert pattern.'}")
            sections.append(f"- Source ticket: `{ticket.get('path') or 'unknown'}`")
            sections.append("")
    else:
        sections.append(
            "No sufficiently similar historical ticket was found. Baseline troubleshooting guidance is used and must be reviewed after the first resolved incident."
        )
        sections.append("")
    sections.extend([
        "## Alert Rules",
    ])
    for rule in result.alert_rules:
        severity = str(rule.severity or "warning").strip().lower()
        if _SEVERITY_RANK.get(severity, 0) > _SEVERITY_RANK.get(highest_severity, 0):
            highest_severity = severity
        kind = _rule_kind(rule.name, slug)
        guidance = _RULE_GUIDANCE.get(kind, ["Check the affected service's logs and recent changes."])
        annotations = rule.annotations or {}
        sections.append(f"### {rule.name} ({severity})")
        sections.append(f"- Condition: `{rule.expr}` for `{rule.duration}`")
        if annotations.get("summary"):
            sections.append(f"- Summary: {annotations['summary']}")
        if annotations.get("description"):
            sections.append(f"- Description: {annotations['description']}")
        sections.append("- Troubleshooting steps:")
        sections.extend(f"  - {step}" for step in guidance)
        sections.append("")

    content = "\n".join(sections).strip()
    return {
        "kind": "runbook",
        "title": f"Runbook - {application.name}",
        "summary": f"Auto-generated monitoring runbook for {application.name} ({application.environment}).",
        "content": content,
        "services": [application.name],
        "severity": highest_severity or "high",
        "alert_type": f"{slug}-monitoring",
        "metadata": {
            "tenant_id": str(application.tenant_id or ""),
            "environment": str(application.environment or ""),
            "namespace": str(application.namespace or ""),
            "source": "rule-generation-agent",
            "application_id": str(application.id),
            "context_strategy": "similar-historical-tickets-first",
            "historical_ticket_count": len(similar_tickets),
            "historical_ticket_paths": [str(ticket.get("path") or "") for ticket in similar_tickets],
        },
    }


async def _publish_runbook_document(application: ApplicationRegistration, result: RulesGeneratedResult) -> None:
    """Best-effort: writes a runbook document for the generated rules so the
    newer application-onboarding pipeline produces documentation just like
    the existing rule-onboarding flow does. Never raises - a failure here
    must not break rule generation, which is this service's primary job."""
    if not result.alert_rules:
        return
    similar_tickets = await _discover_similar_ticket_context(application, result)
    payload = _build_runbook_document_payload(application, result, similar_tickets)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(f"{settings.context_agent_url}/rag/documents", json=payload)
            response.raise_for_status()
        logger.info("runbook document created", extra={"application": application.name})
    except Exception as exc:
        logger.warning(
            "failed to create runbook document for application; continuing without it",
            extra={"application": application.name, "error": str(exc)},
        )


async def startup(app: FastAPI) -> None:
    async def handle(payload: dict) -> None:
        started = perf_counter()
        validation = MetricsValidationResult.model_validate(payload)
        session_factory = getattr(app.state, "session_factory", None)
        if session_factory is None:
            raise RuntimeError("session factory unavailable")
        async with session_factory() as session:
            repo = IncidentRepository(session)
            row = await repo.get_application(validation.application_id)
            if row is None:
                logger.warning("rule generation skipped; application missing", extra={"application_id": str(validation.application_id)})
                return
            application = application_from_row(row)
            discovery_payload = ((row.get("payload") or {}).get("discovery") or {}) if isinstance(row.get("payload"), dict) else {}
            from common.models import ApplicationDiscoveryResult

            discovery = ApplicationDiscoveryResult.model_validate(discovery_payload or {
                "application_id": str(validation.application_id),
                "tenant_id": application.tenant_id,
                "name": application.name,
                "environment": application.environment,
                "namespace": application.namespace,
                "technology": application.technology,
                "metrics_endpoint": application.metrics_endpoint,
                "labels": application.labels,
            })
            result = await agent.run(application, discovery, validation)
            await repo.replace_rules(result)
            await repo.update_application_status(application.id, status=str(result.status), payload={"rules_generation": result.model_dump(mode="json")})
            await repo.save_monitoring_audit(
                MonitoringAuditEvent(
                    application_id=application.id,
                    tenant_id=application.tenant_id,
                    event_type=APPLICATION_RULES_GENERATED,
                    actor="system",
                    agent="rule-generation-agent",
                    decision=str(result.governance.get("decision") or "approved"),
                    execution_time_ms=(perf_counter() - started) * 1000.0,
                    input=validation.model_dump(mode="json"),
                    output=result.model_dump(mode="json"),
                )
            )
            await session.commit()
        await _publish_runbook_document(application, result)
        await app.state.producer.publish(APPLICATION_RULES_GENERATED, result.model_dump(mode="json"), key=str(validation.application_id))
        RULE_GENERATION_DURATION.labels(settings.service_name, "prometheus").observe(max(0.0, perf_counter() - started))
        ONBOARDING_SUCCESS.labels(settings.service_name, "rules_generation").inc()

    consumer = RabbitMQConsumer(settings, APPLICATION_METRICS_VALIDATED)
    tasks.append(asyncio.create_task(consume_rabbitmq_forever(consumer, handle), name="rule-generation-consumer"))


async def shutdown(_: FastAPI) -> None:
    for task in tasks:
        task.cancel()


app = create_app(title="KaiOps Rule Generation Agent", settings=settings, startup=startup, shutdown=shutdown)
