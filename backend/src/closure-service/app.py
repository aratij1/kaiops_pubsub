from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from datetime import datetime, timezone
from typing import Any

from closure_service import ClosureValidationAgent
from common.config import get_settings
from common.event_publishers import build_agent_event_contract, build_event_envelope
from common.kafka import KafkaConsumer, consume_forever as consume_kafka_forever
from common.models import Incident, IncidentStatus, RemediationAction, ResolutionReport
from common.rabbitmq import RabbitMQConsumer, consume_forever as consume_rabbitmq_forever
from common.repository import IncidentRepository
from common.service import create_app
from common.telemetry import EVENTS_PROCESSED
from common.topics import CLOSURE_EVENTS, REMEDIATION_EVENTS
from fastapi import FastAPI

settings = get_settings()
settings.service_name = "closure-service"
agent = ClosureValidationAgent()
tasks: list[asyncio.Task] = []

ConsumeRunner = Callable[[Any, Callable[[dict], Awaitable[None]]], Coroutine[Any, Any, None]]


def _extract_remediation_action_payload(payload: dict[str, Any]) -> dict[str, Any]:
    action = payload.get("remediation_action") if isinstance(payload, dict) else None
    if isinstance(action, dict):
        return action
    return payload


def _build_closure_event_payload(
    *,
    action: RemediationAction,
    report: ResolutionReport,
    source_payload: dict[str, Any],
) -> dict[str, Any]:
    incident_id = str(action.incident_id)
    source_contract = source_payload.get("event_contract", {}) if isinstance(source_payload.get("event_contract"), dict) else {}
    flow_id = str(source_contract.get("flow_id") or incident_id)
    trace_id = str(source_contract.get("trace_id") or "")
    correlation_id = str(source_contract.get("correlation_id") or "") or None

    event_contract = build_agent_event_contract(
        flow_id=flow_id,
        incident_id=incident_id,
        trace_id=trace_id,
        correlation_id=correlation_id,
        agent="closure-service",
        payload={
            "ticket_id": report.ticket_id,
            "action_taken": report.action_taken,
            "health_restored": report.health_restored,
            "alerts_cleared": report.alerts_cleared,
            "topic": CLOSURE_EVENTS,
        },
        metadata={
            "root_cause": report.root_cause,
            "impact": report.impact,
            "ticket_id": report.ticket_id,
        },
        confidence=1.0 if report.health_restored else 0.7,
        reasoning="closure validation derived from remediation outcome and health checks",
        citations=[f"report://{report.id}"],
        evidence_ids=[f"action:{action.id}", f"incident:{incident_id}"],
    )
    return {
        "report": report,
        "remediation_action": action,
        "event_contract": event_contract,
    }


def _resolve_closure_service_name(action: RemediationAction, incident_payload: dict[str, Any] | None) -> str:
    payload = incident_payload if isinstance(incident_payload, dict) else {}
    service = str(payload.get("service") or "").strip()
    if service:
        return service
    return str(action.target or "unknown").strip() or "unknown"


def _build_final_incident_payload(
    *,
    action: RemediationAction,
    report: ResolutionReport,
    incident_payload: dict[str, Any] | None,
    recommendation: dict[str, Any] | None,
    source_contract: dict[str, Any] | None,
) -> dict[str, Any]:
    incident_payload_map = incident_payload if isinstance(incident_payload, dict) else {}
    recommendation_map = recommendation if isinstance(recommendation, dict) else {}
    source_contract_map = source_contract if isinstance(source_contract, dict) else {}
    service_name = _resolve_closure_service_name(action, incident_payload_map)
    existing_metadata = incident_payload_map.get("metadata")
    final_payload = {
        "id": str(action.incident_id),
        "service": service_name,
        "environment": str(incident_payload_map.get("environment") or action.parameters.get("environment") or "prod"),
        "severity": str(incident_payload_map.get("severity") or recommendation_map.get("severity") or "warning").lower(),
        "status": IncidentStatus.CLOSED.value if report.health_restored else IncidentStatus.FAILED.value,
        "title": str(incident_payload_map.get("title") or f"Incident {action.incident_id}"),
        "summary": str(incident_payload_map.get("summary") or ""),
        "owner_team": incident_payload_map.get("owner_team"),
        "ticket_id": incident_payload_map.get("ticket_id"),
        "closed_at": datetime.now(timezone.utc).isoformat() if report.health_restored else incident_payload_map.get("closed_at"),
        "trace_id": str(
            incident_payload_map.get("trace_id")
            or source_contract_map.get("trace_id")
            or recommendation_map.get("trace_id")
            or ""
        ) or None,
        # Preserve persistence-critical fields that save_incident() would
        # otherwise silently reset to Pydantic defaults (metadata -> {},
        # created_at -> now, tenant_id -> "default"), wiping data set at
        # incident creation (incident_candidate/correlation_key, Jira,
        # deduplication, severity_policy, etc.).
        "metadata": existing_metadata if isinstance(existing_metadata, dict) else {},
        "created_at": incident_payload_map.get("created_at"),
        "tenant_id": incident_payload_map.get("tenant_id") or "default",
    }
    final_payload["alert_ids"] = incident_payload_map.get("alert_ids") if isinstance(incident_payload_map.get("alert_ids"), list) else []
    if final_payload["created_at"] is None:
        final_payload.pop("created_at")
    return final_payload


async def _sync_closure_to_jira(incident_payload: dict[str, Any], report: ResolutionReport) -> None:
    import os
    import logging
    import httpx

    logger = logging.getLogger("closure-service.jira-sync")

    ticket_id = str(incident_payload.get("ticket_id") or "").strip()
    if not ticket_id:
        logger.info("No Jira ticket linked to incident %s; skipping closure update", report.incident_id)
        return

    base_url = str(os.getenv("JIRA_API_BASE_URL", "") or os.getenv("JIRA_URL", "") or "").rstrip("/")
    email = str(os.getenv("JIRA_API_EMAIL", "") or os.getenv("JIRA_USER_EMAIL", "") or "")
    token = str(os.getenv("JIRA_API_TOKEN", "") or "")

    if not (base_url and email and token):
        logger.info("Jira outbound API is not fully configured; skipping closure sync on ticket %s", ticket_id)
        return

    auth = (email, token)
    headers = {"Content-Type": "application/json"}

    # 1. Post resolution comment
    lessons = "\n".join(f"- {lesson}" for lesson in report.lessons_learned) if report.lessons_learned else "- No additional lessons captured."
    comment_body = (
        "[kaiops-managed-closure]\n"
        "h2. Incident Resolved & Closed\n"
        "This incident has been automated resolved by KaiOps workflow.\n\n"
        "h3. Resolution Report\n"
        f"* *Root Cause*: {report.root_cause}\n"
        f"* *Impact*: {report.impact}\n"
        f"* *Action Taken*: {report.action_taken}\n"
        f"* *Health Restored*: {report.health_restored}\n"
        f"* *Alerts Cleared*: {report.alerts_cleared}\n"
        f"* *Validation Details*: {report.validation}\n\n"
        "h3. Lessons Learned\n"
        f"{lessons}\n"
    )

    try:
        async with httpx.AsyncClient(auth=auth, timeout=15.0) as client:
            # Post Comment
            comment_resp = await client.post(
                f"{base_url}/rest/api/2/issue/{ticket_id}/comment",
                json={"body": comment_body},
                headers=headers
            )
            if comment_resp.status_code >= 400:
                logger.error("Failed to post resolution comment to Jira ticket %s (%s): %s", ticket_id, comment_resp.status_code, comment_resp.text)
            else:
                logger.info("Successfully posted resolution comment to Jira ticket %s", ticket_id)

            # 2. Transition Jira ticket to Resolved / Done
            trans_resp = await client.get(
                f"{base_url}/rest/api/2/issue/{ticket_id}/transitions",
                headers=headers
            )
            if trans_resp.status_code >= 400:
                logger.error("Failed to fetch transitions for Jira ticket %s (%s): %s", ticket_id, trans_resp.status_code, trans_resp.text)
                return

            transitions = trans_resp.json().get("transitions", [])
            transition_id = None
            for t in transitions:
                name = str(t.get("name") or "").strip().lower()
                if name in {"done", "resolved", "closed", "resolve", "close", "resolve issue", "close issue"}:
                    transition_id = t.get("id")
                    break

            if transition_id:
                transition_resp = await client.post(
                    f"{base_url}/rest/api/2/issue/{ticket_id}/transitions",
                    json={"transition": {"id": transition_id}},
                    headers=headers
                )
                if transition_resp.status_code >= 400:
                    logger.error("Failed to transition Jira ticket %s to resolved state (%s): %s", ticket_id, transition_resp.status_code, transition_resp.text)
                else:
                    logger.info("Successfully transitioned Jira ticket %s to resolved state using transition id %s", ticket_id, transition_id)
            else:
                logger.warning("No matching transition found for closing Jira ticket %s (available: %s)", ticket_id, [t.get("name") for t in transitions])

    except Exception as exc:
        logger.exception("Error updating Jira closure for ticket %s: %s", ticket_id, exc)


async def _persist_closure_event(
    *,
    app: FastAPI,
    action: RemediationAction,
    report: ResolutionReport,
    source_payload: dict[str, Any],
) -> None:
    import logging
    logger = logging.getLogger("closure-service")
    if not settings.database_enabled or getattr(app.state, "session_factory", None) is None:
        return
    source_contract = source_payload.get("event_contract", {}) if isinstance(source_payload.get("event_contract"), dict) else {}
    source_recommendation = source_payload.get("source_payload", {}).get("recommendation") if isinstance(source_payload.get("source_payload"), dict) else {}
    recommendation = source_recommendation if isinstance(source_recommendation, dict) else {}
    status = "closed" if bool(report.health_restored) else "failed"

    async with app.state.session_factory() as session:
        repo = IncidentRepository(session)
        incident_payload = await repo.get_incident(str(action.incident_id)) or {}
        report.ticket_id = str(incident_payload.get("ticket_id") or "").strip() or None
        final_incident_payload = _build_final_incident_payload(
            action=action,
            report=report,
            incident_payload=incident_payload,
            recommendation=recommendation,
            source_contract=source_contract,
        )
        service_name = str(final_incident_payload.get("service") or "unknown")
        await repo.save_incident(Incident.model_validate(final_incident_payload))
        await repo.save_incident_event(
            build_event_envelope(
                event_type="incident.closure.completed",
                identity={
                    "incident_id": str(action.incident_id),
                    "alert_id": None,
                    "trace_id": str(source_contract.get("trace_id") or recommendation.get("trace_id") or ""),
                    "correlation_id": str(source_contract.get("correlation_id") or recommendation.get("correlation_id") or "") or None,
                    "causation_id": None,
                    "parent_event_id": None,
                },
                scope={
                    "tenant_id": "default",
                    "service": service_name,
                    "environment": "prod",
                    "region": None,
                    "team": None,
                },
                state={
                    "severity": str(recommendation.get("severity") or "warning").lower(),
                    "status": status,
                    "owner": None,
                },
                policy={
                    "risk_tier": "unknown",
                    "execution_mode": "unknown",
                    "requires_approval": None,
                    "policy_version": None,
                    "policy_reason": "closure validation completed",
                },
                transport={
                    "provider": "unknown",
                    "channel": CLOSURE_EVENTS,
                    "partition": None,
                    "offset": None,
                    "delivery_tag": None,
                },
                payload={
                    "report_id": str(report.id),
                    "remediation_action_id": str(action.id),
                    "action_taken": report.action_taken,
                    "health_restored": report.health_restored,
                    "alerts_cleared": report.alerts_cleared,
                },
            )
        )
        await session.commit()
        try:
            await _sync_closure_to_jira(incident_payload, report)
        except Exception:
            logger.exception("Failed to synchronize closure event to Jira ticket")


async def startup(app: FastAPI) -> None:
    workers = max(1, int(getattr(settings, "message_bus_worker_count", 1) or 1))
    consumers: list[tuple[str, Any, ConsumeRunner]] = []
    for worker in range(workers):
        consumers.append(
            (f"rabbitmq-w{worker + 1}", RabbitMQConsumer(settings, REMEDIATION_EVENTS), consume_rabbitmq_forever)
        )
    if settings.kafka_enabled:
        for worker in range(workers):
            consumers.insert(
                worker,
                (f"kafka-w{worker + 1}", KafkaConsumer(settings, REMEDIATION_EVENTS), consume_kafka_forever),
            )

    async def handle(payload: dict) -> None:
        action = RemediationAction.model_validate(_extract_remediation_action_payload(payload))
        report = await _validate_and_store(action)
        await _persist_closure_event(app=app, action=action, report=report, source_payload=payload)
        payload_out = _build_closure_event_payload(action=action, report=report, source_payload=payload)
        await app.state.producer.publish(CLOSURE_EVENTS, payload_out, key=str(action.incident_id))
        EVENTS_PROCESSED.labels(settings.service_name, REMEDIATION_EVENTS, "ok").inc()

    for source, consumer, consume_forever in consumers:
        task = asyncio.create_task(consume_forever(consumer, handle), name=f"closure-service-{source}-consumer")
        tasks.append(task)


async def shutdown(_: FastAPI) -> None:
    for task in tasks:
        task.cancel()


app = create_app(title="KaiMS Closure Service", settings=settings, startup=startup, shutdown=shutdown)


async def _validate_and_store(action: RemediationAction) -> ResolutionReport:
    report = await agent.validate(action)
    if settings.database_enabled:
        async with app.state.session_factory() as session:
            repo = IncidentRepository(session)
            incident_payload = await repo.get_incident(str(action.incident_id)) or {}
            report.ticket_id = str(incident_payload.get("ticket_id") or "").strip() or None
            await repo.save_report(report)
            await repo.save_knowledge_base(report)
            runbook_id = str(action.parameters.get("runbook_id") or "").strip()
            if runbook_id:
                await repo.record_runbook_execution_outcome(
                    runbook_id=runbook_id,
                    version=int(action.parameters.get("runbook_version") or 1),
                    successful=bool(report.health_restored and report.alerts_cleared),
                    modified=bool(action.parameters.get("operator_modified")),
                    actor=str(action.parameters.get("approved_by") or "closure-service"),
                    tenant_id=action.tenant_id or "default",
                    metadata=action.parameters,
                )
            await session.commit()
    return report


@app.post("/validate", response_model=ResolutionReport)
async def validate(action: RemediationAction) -> ResolutionReport:
    report = await _validate_and_store(action)
    await _persist_closure_event(app=app, action=action, report=report, source_payload={})
    return report
