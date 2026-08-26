from __future__ import annotations

import asyncio
import hmac
import json
import logging
from collections.abc import Awaitable, Callable, Coroutine
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from closure_service import ClosureValidationAgent
from closure_service.reconciliation import ReconciliationDecision, assess_terminal_action
from common.config import get_settings
from common.authorization import OperationalRole, role_is_allowed
from common.event_publishers import build_agent_event_contract, build_event_envelope, normalize_payload
from common.kafka import KafkaConsumer, consume_forever as consume_kafka_forever
from common.models import Incident, IncidentStatus, RemediationAction, RemediationStatus, ResolutionReport
from common.resolution_lifecycle import LifecycleActor, ResolutionState, create_lifecycle, extract_lifecycle, transition_lifecycle
from common.rabbitmq import RabbitMQConsumer, consume_forever as consume_rabbitmq_forever
from common.repository import IncidentRepository
from common.service import create_app
from common.telemetry import EVENTS_PROCESSED, LIFECYCLE_RECONCILIATION
from common.topics import CLOSURE_EVENTS, REMEDIATION_EVENTS
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

settings = get_settings()
settings.service_name = "closure-service"
agent = ClosureValidationAgent()
tasks: list[asyncio.Task] = []
logger = logging.getLogger("closure-service")

ConsumeRunner = Callable[[Any, Callable[[dict], Awaitable[None]]], Coroutine[Any, Any, None]]


def _reconciliation_mode() -> str:
    configured = str(getattr(settings, "closure_reconciliation_mode", "apply") or "apply").strip().lower()
    if configured not in {"preview", "apply"}:
        logger.warning("Invalid closure reconciliation mode; using apply", extra={"configured_mode": configured})
        return "apply"
    return configured


async def _load_terminal_action_candidates(app: FastAPI, *, limit: int) -> list[tuple[Any, str, str]]:
    session_factory = getattr(app.state, "session_factory", None)
    if not settings.database_enabled or session_factory is None:
        return []
    async with session_factory() as session:
        result = await session.execute(
            text(
                "SELECT a.payload, p.status, "
                "CASE WHEN a.action_type='diagnostic_completion' THEN 'diagnostic-startup-reconcile' "
                "ELSE 'successful-action-startup-reconcile' END AS replay_source "
                "FROM actions a JOIN incident_projections p ON p.incident_id=a.incident_id "
                "WHERE p.status NOT IN ('closed','resolved','cancelled','canceled') AND ("
                "(a.action_type='diagnostic_completion' AND a.status='skipped') OR "
                "(a.status='succeeded' AND p.status IN "
                "('approved','remediating','validating','investigating','awaiting_approval','failed'))) "
                "ORDER BY a.updated_at DESC LIMIT :reconciliation_limit"
            ),
            {"reconciliation_limit": max(1, min(int(limit), 1000))},
        )
        return list(result.all())


async def _reconcile_terminal_actions(app: FastAPI) -> dict[str, Any]:
    mode = _reconciliation_mode()
    limit = max(1, min(int(getattr(settings, "closure_reconciliation_batch_size", 100) or 100), 1000))
    rows = await _load_terminal_action_candidates(app, limit=limit)
    summary: dict[str, Any] = {"mode": mode, "candidate_count": len(rows), "replayed": 0, "decisions": {}}
    for stored_payload, projection_status, replay_source in rows:
        try:
            payload_map = stored_payload if isinstance(stored_payload, dict) else json.loads(str(stored_payload))
            action = RemediationAction.model_validate(payload_map)
            assessment = assess_terminal_action(action, projection_status)
            decision = assessment.decision.value
            summary["decisions"][decision] = int(summary["decisions"].get(decision, 0)) + 1
            LIFECYCLE_RECONCILIATION.labels(mode, decision, assessment.reason).inc()
            if mode != "apply" or assessment.decision != ReconciliationDecision.REPLAY:
                continue
            replay_payload = {"remediation_action": action.model_dump(mode="json"), "source": replay_source}
            report = await _validate_and_store(action)
            payload_out = _build_closure_event_payload(action=action, report=report, source_payload=replay_payload)
            persistence = await _persist_closure_event(
                app=app,
                action=action,
                report=report,
                source_payload=replay_payload,
                event_payload=payload_out,
            )
            if persistence.get("outbox_enqueued"):
                await _publish_closure_event(app, payload_out, key=str(action.incident_id))
                summary["replayed"] += 1
                EVENTS_PROCESSED.labels(settings.service_name, REMEDIATION_EVENTS, "terminal-action-reconciled").inc()
        except Exception:
            LIFECYCLE_RECONCILIATION.labels(mode, "error", "candidate_processing_failed").inc()
            logger.exception("failed to reconcile persisted terminal action", extra={"replay_source": replay_source})
    logger.info("terminal action reconciliation completed", extra={"reconciliation": summary})
    return summary


def _closure_outbox_event_id(payload: dict[str, Any], action: RemediationAction) -> str:
    contract = payload.get("event_contract") if isinstance(payload.get("event_contract"), dict) else {}
    return str(contract.get("event_id") or f"closure:{action.id}")


async def _mark_outbox_result(app: FastAPI, event_id: str, *, error: Exception | None = None) -> None:
    if not settings.database_enabled or getattr(app.state, "session_factory", None) is None:
        return
    async with app.state.session_factory() as session:
        repo = IncidentRepository(session)
        if error is None:
            await repo.mark_resolution_event_published(event_id)
        else:
            await repo.mark_resolution_event_retry(event_id, str(error))
        await session.commit()


async def _publish_closure_event(app: FastAPI, payload: dict[str, Any], *, key: str) -> None:
    event_id = str((payload.get("event_contract") or {}).get("event_id") or "")
    try:
        await app.state.producer.publish(CLOSURE_EVENTS, payload, key=key)
    except Exception as exc:
        if event_id:
            await _mark_outbox_result(app, event_id, error=exc)
        raise
    if event_id:
        await _mark_outbox_result(app, event_id)


async def _flush_resolution_outbox(app: FastAPI) -> int:
    if not settings.database_enabled or getattr(app.state, "session_factory", None) is None:
        return 0
    published = 0
    async with app.state.session_factory() as session:
        lock_acquired = await session.scalar(text("SELECT GET_LOCK('kaiops_resolution_outbox_dispatch', 0)"))
        if int(lock_acquired or 0) != 1:
            return 0
        try:
            repo = IncidentRepository(session)
            rows = await repo.list_pending_resolution_events(
                limit=int(getattr(settings, "resolution_outbox_batch_size", 100) or 100)
            )
            for row in rows:
                try:
                    await app.state.producer.publish(row.topic, row.payload, key=row.partition_key)
                    await repo.mark_resolution_event_published(row.event_id)
                    published += 1
                except Exception as exc:
                    await repo.mark_resolution_event_retry(row.event_id, str(exc))
                await session.commit()
        finally:
            await session.execute(text("SELECT RELEASE_LOCK('kaiops_resolution_outbox_dispatch')"))
            await session.commit()
    return published


async def _outbox_dispatch_loop(app: FastAPI) -> None:
    interval = max(1.0, float(getattr(settings, "resolution_outbox_poll_seconds", 5.0) or 5.0))
    while True:
        try:
            await _flush_resolution_outbox(app)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("resolution outbox dispatch failed")
        await asyncio.sleep(interval)


async def _terminal_action_reconciliation_loop(app: FastAPI) -> None:
    """Continuously repair lost or out-of-order terminal handoffs.

    The candidate assessor only replays explicit diagnostic completion or a
    successful action with signed recovery proof. This makes apply mode safe
    for normal operation while ensuring a transient broker/projection race
    cannot leave an incident at Validate indefinitely.
    """
    interval = max(
        5.0,
        float(getattr(settings, "closure_reconciliation_interval_seconds", 15.0) or 15.0),
    )
    while True:
        await asyncio.sleep(interval)
        try:
            await _reconcile_terminal_actions(app)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("terminal action reconciliation loop failed")


def _extract_remediation_action_payload(payload: dict[str, Any]) -> dict[str, Any]:
    action = payload.get("remediation_action") if isinstance(payload, dict) else None
    if isinstance(action, dict):
        return action
    return payload


def _is_diagnostic_report(report: ResolutionReport) -> bool:
    return str(report.metadata.get("closure_kind") or "").strip().lower() == "diagnostic"


def _is_diagnostic_closure(report: ResolutionReport) -> bool:
    return _is_diagnostic_report(report) and report.metadata.get("watch_only_authorized") is True


def _is_manual_closure(report: ResolutionReport) -> bool:
    return str(report.metadata.get("closure_kind") or "").strip().lower() == "manual"


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
    closure_outcome = (
        "closed"
        if report.health_restored or _is_diagnostic_closure(report) or _is_manual_closure(report)
        else "diagnostic_recorded"
        if _is_diagnostic_report(report)
        else "validation_failed"
    )
    event_contract["event_id"] = f"closure:{action.id}:{closure_outcome}"
    return {
        "report": report,
        "remediation_action": action,
        "resolution_lifecycle": extract_lifecycle(report.metadata, action.parameters, action.metadata),
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
    diagnostic_report = _is_diagnostic_report(report)
    diagnostic_closure = _is_diagnostic_closure(report)
    manual_closure = _is_manual_closure(report)
    closure_complete = bool(report.health_restored or diagnostic_closure or manual_closure)
    existing_status = str(incident_payload_map.get("status") or IncidentStatus.INVESTIGATING.value).lower()
    final_status = (
        IncidentStatus.CLOSED.value
        if closure_complete
        else existing_status
        if diagnostic_report
        else IncidentStatus.FAILED.value
    )
    final_payload = {
        "id": str(action.incident_id),
        "service": service_name,
        "environment": str(incident_payload_map.get("environment") or action.parameters.get("environment") or "prod"),
        "severity": str(incident_payload_map.get("severity") or recommendation_map.get("severity") or "warning").lower(),
        "status": final_status,
        "title": str(incident_payload_map.get("title") or f"Incident {action.incident_id}"),
        "summary": str(incident_payload_map.get("summary") or ""),
        "owner_team": incident_payload_map.get("owner_team"),
        "ticket_id": incident_payload_map.get("ticket_id"),
        "closed_at": datetime.now(timezone.utc).isoformat() if closure_complete else incident_payload_map.get("closed_at"),
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
    lifecycle = extract_lifecycle(
        report.metadata,
        action.parameters,
        action.metadata,
        recommendation_map,
        incident_payload_map.get("metadata"),
    ) or create_lifecycle(
        tenant_id=action.tenant_id,
        incident_id=action.incident_id,
        recommendation_id=(
            action.parameters.get("recommendation_id")
            or recommendation_map.get("id")
            or "legacy-unavailable"
        ),
        plan=action.parameters.get("execution_plan") if isinstance(action.parameters.get("execution_plan"), dict) else {},
        state=ResolutionState.DIAGNOSTIC_ONLY if diagnostic_closure else ResolutionState.RECOVERED if report.health_restored else ResolutionState.FAILED_RETRYABLE,
        reason_code="legacy_lifecycle_reconstructed",
    )
    final_payload["metadata"] = dict(final_payload["metadata"])
    final_payload["metadata"]["resolution_lifecycle"] = (
        lifecycle
        if diagnostic_report and not diagnostic_closure
        else transition_lifecycle(
            lifecycle,
            ResolutionState.CLOSED if closure_complete else ResolutionState.FAILED_RETRYABLE,
            actor=LifecycleActor.OPERATOR if manual_closure else LifecycleActor.CLOSURE,
            reason_code=(
                "watch_only_policy_completed"
                if diagnostic_closure
                else "operator_administrative_closure"
                if manual_closure
                else None
                if report.health_restored
                else "recovery_validation_failed"
            ),
            validation={
                "checks": report.validation,
                "passed": bool(report.health_restored or diagnostic_closure),
                "administrative_disposition": manual_closure,
                "operator_identity": (
                    {
                        "actor_id": report.metadata.get("actor_id"),
                        "actor_role": report.metadata.get("actor_role"),
                        "auth_jti": report.metadata.get("auth_jti"),
                    }
                    if manual_closure
                    else None
                ),
            },
        )
    )
    final_payload["alert_ids"] = incident_payload_map.get("alert_ids") if isinstance(incident_payload_map.get("alert_ids"), list) else []
    if final_payload["created_at"] is None:
        final_payload.pop("created_at")
    return final_payload


async def _sync_closure_to_jira(incident_payload: dict[str, Any], report: ResolutionReport) -> dict[str, Any]:
    import os
    import logging
    import httpx

    logger = logging.getLogger("closure-service.jira-sync")

    ticket_id = str(incident_payload.get("ticket_id") or "").strip()
    if not ticket_id:
        logger.info("No Jira ticket linked to incident %s; skipping closure update", report.incident_id)
        return {"status": "skipped", "reason": "no_linked_ticket", "transitioned": False}

    base_url = str(os.getenv("JIRA_API_BASE_URL", "") or os.getenv("JIRA_URL", "") or "").rstrip("/")
    email = str(os.getenv("JIRA_API_EMAIL", "") or os.getenv("JIRA_USER_EMAIL", "") or "")
    token = str(os.getenv("JIRA_API_TOKEN", "") or "")

    if not (base_url and email and token):
        logger.info("Jira outbound API is not fully configured; skipping closure sync on ticket %s", ticket_id)
        return {"status": "skipped", "reason": "jira_not_configured", "ticket_id": ticket_id, "transitioned": False}

    auth = (email, token)
    headers = {"Content-Type": "application/json"}

    # 1. Post resolution comment
    lessons = "\n".join(f"- {lesson}" for lesson in report.lessons_learned) if report.lessons_learned else "- No additional lessons captured."
    recovery_validated = bool(report.health_restored and report.alerts_cleared)
    diagnostic_closure = str(report.metadata.get("closure_kind") or "").lower() == "diagnostic"
    diagnostic_details = report.metadata.get("diagnostic_details") if isinstance(report.metadata.get("diagnostic_details"), dict) else {}
    diagnostic_details_text = json.dumps(diagnostic_details, indent=2, default=str) if diagnostic_details else "No additional diagnostic details supplied."
    diagnostic_section = f"h3. Diagnostic Evidence\n{{code:json}}\n{diagnostic_details_text}\n{{code}}\n\n" if diagnostic_closure else ""
    operator_comment = str(report.metadata.get("operator_comment") or "").strip()
    operator_section = f"h3. Operator Closure Comment\n{operator_comment}\n\n" if operator_comment else ""
    comment_body = (
        "[kaiops-managed-closure]\n"
        f"h2. {'Incident Resolved & Closed' if recovery_validated else 'Remediation Completed — Validation Pending'}\n"
        f"{'KaiOps validated recovery and completed the incident workflow.' if recovery_validated else 'KaiOps completed remediation, but recovery validation did not pass. This ticket remains open for operator investigation.'}\n\n"
        "h3. Resolution Report\n"
        f"* *Closure Type*: {'Diagnostic - no corrective action executed' if diagnostic_closure else 'Recovery validated' if recovery_validated else 'Validation pending'}\n"
        f"* *Root Cause*: {report.root_cause}\n"
        f"* *Impact*: {report.impact}\n"
        f"* *Action Taken*: {report.action_taken}\n"
        f"* *Health Restored*: {report.health_restored}\n"
        f"* *Alerts Cleared*: {report.alerts_cleared}\n"
        f"* *Validation Details*: {report.validation}\n\n"
        f"{diagnostic_section}"
        f"{operator_section}"
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

            # Execution success alone is not incident resolution. Jira must
            # remain open until closure validation proves both restored health
            # and cleared alerts.
            if not recovery_validated:
                logger.warning("Jira ticket %s remains open because recovery validation did not pass", ticket_id)
                return {"status": "validation_pending", "reason": "recovery_not_validated", "ticket_id": ticket_id, "transitioned": False, "commented": comment_resp.status_code < 400}

            # 2. Transition Jira ticket to Resolved / Done
            trans_resp = await client.get(
                f"{base_url}/rest/api/2/issue/{ticket_id}/transitions",
                headers=headers
            )
            if trans_resp.status_code >= 400:
                logger.error("Failed to fetch transitions for Jira ticket %s (%s): %s", ticket_id, trans_resp.status_code, trans_resp.text)
                return {"status": "failed", "reason": "transition_lookup_failed", "ticket_id": ticket_id, "transitioned": False, "http_status": trans_resp.status_code}

            transitions = trans_resp.json().get("transitions", [])
            transition_id = None
            for t in transitions:
                name = str(t.get("name") or "").strip().lower()
                destination = t.get("to") if isinstance(t.get("to"), dict) else {}
                status_category = destination.get("statusCategory") if isinstance(destination.get("statusCategory"), dict) else {}
                destination_category = str(status_category.get("key") or status_category.get("name") or "").strip().lower()
                if name in {"done", "resolved", "closed", "resolve", "close", "resolve issue", "close issue"} or destination_category in {"done", "complete", "completed"}:
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
                    return {"status": "failed", "reason": "transition_failed", "ticket_id": ticket_id, "transitioned": False, "http_status": transition_resp.status_code}
                else:
                    logger.info("Successfully transitioned Jira ticket %s to resolved state using transition id %s", ticket_id, transition_id)
                    return {"status": "resolved", "ticket_id": ticket_id, "transitioned": True, "transition_id": str(transition_id), "commented": comment_resp.status_code < 400}
            else:
                logger.warning("No matching transition found for closing Jira ticket %s (available: %s)", ticket_id, [t.get("name") for t in transitions])
                return {"status": "failed", "reason": "no_resolved_transition", "ticket_id": ticket_id, "transitioned": False}

    except Exception as exc:
        logger.exception("Error updating Jira closure for ticket %s: %s", ticket_id, exc)
        return {"status": "failed", "reason": "jira_request_error", "ticket_id": ticket_id, "transitioned": False, "error": str(exc)}


async def _persist_closure_event(
    *,
    app: FastAPI,
    action: RemediationAction,
    report: ResolutionReport,
    source_payload: dict[str, Any],
    event_payload: dict[str, Any] | None = None,
    sync_jira: bool = True,
    propagate_related: bool = True,
) -> dict[str, Any]:
    import logging
    logger = logging.getLogger("closure-service")
    if not settings.database_enabled or getattr(app.state, "session_factory", None) is None:
        return {"status": "not_persisted", "transitioned": False, "outbox_enqueued": True}
    source_contract = source_payload.get("event_contract", {}) if isinstance(source_payload.get("event_contract"), dict) else {}
    source_recommendation = source_payload.get("source_payload", {}).get("recommendation") if isinstance(source_payload.get("source_payload"), dict) else {}
    recommendation = source_recommendation if isinstance(source_recommendation, dict) else {}
    status = (
        "closed"
        if bool(report.health_restored) or _is_diagnostic_closure(report) or _is_manual_closure(report)
        else "investigating"
        if _is_diagnostic_report(report)
        else "failed"
    )
    related_incidents: list[dict[str, Any]] = []

    async with app.state.session_factory() as session:
        repo = IncidentRepository(session)
        incident_payload = await repo.get_incident(str(action.incident_id), tenant_id=action.tenant_id) or {}
        report.ticket_id = str(incident_payload.get("ticket_id") or "").strip() or None
        final_incident_payload = _build_final_incident_payload(
            action=action,
            report=report,
            incident_payload=incident_payload,
            recommendation=recommendation,
            source_contract=source_contract,
        )
        final_lifecycle = final_incident_payload.get("metadata", {}).get("resolution_lifecycle")
        if isinstance(final_lifecycle, dict):
            report.metadata = {**(report.metadata if isinstance(report.metadata, dict) else {}), "resolution_lifecycle": final_lifecycle}
            await repo.save_report(report)
        service_name = str(final_incident_payload.get("service") or "unknown")
        final_metadata = (
            final_incident_payload.get("metadata")
            if isinstance(final_incident_payload.get("metadata"), dict)
            else {}
        )
        candidate = (
            final_metadata.get("incident_candidate")
            if isinstance(final_metadata.get("incident_candidate"), dict)
            else {}
        )
        await repo.save_incident(Incident.model_validate(final_incident_payload))
        await repo.save_incident_event(
            build_event_envelope(
                event_type="incident.diagnostic.recorded" if _is_diagnostic_report(report) and not _is_diagnostic_closure(report) else "incident.closure.completed",
                identity={
                    "incident_id": str(action.incident_id),
                    "alert_id": None,
                    "trace_id": str(source_contract.get("trace_id") or recommendation.get("trace_id") or ""),
                    "correlation_id": str(source_contract.get("correlation_id") or recommendation.get("correlation_id") or "") or None,
                    "causation_id": None,
                    "parent_event_id": None,
                },
                scope={
                    "tenant_id": action.tenant_id,
                    "service": service_name,
                    "environment": str(final_incident_payload.get("environment") or "prod"),
                    "region": None,
                    "team": None,
                },
                state={
                    # Closure must preserve the canonical incident severity.
                    # Defaulting a missing nested recommendation to warning
                    # corrupts Sev 1/Sev 2 MTTR buckets in the read model.
                    "severity": str(final_incident_payload.get("severity") or recommendation.get("severity") or "warning").lower(),
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
                    "resolution_lifecycle": final_incident_payload.get("metadata", {}).get("resolution_lifecycle"),
                },
            )
        )
        durable_event_payload = normalize_payload(
            event_payload or _build_closure_event_payload(action=action, report=report, source_payload=source_payload)
        )
        outbox_enqueued = await repo.enqueue_resolution_event(
            event_id=_closure_outbox_event_id(durable_event_payload, action),
            aggregate_id=str(action.incident_id),
            topic=CLOSURE_EVENTS,
            partition_key=str(action.incident_id),
            payload=durable_event_payload,
            tenant_id=action.tenant_id,
            available_after_seconds=float(getattr(settings, "resolution_outbox_initial_delay_seconds", 60.0) or 60.0),
        )
        await session.commit()
        if report.health_restored and propagate_related:
            related_incidents = await repo.list_unresolved_incident_family(
                incident_id=str(action.incident_id),
                service=service_name,
                environment=str(final_incident_payload.get("environment") or "unknown"),
                category=str(candidate.get("category") or "unknown"),
                tenant_id=str(action.tenant_id or "default"),
            )
        jira_result: dict[str, Any] = {
            "status": "not_requested",
            "transitioned": False,
            "outbox_enqueued": outbox_enqueued,
        }
        if not outbox_enqueued:
            jira_result["status"] = "duplicate_suppressed"
            return jira_result
        try:
            if not sync_jira:
                return jira_result
            jira_result = await _sync_closure_to_jira(incident_payload, report)
            if jira_result.get("transitioned") and report.ticket_id:
                await repo.close_jira_ticket_link(report.ticket_id)
                await session.commit()
        except Exception:
            logger.exception("Failed to synchronize closure event to Jira ticket")
        for related in related_incidents:
            related_id = str(related.get("id") or "").strip()
            if not related_id:
                continue
            related_action_payload = action.model_dump(mode="json")
            related_action_payload.update(
                {
                    "id": str(uuid4()),
                    "incident_id": related_id,
                    "idempotency_key": f"recovery-family:{action.incident_id}:{related_id}",
                    "parameters": {
                        **(action.parameters if isinstance(action.parameters, dict) else {}),
                        "reconciled_from_incident_id": str(action.incident_id),
                        "resolution_propagated": True,
                    },
                }
            )
            related_report_payload = report.model_dump(mode="json")
            related_report_payload.update(
                {
                    "id": str(uuid4()),
                    "incident_id": related_id,
                    "ticket_id": str(related.get("ticket_id") or "").strip() or None,
                    "action_taken": (
                        f"Resolved by verified recovery of related incident {action.incident_id}. "
                        f"{report.action_taken}"
                    ),
                    "metadata": {
                        **(report.metadata if isinstance(report.metadata, dict) else {}),
                        "closure_kind": "related-recovery",
                        "reconciled_from_incident_id": str(action.incident_id),
                    },
                }
            )
            await _persist_closure_event(
                app=app,
                action=RemediationAction.model_validate(related_action_payload),
                report=ResolutionReport.model_validate(related_report_payload),
                source_payload={"source": "verified-related-recovery", "source_payload": source_payload},
                sync_jira=sync_jira,
                propagate_related=False,
            )
        return jira_result


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
        # A failed/skipped executor attempt is not proof that recovery failed.
        # Remediation Engine owns failure reconsideration; closure only starts
        # after a successful terminal execution and its validation contract.
        diagnostic_completion = (
            action.status == RemediationStatus.SKIPPED
            and action.action_type == "diagnostic_completion"
            and action.parameters.get("diagnostic_closure") is True
        )
        if action.status != RemediationStatus.SUCCEEDED and not diagnostic_completion:
            EVENTS_PROCESSED.labels(settings.service_name, REMEDIATION_EVENTS, "awaiting-remediation").inc()
            return
        report = await _validate_and_store(action)
        payload_out = _build_closure_event_payload(action=action, report=report, source_payload=payload)
        persistence = await _persist_closure_event(
            app=app,
            action=action,
            report=report,
            source_payload=payload,
            event_payload=payload_out,
        )
        if persistence.get("outbox_enqueued"):
            await _publish_closure_event(app, payload_out, key=str(action.incident_id))
        EVENTS_PROCESSED.labels(settings.service_name, REMEDIATION_EVENTS, "ok").inc()

    for source, consumer, consume_forever in consumers:
        task = asyncio.create_task(consume_forever(consumer, handle), name=f"closure-service-{source}-consumer")
        tasks.append(task)
    tasks.append(asyncio.create_task(_outbox_dispatch_loop(app), name="closure-service-resolution-outbox"))
    tasks.append(
        asyncio.create_task(
            _terminal_action_reconciliation_loop(app),
            name="closure-service-terminal-action-reconciliation",
        )
    )

    # Startup reconciliation handles downtime immediately; the periodic loop
    # above protects the same handoff during steady-state operation. Successful
    # executor exit alone remains deliberately insufficient.
    await _reconcile_terminal_actions(app)


async def shutdown(_: FastAPI) -> None:
    for task in tasks:
        task.cancel()


app = create_app(title="KaiMS Closure Service", settings=settings, startup=startup, shutdown=shutdown)


def _eligible_for_reusable_knowledge(action: RemediationAction, report: ResolutionReport) -> bool:
    return bool(
        report.health_restored
        and report.alerts_cleared
        and action.parameters.get("outcome_reviewed") is True
        and str(action.parameters.get("outcome_reviewed_by") or "").strip()
        and not action.parameters.get("operator_modified")
    )


@app.get("/reconciliation/terminal-actions")
async def preview_terminal_action_reconciliation(limit: int = 100) -> dict[str, Any]:
    """Read-only visibility into work that startup reconciliation would assess."""

    rows = await _load_terminal_action_candidates(app, limit=max(1, min(limit, 1000)))
    candidates: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for stored_payload, projection_status, replay_source in rows:
        try:
            payload_map = stored_payload if isinstance(stored_payload, dict) else json.loads(str(stored_payload))
            action = RemediationAction.model_validate(payload_map)
            assessment = assess_terminal_action(action, projection_status)
            counts[assessment.decision.value] = counts.get(assessment.decision.value, 0) + 1
            candidates.append({
                "incident_id": str(action.incident_id),
                "action_id": str(action.id),
                "action_status": action.status.value,
                "projection_status": projection_status,
                "source": replay_source,
                **assessment.model_dump(),
            })
        except Exception as exc:
            counts["error"] = counts.get("error", 0) + 1
            candidates.append({"decision": "error", "reason": "invalid_persisted_action", "error": str(exc)})
    return {
        "mode": _reconciliation_mode(),
        "mutating": False,
        "candidate_count": len(rows),
        "counts": counts,
        "candidates": candidates,
    }


async def _validate_and_store(action: RemediationAction) -> ResolutionReport:
    report = await agent.validate(action)
    if settings.database_enabled:
        async with app.state.session_factory() as session:
            repo = IncidentRepository(session)
            incident_payload = await repo.get_incident(str(action.incident_id), tenant_id=action.tenant_id) or {}
            report.ticket_id = str(incident_payload.get("ticket_id") or "").strip() or None
            await repo.save_report(report)
            reviewed_success = _eligible_for_reusable_knowledge(action, report)
            if reviewed_success:
                await repo.save_knowledge_base(report)
            runbook_id = str(action.parameters.get("runbook_id") or "").strip()
            if runbook_id and not bool(action.parameters.get("diagnostic_closure")):
                await repo.record_runbook_execution_outcome(
                    runbook_id=runbook_id,
                    version=int(action.parameters.get("runbook_version") or 1),
                    successful=bool(report.health_restored and report.alerts_cleared),
                    modified=bool(action.parameters.get("operator_modified")),
                    actor=str(action.parameters.get("approved_by") or "closure-service"),
                    tenant_id=action.tenant_id,
                    metadata=action.parameters,
                )
            await session.commit()
    return report


@app.post("/validate", response_model=ResolutionReport)
async def validate(
    action: RemediationAction,
    x_kaiops_internal_token: str = Header(default=""),
) -> ResolutionReport:
    expected_token = settings.service_internal_token
    if not expected_token:
        raise HTTPException(status_code=503, detail="Internal service authentication is not configured")
    if not hmac.compare_digest(x_kaiops_internal_token, expected_token):
        raise HTTPException(status_code=403, detail="Internal service authentication failed")
    report = await _validate_and_store(action)
    payload_out = _build_closure_event_payload(action=action, report=report, source_payload={})
    persistence = await _persist_closure_event(
        app=app,
        action=action,
        report=report,
        source_payload={},
        event_payload=payload_out,
    )
    if persistence.get("outbox_enqueued"):
        await _publish_closure_event(app, payload_out, key=str(action.incident_id))
    return report


class ManualClosureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comment: str = Field(min_length=10, max_length=4000)
    actor_id: str = Field(min_length=1, max_length=255)
    actor_role: str = Field(min_length=1, max_length=64)
    tenant_id: str = Field(min_length=1, max_length=255)
    auth_jti: str = Field(min_length=1, max_length=255)


@app.post("/incidents/{incident_id}/manual-close")
async def manual_close_incident(
    incident_id: str,
    request: ManualClosureRequest,
    x_kaiops_internal_token: str = Header(default=""),
) -> dict[str, Any]:
    expected_token = settings.service_internal_token
    if not expected_token:
        raise HTTPException(status_code=503, detail="Internal service authentication is not configured")
    if not hmac.compare_digest(x_kaiops_internal_token, expected_token):
        raise HTTPException(status_code=403, detail="Internal service authentication failed")
    if not role_is_allowed(
        request.actor_role,
        {OperationalRole.ADMIN.value, OperationalRole.HITL_APPROVER.value},
    ):
        raise HTTPException(status_code=403, detail="Operator role is not authorized for manual closure")
    related_incidents: list[dict[str, Any]] = []
    async with app.state.session_factory() as session:
        incident_payload = await IncidentRepository(session).get_incident(incident_id, tenant_id=request.tenant_id)
    if not incident_payload:
        raise HTTPException(status_code=404, detail="Incident not found")
    if str(incident_payload.get("status") or "").lower() in {"closed", "resolved"}:
        return {"status": "already_closed", "incident_id": incident_id}
    action = RemediationAction(
        tenant_id=str(incident_payload.get("tenant_id") or ""),
        incident_id=incident_id,
        action_type="manual_closure",
        target=str(incident_payload.get("service") or "unknown"),
        status=RemediationStatus.SKIPPED,
        completed_at=datetime.now(timezone.utc),
        output=f"Incident administratively closed by {request.actor_id}.",
        parameters={"operator_comment": request.comment, "actor_id": request.actor_id, "actor_role": request.actor_role, "manual_closure": True},
    )
    report = ResolutionReport(
        tenant_id=str(incident_payload.get("tenant_id") or ""),
        incident_id=incident_id,
        root_cause="Operator-directed closure",
        impact=str(incident_payload.get("summary") or "Impact reviewed by operator."),
        action_taken=f"Administrative closure by {request.actor_id}: {request.comment}",
        validation={"operator_attested": True, "technical_recovery_verified": False},
        alerts_cleared=False,
        health_restored=False,
        metadata={
            "closure_kind": "manual",
            "operator_comment": request.comment,
            "actor_id": request.actor_id,
            "actor_role": request.actor_role,
            "auth_jti": request.auth_jti,
            "technical_recovery_verified": False,
        },
    )
    jira_result = await _sync_closure_to_jira(incident_payload, report)
    if incident_payload.get("ticket_id") and not jira_result.get("transitioned"):
        raise HTTPException(status_code=502, detail={"message": "Jira update failed; incident was not closed.", "jira": jira_result})
    async with app.state.session_factory() as session:
        repo = IncidentRepository(session)
        await repo.save_report(report)
        await session.commit()
    manual_source = {"source": "manual-closure"}
    payload_out = _build_closure_event_payload(action=action, report=report, source_payload=manual_source)
    persistence = await _persist_closure_event(
        app=app,
        action=action,
        report=report,
        source_payload=manual_source,
        event_payload=payload_out,
        sync_jira=False,
    )
    if persistence.get("outbox_enqueued"):
        await _publish_closure_event(app, payload_out, key=incident_id)
    return {
        "status": "closed",
        "closure_kind": "manual",
        "technical_recovery_verified": False,
        "incident_id": incident_id,
        "comment": request.comment,
        "jira": jira_result,
    }
