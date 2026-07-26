from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from collections import deque
from collections.abc import Awaitable, Callable, Coroutine
from time import monotonic
from typing import Any

from alert_intelligence import AlertIntelligenceAgent
from common.config import get_settings
from common.ai_layer_client import AiLayerClient
from common.event_publishers import build_event_envelope
from common.kafka import KafkaConsumer, consume_forever as consume_kafka_forever
from common.models import Alert
from common.rabbitmq import RabbitMQConsumer, consume_forever as consume_rabbitmq_forever
from common.repository import IncidentRepository
from common.servicebus import AzureServiceBusConsumer, consume_forever as consume_service_bus_forever
from common.repository_interfaces import SqlAlertHistoryRepository
from common.service import create_app
from common.telemetry import EVENTS_PROCESSED
from common.topics import ENRICHED_ALERTS, JIRA_INVESTIGATIONS, RAW_ALERTS
from fastapi import FastAPI
import httpx

settings = get_settings()
settings.service_name = "alert-intelligence"
agent = AlertIntelligenceAgent()
tasks: list[asyncio.Task] = []
ai_client = AiLayerClient(settings)
DISCOVERY_LLM_ENABLED = str(os.getenv("DISCOVERY_LLM_ENABLED", "true")).strip().lower() in {"1", "true", "yes", "on"}
DISCOVERY_MIN_CONFIDENCE = max(0.0, min(1.0, float(os.getenv("DISCOVERY_MIN_CONFIDENCE", "0.65") or 0.65)))
DISCOVERY_WARNING_MIN_CONFIDENCE = max(
    DISCOVERY_MIN_CONFIDENCE,
    min(1.0, float(os.getenv("DISCOVERY_WARNING_MIN_CONFIDENCE", "0.80") or 0.80)),
)
JIRA_MAX_NEW_ISSUES_PER_HOUR = max(1, int(os.getenv("JIRA_MAX_NEW_ISSUES_PER_HOUR", "2") or 2))
MESSAGE_BUS_DUAL_CONSUME_ENABLED = str(
    os.getenv("MESSAGE_BUS_DUAL_CONSUME_ENABLED", "false")
).strip().lower() in {"1", "true", "yes", "on"}
_JIRA_CREATION_TIMES: deque[float] = deque()
logger = logging.getLogger("alert-intelligence")

ConsumeRunner = Callable[[Any, Callable[[dict], Awaitable[None]]], Coroutine[Any, Any, None]]


def _json_object(value: str) -> dict[str, Any]:
    text = str(value or "").strip()
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    candidate = fenced.group(1).strip() if fenced else text
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start >= 0 and end > start:
        candidate = candidate[start : end + 1] if start >= 0 and end > start else candidate
    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else {}
    except ValueError:
        return {}


async def _llm_discovery(alert: Alert) -> dict[str, Any]:
    if not DISCOVERY_LLM_ENABLED:
        return {}
    prompt = (
        "Act as an SRE discovery agent. Return one strict JSON object only. Required keys: "
        "title, description, service, environment, "
        "category, initial_hypothesis, technical_impact, business_impact, affected_users, scope, urgency, "
        "actionable, actionability_reason, recommended_severity, confidence, reasoning, evidence_used, "
        "missing_evidence, alternative_hypotheses, impact_basis. Set actionable=true only when "
        "operator intervention or investigation is required; routine cleanup, retry noise, test signals, and KaiOps' "
        "own integration errors are not actionable. confidence must be 0..1. Treat the supplied alert as an observation, "
        "not proof of root cause or customer impact. evidence_used must contain only identifiers or fields present in the "
        "payload. Separate observed impact from possible risk, list unknowns in missing_evidence, and never invent evidence."
    )
    try:
        response = await ai_client.route_model(
            severity=alert.severity,
            task="general",
            prompt=prompt,
            payload={"alert": alert.model_dump(mode="json")},
        )
        parsed = _json_object(str(response.get("content") or ""))
        if parsed:
            usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
            parsed["model_provider"] = str(usage.get("provider") or "model-router")
            parsed["model_name"] = str(response.get("model") or usage.get("model") or "unknown")
            try:
                confidence = float(parsed.get("confidence"))
                if 1.0 < confidence <= 100.0:
                    parsed["confidence"] = confidence / 100.0
            except (TypeError, ValueError):
                pass
            logger.info(
                "incident_pipeline stage=llm_discovery outcome=parsed provider=%s model=%s",
                parsed["model_provider"],
                parsed["model_name"],
            )
        else:
            usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
            logger.warning(
                "incident_pipeline stage=llm_discovery outcome=fallback provider=%s model=%s reason=non-json-response",
                usage.get("provider"),
                response.get("model") or usage.get("model"),
            )
        return parsed
    except Exception:
        return {}


def _qualify_candidate_for_jira(candidate: dict[str, Any]) -> tuple[bool, str]:
    if not bool(candidate.get("actionable")):
        return False, str(candidate.get("actionability_reason") or "Discovery classified signal as non-actionable")
    confidence = float(candidate.get("confidence") or 0.0)
    severity = str(candidate.get("final_severity") or candidate.get("recommended_severity") or "").lower()
    threshold = DISCOVERY_WARNING_MIN_CONFIDENCE if severity == "warning" else DISCOVERY_MIN_CONFIDENCE
    if severity not in {"warning", "high", "critical"}:
        return False, f"final severity {severity or 'unknown'} is below Jira threshold"
    if confidence < threshold:
        return False, f"confidence {confidence:.2f} is below {threshold:.2f}"
    if not candidate.get("evidence"):
        return False, "candidate has no evidence references"
    return True, "qualified by actionability, severity, confidence, and evidence policy"


async def _sync_candidate_to_jira(incident: Any) -> str | None:
    candidate = incident.metadata.get("incident_candidate") if isinstance(incident.metadata, dict) else {}
    if not isinstance(candidate, dict):
        return None
    qualified, qualification_reason = _qualify_candidate_for_jira(candidate)
    incident.metadata["jira_qualification"] = {
        "qualified": qualified,
        "reason": qualification_reason,
        "policy_version": "jira-qualification-v2",
    }
    jira_key = str(getattr(incident, "ticket_id", "") or candidate.get("jira_key") or "")
    # Human/external Jira incidents are already golden records and may be
    # enriched even when the new evidence alone is below creation threshold.
    if not jira_key and not qualified:
        logger.info(
            "incident_pipeline stage=jira_qualification outcome=suppressed incident=%s reason=%s",
            incident.id,
            qualification_reason,
        )
        return None
    base_url = str(os.getenv("JIRA_API_BASE_URL", "") or "").rstrip("/")
    email = str(os.getenv("JIRA_API_EMAIL", "") or "")
    token = str(os.getenv("JIRA_API_TOKEN", "") or "")
    project_key = str(os.getenv("JIRA_PROJECT_KEY", "") or "")
    if not (base_url and email and token and project_key):
        return None
    idempotency_key = str(candidate.get("idempotency_key") or "")
    fingerprint_label = f"kaiops-candidate-{idempotency_key[:32]}"
    async with httpx.AsyncClient(auth=(email, token), timeout=15.0) as client:
        if not jira_key:
            jql = (
                f'project = "{project_key}" AND labels = "{fingerprint_label}" '
                "AND statusCategory != Done ORDER BY updated DESC"
            )
            search = await client.get(
                f"{base_url}/rest/api/3/search/jql",
                params={"jql": jql, "fields": "key,status", "maxResults": 1},
            )
            search.raise_for_status()
            issues = search.json().get("issues", []) if isinstance(search.json(), dict) else []
            if issues and isinstance(issues[0], dict):
                jira_key = str(issues[0].get("key") or "")
            else:
                current = monotonic()
                while _JIRA_CREATION_TIMES and current - _JIRA_CREATION_TIMES[0] >= 3600:
                    _JIRA_CREATION_TIMES.popleft()
                if len(_JIRA_CREATION_TIMES) >= JIRA_MAX_NEW_ISSUES_PER_HOUR:
                    incident.metadata["jira_qualification"] = {
                        "qualified": False,
                        "reason": "post-Discovery hourly Jira creation limit reached",
                        "policy_version": "jira-qualification-v2",
                    }
                    logger.info(
                        "incident_pipeline stage=jira outcome=rate_limited incident=%s",
                        incident.id,
                    )
                    return None
                _JIRA_CREATION_TIMES.append(current)
                severity = str(candidate.get("final_severity") or "warning").lower()
                description = (
                    "h2. AI-discovered incident\n"
                    f"* Service: {candidate.get('service')}\n"
                    f"* Environment: {candidate.get('environment')}\n"
                    f"* Category: {candidate.get('category')}\n"
                    f"* Final severity: {severity}\n"
                    f"* Confidence: {candidate.get('confidence')}\n\n"
                    "h2. Initial hypothesis\n"
                    f"{candidate.get('initial_hypothesis')}\n\n"
                    "h2. Business impact\n"
                    f"{candidate.get('business_impact')}\n\n"
                    "h2. Evidence\n"
                    f"{json.dumps(candidate.get('evidence', []), default=str)[:5000]}"
                )
                created = await client.post(
                    f"{base_url}/rest/api/2/issue",
                    json={
                        "fields": {
                            "project": {"key": project_key},
                            "summary": str(candidate.get("title") or "KaiOps incident")[:255],
                            "description": description,
                            "issuetype": {"name": "Bug"},
                            "labels": [
                                "managed_by_kaiops",
                                fingerprint_label,
                                f"kaiops-severity-{severity}",
                            ],
                        }
                    },
                )
                created.raise_for_status()
                jira_key = str(created.json().get("key") or "")
                if not jira_key:
                    raise RuntimeError("Jira create response did not include an issue key")
        incident.ticket_id = jira_key
        candidate["jira_key"] = jira_key
        incident.metadata["incident_candidate"] = candidate
    property_key = f"kaiops-candidate-{idempotency_key[:32]}"
    property_url = f"{base_url}/rest/api/2/issue/{jira_key}/properties/{property_key}"
    async with httpx.AsyncClient(auth=(email, token), timeout=15.0) as client:
        existing = await client.get(property_url)
        if existing.status_code == 200:
            return jira_key
        markers = {
            "managed_by_kaiops": True,
            "kaiops_incident_id": str(incident.id),
            "event_origin": "kaiops",
            "idempotency_key": idempotency_key,
        }
        await client.put(
            property_url,
            json={
                **markers,
                "incident_candidate": candidate,
                "severity_policy": incident.metadata.get("severity_policy", {}),
            },
        )
        await client.put(
            f"{base_url}/rest/api/2/issue/{jira_key}",
            json={
                "update": {
                    "labels": [
                        {"add": "managed_by_kaiops"},
                        {"add": f"kaiops_incident_{str(incident.id).replace('-', '_')}"},
                    ]
                }
            },
        )
        body = (
            "[kaiops-managed-update]\n"
            "h2. AI Discovery and Severity Policy\n"
            f"* KaiOps incident ID: {incident.id}\n"
            f"* Category: {candidate.get('category')}\n"
            f"* Final severity: {candidate.get('final_severity')}\n"
            f"* Confidence: {candidate.get('confidence')}\n"
            f"* Initial hypothesis: {candidate.get('initial_hypothesis')}\n"
            f"* Business impact: {candidate.get('business_impact')}\n"
            f"* Evidence: {', '.join(str(row.get('uri')) for row in candidate.get('evidence', []) if isinstance(row, dict))}\n"
            f"* Similar incidents: {json.dumps(candidate.get('similar_incidents', []), default=str)[:1500]}"
        )
        await client.post(f"{base_url}/rest/api/2/issue/{jira_key}/comment", json={"body": body})
    logger.info(
        "incident_pipeline stage=jira outcome=synchronized incident=%s issue=%s",
        incident.id,
        jira_key,
    )
    return jira_key


def _build_alert_enriched_envelope(alert: Alert, incident: Any) -> dict[str, Any]:
    severity = str(getattr(alert.severity, "value", alert.severity) or "warning").strip().lower() or "warning"
    return build_event_envelope(
        event_type="incident.alert.enriched",
        identity={
            "incident_id": str(incident.id),
            "alert_id": str(alert.id),
            "trace_id": str(incident.trace_id or alert.trace_id or ""),
            "correlation_id": str(alert.correlation_id or "") or None,
            "causation_id": None,
            "parent_event_id": None,
        },
        scope={
            "tenant_id": "default",
            "service": str(alert.service or "unknown"),
            "environment": str(alert.environment or "prod"),
            "region": None,
            "team": str(alert.metadata.get("owner_team") or "") or None,
        },
        state={
            "severity": severity,
            "status": "investigating",
            "owner": None,
        },
        policy={
            "risk_tier": "unknown",
            "execution_mode": "unknown",
            "requires_approval": None,
            "policy_version": None,
            "policy_reason": "alert enriched and incident opened",
        },
        transport={
            "provider": "unknown",
            "channel": ENRICHED_ALERTS,
            "partition": None,
            "offset": None,
            "delivery_tag": None,
        },
        payload={
            "alert_name": alert.name,
            "alert_source": alert.source,
            "incident_title": incident.title,
            "service": alert.service,
            "jira_key": str(getattr(incident, "ticket_id", "") or "") or None,
            "incident_candidate": incident.metadata.get("incident_candidate", {}),
            "severity_policy": incident.metadata.get("severity_policy", {}),
            "managed_by_kaiops": True,
            "kaiops_incident_id": str(incident.id),
            "event_origin": "kaiops",
        },
    )

async def startup(app: FastAPI) -> None:
    if settings.database_enabled and getattr(app.state, "session_factory", None) is not None:
        agent.alert_history_repository = SqlAlertHistoryRepository(
            session_factory=app.state.session_factory,
            max_items=2000,
        )

    workers = max(1, int(getattr(settings, "message_bus_worker_count", 1) or 1))
    consumers: list[tuple[str, Any, ConsumeRunner]] = []
    for worker in range(workers):
        consumers.append((f"rabbitmq-w{worker + 1}", RabbitMQConsumer(settings, RAW_ALERTS), consume_rabbitmq_forever))
        consumers.append(
            (
                f"rabbitmq-jira-w{worker + 1}",
                RabbitMQConsumer(settings, JIRA_INVESTIGATIONS),
                consume_rabbitmq_forever,
            )
        )
    # Producers may mirror an event to RabbitMQ and Kafka for durability.
    # Consuming both copies in the same service executes LLM/Jira side effects
    # twice, so RabbitMQ is primary unless dual consumption is explicitly
    # requested for a migration.
    if settings.kafka_enabled and MESSAGE_BUS_DUAL_CONSUME_ENABLED:
        for worker in range(workers):
            consumers.insert(worker, (f"kafka-w{worker + 1}", KafkaConsumer(settings, RAW_ALERTS), consume_kafka_forever))
            consumers.insert(
                worker,
                (
                    f"kafka-jira-w{worker + 1}",
                    KafkaConsumer(settings, JIRA_INVESTIGATIONS),
                    consume_kafka_forever,
                ),
            )
    if settings.azure_service_bus_enabled:
        for worker in range(workers):
            consumers.append(
                (
                    f"servicebus-w{worker + 1}",
                    AzureServiceBusConsumer(settings, RAW_ALERTS),
                    consume_service_bus_forever,
                )
            )

    async def handle(payload: dict) -> None:
        raw_alert_payload = payload.get("alert") if isinstance(payload.get("alert"), dict) else payload
        alert_input = Alert.model_validate(raw_alert_payload)
        llm_discovery = await _llm_discovery(alert_input)
        alert, incident = await agent.process(alert_input, llm_discovery)
        jira_key: str | None = None
        try:
            jira_key = await _sync_candidate_to_jira(incident)
        except Exception:
            logger.exception("failed to synchronize incident candidate to Jira incident=%s", incident.id)
        if settings.database_enabled:
            async with app.state.session_factory() as session:
                repo = IncidentRepository(session)
                await repo.save_alert(alert)
                await repo.save_incident(incident)
                await repo.save_incident_event(_build_alert_enriched_envelope(alert, incident))
                await session.commit()
        if jira_key:
            await app.state.producer.publish(
                ENRICHED_ALERTS,
                {"alert": alert, "incident": incident},
                key=str(alert.correlation_id or alert.service),
            )
        else:
            logger.info(
                "incident_pipeline stage=downstream outcome=suppressed incident=%s reason=no qualified Jira incident",
                incident.id,
            )
        EVENTS_PROCESSED.labels(settings.service_name, RAW_ALERTS, "ok").inc()

    for source, consumer, consume_forever in consumers:
        task = asyncio.create_task(consume_forever(consumer, handle), name=f"alert-intelligence-{source}-consumer")
        tasks.append(task)


async def shutdown(_: FastAPI) -> None:
    for task in tasks:
        task.cancel()


app = create_app(title="KaiMS Alert Intelligence", settings=settings, startup=startup, shutdown=shutdown)


@app.post("/process")
async def process(alert: Alert) -> dict:
    enriched, incident = await agent.process(alert, await _llm_discovery(alert))
    jira_key: str | None = None
    try:
        jira_key = await _sync_candidate_to_jira(incident)
    except Exception:
        logger.exception("failed to synchronize incident candidate to Jira incident=%s", incident.id)
    if jira_key:
        await app.state.producer.publish(ENRICHED_ALERTS, {"alert": enriched, "incident": incident}, key=alert.service)
    return {"alert": enriched, "incident": incident, "jira_qualified": bool(jira_key)}
