from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shlex
from time import perf_counter
from typing import Any
from urllib.parse import urlparse
from uuid import NAMESPACE_URL, uuid5

from common.config import get_settings
from common.event_publishers import EventPublisher, RabbitMQPublisher, build_agent_event_contract, build_event_envelope
from common.kafka import KafkaConsumer, consume_forever as consume_kafka_forever
from ai_workbench_common.models import Context
from common.models import Alert, Incident
from common.rabbitmq import RabbitMQConsumer, consume_forever as consume_rabbitmq_forever
from common.repository import IncidentRepository
from common.service import create_app
from common.telemetry import (
    CONTEXT_KNOWLEDGE_OPERATIONS,
    CONTEXT_KNOWLEDGE_REUSE_COUNT,
    CONTEXT_STRATEGY_DURATION,
    CONTEXT_STRATEGY_REQUESTS,
    EVENTS_PROCESSED,
)
from common.topics import CONTEXT_EVENTS, ORCHESTRATION_EVENTS
from context_agent import ContextIntelligenceAgent
from context_agent.connectors import VectorDBConnector
from context_agent.knowledge_graph import KnowledgeGraph
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

settings = get_settings()
settings.service_name = "context-agent"
logger = logging.getLogger("context-agent")
agent = ContextIntelligenceAgent()
tasks: list[asyncio.Task] = []
MESSAGE_BUS_DUAL_CONSUME_ENABLED = str(
    os.getenv("MESSAGE_BUS_DUAL_CONSUME_ENABLED", "false")
).strip().lower() in {"1", "true", "yes", "on"}


def _context_strategy(override: str | None = None) -> str:
    strategy = str(override or getattr(settings, "context_strategy", "auto") or "auto").strip().lower()
    aliases = {"continuous": "auto", "immediate": "realtime"}
    strategy = aliases.get(strategy, strategy)
    return strategy if strategy in {"auto", "realtime", "historical"} else "auto"


def _context_completeness(context: Context) -> tuple[bool, list[str]]:
    metadata = context.metadata if isinstance(context.metadata, dict) else {}
    discovery = metadata.get("discovery_report") if isinstance(metadata.get("discovery_report"), dict) else {}
    evidence = discovery.get("evidence") if isinstance(discovery.get("evidence"), list) else []
    available = {
        "discovery_evidence": bool(evidence or metadata.get("discovery_evidence")),
        "service_inventory": bool(context.cmdb or context.deployment),
        "observability": bool(context.observability),
        "dependencies": bool(context.dependency_services),
        "runbook_or_changes": bool(context.runbook or context.recent_changes),
    }
    missing = [name for name, present in available.items() if not present]
    explicitly_complete = metadata.get("context_complete") is True
    return explicitly_complete or sum(available.values()) >= 3, missing


def _has_code_evidence(context: Context) -> bool:
    metadata = context.metadata if isinstance(context.metadata, dict) else {}
    discovery = metadata.get("discovery_report") if isinstance(metadata.get("discovery_report"), dict) else {}
    evidence = discovery.get("evidence") if isinstance(discovery.get("evidence"), list) else []
    return any(
        isinstance(row, dict) and str(row.get("source") or "").strip().lower() == "code"
        for row in evidence
    )


def _context_identity(alert: Alert) -> tuple[str, str, str, str]:
    metadata = alert.metadata if isinstance(alert.metadata, dict) else {}
    labels = alert.labels if isinstance(alert.labels, dict) else {}
    tenant_id = str(metadata.get("tenant_id") or labels.get("tenant_id") or "default").strip() or "default"
    service = str(alert.service or "unknown").strip().lower() or "unknown"
    environment = str(alert.environment or labels.get("environment") or "prod").strip().lower() or "prod"
    # Alert type identity must not include deployment-specific labels. A pod,
    # namespace, project, or application change is another occurrence of the
    # same alert type and should reuse validated knowledge. Service and
    # environment retain the safety boundary between distinct workloads.
    stable_labels = {
        key: str(labels.get(key) or "").strip().lower()
        for key in ("category", "alert_family")
        if str(labels.get(key) or "").strip()
    }
    signature_input = {
        "source": str(alert.source or "").strip().lower(),
        "name": str(alert.name or "").strip().lower(),
        "service": service,
        "environment": environment,
        "labels": stable_labels,
    }
    signature = hashlib.sha256(
        json.dumps(signature_input, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return tenant_id, service, environment, signature


def _resolution_quality_score(payload: Any) -> float:
    if not isinstance(payload, dict) or not payload:
        return 0.0
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    evaluation = metadata.get("evaluation") if isinstance(metadata.get("evaluation"), dict) else {}
    raw = evaluation.get("overall_score")
    if raw is None:
        raw = payload.get("confidence")
    try:
        score = float(raw or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(score / 100.0 if score > 1.0 else score, 1.0))


def _qualified_resolution_cache(payload: Any) -> bool:
    if not bool(getattr(settings, "context_resolution_reuse_enabled", True)):
        return False
    threshold = float(getattr(settings, "context_resolution_reuse_min_score", 0.7) or 0.7)
    return _resolution_quality_score(payload) > max(0.0, min(threshold, 1.0))


async def _collect_context_with_strategy(
    app: FastAPI,
    alert: Alert,
    incident: Incident,
    strategy_override: str | None = None,
    supplied_context: dict[str, Any] | None = None,
) -> Context:
    started = perf_counter()
    strategy = _context_strategy(strategy_override)
    tenant_id, service, environment, signature = _context_identity(alert)
    session_factory = getattr(app.state, "session_factory", None)
    database_available = bool(settings.database_enabled and session_factory is not None)

    if isinstance(supplied_context, dict):
        try:
            provided = Context.model_validate(supplied_context).model_copy(
                update={"incident_id": incident.id, "alert": alert}
            )
        except Exception:
            logger.warning("supplied context is invalid; evaluating cache policy instead")
        else:
            complete, missing = _context_completeness(provided)
            if complete and strategy != "realtime":
                provided.metadata = {
                    **(provided.metadata if isinstance(provided.metadata, dict) else {}),
                    "context_strategy": strategy,
                    "context_source": "ticket_payload",
                    "context_reused": True,
                    "context_complete": True,
                    "context_missing_sections": missing,
                    "realtime_collection_performed": False,
                }
                CONTEXT_STRATEGY_REQUESTS.labels(strategy, "complete_payload").inc()
                return provided

    if strategy in {"auto", "historical"} and database_available:
        configured_ttl = int(getattr(settings, "context_knowledge_ttl_seconds", 0) or 0)
        historical_ttl = int(os.getenv("CONTEXT_HISTORICAL_MAX_AGE_SECONDS", "0") or 0)
        ttl_seconds = historical_ttl if strategy == "historical" else configured_ttl
        not_before = (
            datetime.now(timezone.utc) - timedelta(seconds=max(60, ttl_seconds))
            if ttl_seconds > 0
            else datetime.min.replace(tzinfo=timezone.utc)
        )
        try:
            async with session_factory() as session:
                repo = IncidentRepository(session)
                cached = await repo.find_context_knowledge(
                    tenant_id=tenant_id,
                    service=service,
                    environment=environment,
                    alert_name=str(alert.name or "unknown"),
                    alert_signature=signature,
                    not_before=not_before,
                )
                CONTEXT_KNOWLEDGE_OPERATIONS.labels("lookup", "hit" if cached else "miss").inc()
                if cached:
                    cached_resolution = cached.get("resolution_payload", {})
                    if strategy == "auto" and not _qualified_resolution_cache(cached_resolution):
                        CONTEXT_KNOWLEDGE_OPERATIONS.labels("lookup", "unqualified").inc()
                        cached = None
                if cached:
                    try:
                        context = Context.model_validate(cached.get("payload", {})).model_copy(
                            update={"incident_id": incident.id, "alert": alert}
                        )
                    except Exception:
                        CONTEXT_KNOWLEDGE_OPERATIONS.labels("lookup", "invalid").inc()
                        logger.exception("invalid cached context knowledge id=%s; refreshing", cached.get("id"))
                    else:
                        complete, missing = _context_completeness(context)
                        if strategy == "auto" and not complete:
                            CONTEXT_KNOWLEDGE_OPERATIONS.labels("lookup", "incomplete").inc()
                            continue_with_refresh = True
                        else:
                            continue_with_refresh = False
                        if continue_with_refresh:
                            logger.info("cached context lacks required evidence coverage for signature=%s; refreshing", signature)
                        else:
                            reuse_count = int(cached.get("reuse_count", 1) or 1)
                            context.metadata = {
                                **(context.metadata if isinstance(context.metadata, dict) else {}),
                                "context_strategy": strategy,
                                "context_source": "periodic_knowledge",
                                "context_reused": True,
                                "alert_type_known": True,
                                "knowledge_route": "reuse_periodic_knowledge",
                                "knowledge_match_type": cached.get("match_type", "signature"),
                                "context_complete": complete,
                                "context_missing_sections": missing,
                                "realtime_collection_performed": False,
                                "context_knowledge_id": cached.get("id"),
                                "context_source_alert_id": cached.get("source_alert_id"),
                                "context_source_incident_id": cached.get("source_incident_id"),
                                "context_collected_at": cached.get("collected_at"),
                                "context_reuse_count": reuse_count,
                                "context_signature": signature,
                                "prior_resolution": cached.get("resolution_payload", {}),
                                "prior_resolution_score": _resolution_quality_score(cached.get("resolution_payload", {})),
                                "resolution_reuse_threshold": float(getattr(settings, "context_resolution_reuse_min_score", 0.7) or 0.7),
                            }
                            await session.commit()
                            CONTEXT_KNOWLEDGE_REUSE_COUNT.observe(reuse_count)
                            CONTEXT_STRATEGY_REQUESTS.labels(strategy, "cache_hit").inc()
                            CONTEXT_STRATEGY_DURATION.labels(strategy, "reused").observe(
                                max(0.0, perf_counter() - started)
                            )
                            return context
        except Exception:
            CONTEXT_KNOWLEDGE_OPERATIONS.labels("lookup", "error").inc()
            logger.exception("context knowledge lookup failed; continuing with fresh discovery")

    if strategy in {"auto", "historical"} and not database_available:
        CONTEXT_KNOWLEDGE_OPERATIONS.labels("lookup", "unavailable").inc()

    if strategy == "historical":
        context = Context(incident_id=incident.id, alert=alert)
        context.metadata = {
            "context_strategy": "historical",
            "context_source": "historical_cache_miss",
            "context_reused": False,
            "context_complete": False,
            "context_missing_sections": ["historical_context"],
            "realtime_collection_performed": False,
        }
        CONTEXT_STRATEGY_REQUESTS.labels("historical", "cache_miss").inc()
        return context

    try:
        context = await agent.collect_with_runtime(alert, incident)
    except Exception:
        CONTEXT_STRATEGY_REQUESTS.labels(strategy, "discovery_error").inc()
        CONTEXT_STRATEGY_DURATION.labels(strategy, "error").observe(max(0.0, perf_counter() - started))
        raise
    context.metadata = {
        **(context.metadata if isinstance(context.metadata, dict) else {}),
        "context_strategy": strategy,
        "context_reused": False,
        "context_source": "realtime_collection",
        "alert_type_known": False,
        "knowledge_route": "full_context_then_learn",
        "context_complete": _context_completeness(context)[0],
        "context_missing_sections": _context_completeness(context)[1],
        "realtime_collection_performed": True,
        "context_signature": signature,
        "context_collected_at": datetime.now(timezone.utc).isoformat(),
    }
    if database_available:
        try:
            async with session_factory() as session:
                repo = IncidentRepository(session)
                knowledge_id = await repo.save_context_knowledge(
                    tenant_id=tenant_id,
                    service=service,
                    environment=environment,
                    alert_name=str(alert.name or "unknown"),
                    alert_signature=signature,
                    source_alert_id=alert.id,
                    source_incident_id=incident.id,
                    payload=context.model_dump(mode="json"),
                )
                context.metadata["context_knowledge_id"] = knowledge_id
                await session.commit()
            CONTEXT_KNOWLEDGE_OPERATIONS.labels("store", "success").inc()
        except Exception:
            CONTEXT_KNOWLEDGE_OPERATIONS.labels("store", "error").inc()
            logger.exception("context knowledge persistence failed; returning freshly collected context")
    outcome = "fresh" if strategy == "realtime" else "cache_miss"
    CONTEXT_STRATEGY_REQUESTS.labels(strategy, outcome).inc()
    CONTEXT_STRATEGY_DURATION.labels(strategy, "fresh_discovery").observe(max(0.0, perf_counter() - started))
    return context


def _extract_message_bus_provider(payload: dict[str, Any]) -> str:
    decision = payload.get("decision")
    if isinstance(decision, dict):
        provider = str(decision.get("message_bus_provider", "rabbitmq")).strip().lower()
        if provider in {"kafka", "rabbitmq", "azure-service-bus", "servicebus", "azure"}:
            return provider
    transport = str(payload.get("transport", "")).strip().lower()
    if transport in {"kafka", "rabbitmq", "azure-service-bus", "servicebus", "azure"}:
        return transport
    return "rabbitmq"


async def _publish_context_event(
    *,
    app: FastAPI,
    provider: str,
    alert: Alert,
    incident: Incident,
    context: Context,
    decision: dict[str, Any] | None,
) -> str:
    publishers: dict[str, EventPublisher] = getattr(app.state, "message_bus_publishers", {})
    selected = publishers.get(provider)
    provider_used = provider
    if selected is None:
        provider_used = "rabbitmq"
        selected = publishers.get("rabbitmq", app.state.producer)

    payload = _build_context_event_payload(
        alert=alert,
        incident=incident,
        context=context,
        decision=decision,
        provider_used=provider_used,
    )
    await selected.publish(CONTEXT_EVENTS, payload, key=alert.service)
    return provider_used


async def _persist_context_event(
    *,
    app: FastAPI,
    alert: Alert,
    incident: Incident,
    context: Context,
    decision: dict[str, Any] | None,
    provider_used: str,
) -> None:
    if not settings.database_enabled or getattr(app.state, "session_factory", None) is None:
        return
    decision_payload = decision if isinstance(decision, dict) else {}
    async with app.state.session_factory() as session:
        repo = IncidentRepository(session)
        await repo.save_incident_event(
            build_event_envelope(
                event_type="incident.context.collected",
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
                    "severity": str(getattr(alert.severity, "value", alert.severity) or "warning").lower(),
                    "status": "investigating",
                    "owner": None,
                },
                policy={
                    "risk_tier": str(decision_payload.get("risk_tier") or "unknown"),
                    "execution_mode": str(decision_payload.get("execution_mode") or "unknown"),
                    "requires_approval": decision_payload.get("requires_approval"),
                    "policy_version": decision_payload.get("policy_version"),
                    "policy_reason": decision_payload.get("policy_reason"),
                },
                transport={
                    "provider": provider_used,
                    "channel": CONTEXT_EVENTS,
                    "partition": None,
                    "offset": None,
                    "delivery_tag": None,
                },
                payload={
                    "workflow": decision_payload.get("workflow"),
                    "context": context.model_dump(mode="json"),
                    "deployment": context.deployment,
                    "related_incidents": context.related_incidents,
                    "dependency_services": context.dependency_services,
                    "document_available": bool(context.metadata.get("rag_service_tagged_match", False)),
                    "discovery_report": context.metadata.get("discovery_report", {}),
                    "discovery_evidence": context.metadata.get("discovery_evidence", {}),
                    "context_sources": context.metadata.get("context_sources", {}),
                    "context_evidence": context.metadata.get("context_evidence", {}),
                },
            )
        )
        await session.commit()


def _build_context_event_payload(
    *,
    alert: Alert,
    incident: Incident,
    context: Context,
    decision: dict[str, Any] | None,
    provider_used: str,
) -> dict[str, Any]:
    decision_payload = decision if isinstance(decision, dict) else {}
    flow_id = str(decision_payload.get("flow_id") or incident.id)
    discovery = context.metadata.get("discovery_report", {})
    if not isinstance(discovery, dict):
        discovery = {}
    report = discovery.get("report") if isinstance(discovery.get("report"), dict) else {}
    evidence = discovery.get("evidence") if isinstance(discovery.get("evidence"), list) else []
    evidence_ids = [
        str(row.get("evidence_id"))
        for row in evidence
        if isinstance(row, dict) and str(row.get("evidence_id") or "").strip()
    ]
    citations = [
        str(row.get("uri"))
        for row in evidence
        if isinstance(row, dict) and str(row.get("uri") or "").strip()
    ]
    event_contract = build_agent_event_contract(
        flow_id=flow_id,
        incident_id=str(incident.id),
        trace_id=str(incident.trace_id or alert.trace_id or ""),
        correlation_id=str(alert.correlation_id or "") or None,
        agent="context-agent",
        payload={
            "service": alert.service,
            "transport_provider": provider_used,
            "topic": CONTEXT_EVENTS,
            "rag_document_count": context.metadata.get("rag_documents", 0),
            "context_sources": context.metadata.get("context_sources", {}),
            "discovery": {
                "protocol": discovery.get("protocol"),
                "summary": report.get("summary"),
                "hypotheses": report.get("hypotheses", []),
                "retrieval_stages": discovery.get("retrieval_stages", []),
                "evidence": evidence,
                "model_usage": discovery.get("model_usage", {}),
                "model_interaction": discovery.get("model_interaction", {}),
                "insufficient_evidence": report.get("insufficient_evidence", False),
                "external_knowledge_eligible": report.get("external_knowledge_eligible", False),
                "external_knowledge_used": report.get("external_knowledge_used", False),
                "external_tools_used": report.get("external_tools_used", []),
                "external_knowledge_error": report.get("external_knowledge_error"),
            },
        },
        metadata={
            "workflow": decision_payload.get("workflow"),
            "requires_approval": decision_payload.get("requires_approval"),
            "message_bus_provider": decision_payload.get("message_bus_provider"),
        },
        confidence=0.8,
        reasoning=str(report.get("summary") or "connector fusion across observability, tickets, code, logs, cmdb, and rag context"),
        citations=citations or [f"rag://{alert.service}", "cmdb://dependencies"],
        evidence_ids=evidence_ids or [f"alert:{alert.id}", f"incident:{incident.id}"],
    )
    return {
        "context": context,
        "incident": incident,
        "decision": decision,
        "transport": provider_used,
        "event_contract": event_contract,
    }


def _build_ingress_consumers() -> list[tuple[str, object, object]]:
    workers = max(1, int(getattr(settings, "message_bus_worker_count", 1) or 1))
    consumers: list[tuple[str, object, object]] = []
    for worker in range(workers):
        consumers.append(
            (f"rabbitmq-w{worker + 1}", RabbitMQConsumer(settings, ORCHESTRATION_EVENTS), consume_rabbitmq_forever)
        )
    if settings.kafka_enabled and MESSAGE_BUS_DUAL_CONSUME_ENABLED:
        for worker in range(workers):
            consumers.insert(
                worker,
                (f"kafka-w{worker + 1}", KafkaConsumer(settings, ORCHESTRATION_EVENTS), consume_kafka_forever),
            )
    return consumers


async def startup(app: FastAPI) -> None:
    provider = str(getattr(settings, "event_bus_provider", "rabbitmq") or "rabbitmq").strip().lower()
    app.state.message_bus_publishers = {provider: app.state.producer, "rabbitmq": app.state.producer}

    if settings.kafka_enabled:
        app.state.message_bus_publishers["kafka"] = app.state.producer

    if settings.kafka_enabled:
        rabbitmq_publisher = RabbitMQPublisher(settings)
        try:
            await rabbitmq_publisher.start()
            app.state.message_bus_publishers["rabbitmq"] = rabbitmq_publisher
        except Exception:
            app.state.rabbitmq_publisher = None
        else:
            app.state.rabbitmq_publisher = rabbitmq_publisher
    else:
        app.state.rabbitmq_publisher = None

    async def handle(payload: dict) -> None:
        alert = Alert.model_validate(payload["alert"])
        incident = Incident.model_validate(payload["incident"])
        decision = payload.get("decision") if isinstance(payload.get("decision"), dict) else {}
        context = await _collect_context_with_strategy(
            app, alert, incident, decision.get("context_strategy"), payload.get("context")
        )
        try:
            create_evidence_rag_draft(alert=alert, incident=incident, context=context)
        except Exception:
            logger.exception(
                "failed to create evidence RAG draft for alert_id=%s",
                alert.alert_id,
            )
        provider = _extract_message_bus_provider(payload)
        provider_used = await _publish_context_event(
            app=app,
            provider=provider,
            alert=alert,
            incident=incident,
            context=context,
            decision=payload.get("decision") if isinstance(payload.get("decision"), dict) else None,
        )
        await _persist_context_event(
            app=app,
            alert=alert,
            incident=incident,
            context=context,
            decision=payload.get("decision") if isinstance(payload.get("decision"), dict) else None,
            provider_used=provider_used,
        )
        EVENTS_PROCESSED.labels(settings.service_name, f"{ORCHESTRATION_EVENTS}:{provider_used}", "ok").inc()

    for source, consumer, consume_forever in _build_ingress_consumers():
        task = asyncio.create_task(consume_forever(consumer, handle), name=f"context-agent-{source}-consumer")
        tasks.append(task)


async def shutdown(app: FastAPI) -> None:
    for task in tasks:
        task.cancel()
    rabbitmq_publisher = getattr(app.state, "rabbitmq_publisher", None)
    if rabbitmq_publisher is not None:
        await rabbitmq_publisher.stop()


app = create_app(title="KaiMS Context Intelligence Agent", settings=settings, startup=startup, shutdown=shutdown)


class RagDocumentRequest(BaseModel):
    kind: str = Field(pattern="^(runbook|incident|deployment|change|dependency|remediation)$")
    alert_id: str | None = Field(default=None, max_length=80)
    alert_type: str | None = Field(default=None, max_length=80)
    severity: str | None = Field(default=None, max_length=32)
    title: str = Field(min_length=3, max_length=160)
    summary: str | None = Field(default=None, min_length=0)
    content: str = Field(min_length=20)
    services: list[str] = Field(default_factory=list)
    deployment: str | None = None
    dependencies: list[str] = Field(default_factory=list)
    change_id: str | None = None
    root_cause: str | None = None
    impact: str | None = None
    execution_plan: str | None = None
    commands: list[str] = Field(default_factory=list)
    scripts: list[str] = Field(default_factory=list)
    queries: list[str] = Field(default_factory=list)
    recommended_action: str | None = None
    source_system: str | None = None
    source_ref: str | None = None
    resolved_by: str | None = None
    closed_at: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class RagDocumentUpdateRequest(RagDocumentRequest):
    path: str = Field(min_length=3)


class EvidenceRagDraftReviewRequest(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=160)
    content: str | None = Field(default=None, min_length=20)
    reviewed_by: str = Field(min_length=2, max_length=120)
    review_notes: str | None = Field(default=None, max_length=2000)


class EvidenceRagDraftApproveRequest(BaseModel):
    approved_by: str = Field(min_length=2, max_length=120)
    title: str | None = Field(default=None, min_length=3, max_length=160)
    content: str | None = Field(default=None, min_length=20)


def _metadata_value(metadata: dict[str, str], *keys: str, default: str = "") -> str:
    for key in keys:
        value = str(metadata.get(key) or "").strip()
        if value:
            return value
    return default


def _http_url_or_default(value: str, default: str) -> str:
    candidate = str(value or "").strip()
    parsed = urlparse(candidate)
    return candidate if parsed.scheme in {"http", "https"} and parsed.netloc else default


def _single_remediation_script(request: RagDocumentRequest) -> str:
    service = (request.services[0] if request.services else request.alert_type or "kaiops-service").strip()
    environment = _metadata_value(request.metadata, "environment", default="prod")
    api_gateway_url = _http_url_or_default(_metadata_value(
        request.metadata,
        "api_gateway_url",
        "apiGatewayUrl",
        "gateway_url",
        default="http://api-gateway:8000",
    ), "http://api-gateway:8000")
    prometheus_url = _http_url_or_default(_metadata_value(
        request.metadata,
        "prometheus_url",
        "monitoring_url",
        "metrics_endpoint",
        default="http://prometheus:9090",
    ), "http://prometheus:9090")
    mysql_host = _metadata_value(request.metadata, "mysql_host", "database_host", default="mysql")
    mysql_database = _metadata_value(request.metadata, "mysql_database", "database_name", default="kaiops")
    mysql_user = _metadata_value(request.metadata, "mysql_user", "database_user", default="kaiops")
    return (
        "bash scripts/remediation/kaiops_alert_health_triage.sh "
        f"--service {shlex.quote(service or 'kaiops-service')} "
        f"--environment {shlex.quote(environment or 'prod')} "
        f"--api-gateway-url {shlex.quote(api_gateway_url)} "
        f"--prometheus-url {shlex.quote(prometheus_url)} "
        f"--mysql-host {shlex.quote(mysql_host)} "
        f"--mysql-database {shlex.quote(mysql_database)} "
        f"--mysql-user {shlex.quote(mysql_user)} "
        "--dry-run true"
    )


def _execution_script_lines(request: RagDocumentRequest) -> list[str]:
    scripts = [str(item).strip() for item in request.scripts if str(item).strip()]
    has_fragments = any(str(item).strip() for item in [*request.commands, *request.queries])
    if scripts:
        return scripts
    if has_fragments:
        return [_single_remediation_script(request)]
    return []


class KnowledgePackSourceDocument(BaseModel):
    name: str = Field(default="uploaded-document", max_length=240)
    category: str | None = Field(default=None, max_length=80)
    text: str = Field(default="", max_length=200_000)
    excerpt: str | None = Field(default=None, max_length=1000)


class KnowledgePackRequest(BaseModel):
    service: str | None = Field(default=None, max_length=128)
    environment: str | None = Field(default=None, max_length=64)
    owner_team: str | None = Field(default=None, max_length=160)
    documents: list[KnowledgePackSourceDocument] = Field(default_factory=list)


class KnowledgePackApproveRequest(KnowledgePackRequest):
    accepted_facts: dict[str, Any] = Field(default_factory=dict)
    approved_by: str | None = Field(default=None, max_length=160)


def vector_connector() -> VectorDBConnector:
    for connector in agent.connectors:
        if isinstance(connector, VectorDBConnector):
            return connector
    raise RuntimeError("VectorDBConnector is not configured")


def knowledge_graph() -> KnowledgeGraph:
    connector = vector_connector()
    if not connector.documents:
        connector.documents = connector.load_documents()
    if connector._knowledge_graph is None:
        connector._knowledge_graph = KnowledgeGraph.from_documents(connector.documents)
    return connector._knowledge_graph


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "document"


def kind_directory(kind: str) -> str:
    return {
        "runbook": "runbooks",
        "incident": "incidents",
        "deployment": "deployments",
        "change": "changes",
        "dependency": "dependencies",
        "remediation": "remediations",
    }[kind]


def _first_match(patterns: list[str], text: str) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
        if match:
            return str(match.group(1) if match.groups() else match.group(0)).strip(" :-\t\r\n")
    return ""


def _unique_tokens(values: list[str], *, limit: int = 12) -> list[str]:
    rows: list[str] = []
    seen: set[str] = set()
    for value in values:
        token = re.sub(r"\s+", " ", str(value or "").strip(" ,.;:-\n\r\t"))
        key = token.lower()
        if not token or key in seen:
            continue
        seen.add(key)
        rows.append(token)
        if len(rows) >= limit:
            break
    return rows


def _fact(value: Any, confidence: float, sources: list[str], status: str | None = None) -> dict[str, Any]:
    present = bool(value if not isinstance(value, list) else len(value))
    return {
        "value": value,
        "confidence": round(float(confidence if present else 0.0), 3),
        "sources": _unique_tokens(sources, limit=8),
        "status": status or ("accepted" if present and confidence >= 0.78 else "needs_review"),
    }


def _compute_knowledge_pack_validation(facts: dict[str, Any]) -> dict[str, Any]:
    required = ["service", "environment", "owner_team", "alert_patterns"]
    recommended = ["dependencies", "commands", "rollback_plan", "validation_checks"]
    missing_required = [key for key in required if not facts[key]["value"]]
    missing_recommended = [key for key in recommended if not facts[key]["value"]]
    low_confidence = [key for key, value in facts.items() if float(value.get("confidence") or 0.0) < 0.7]
    overall_confidence = round(
        sum(float(value.get("confidence") or 0.0) for value in facts.values()) / max(1, len(facts)),
        3,
    )
    return {
        "missing_required": missing_required,
        "missing_recommended": missing_recommended,
        "low_confidence": low_confidence,
        "overall_confidence": overall_confidence,
    }


def _classify_pack_document(name: str, text: str, category: str | None = None) -> str:
    haystack = f"{category or ''} {name} {text}".lower()
    if re.search(r"\b(rca|postmortem|root cause)\b", haystack):
        return "incident"
    if re.search(r"\b(dependency|topology|upstream|downstream|service map)\b", haystack):
        return "dependency"
    if re.search(r"\b(change|deployment|release|rollback)\b", haystack):
        return "change"
    if re.search(r"\b(remediation|restart|failover|scale|script|command|query)\b", haystack):
        return "remediation"
    return "runbook"


def build_knowledge_pack(request: KnowledgePackRequest) -> dict[str, Any]:
    docs = [doc for doc in request.documents if str(doc.text or "").strip()]
    combined = "\n\n".join(f"# {doc.name}\n{doc.text}" for doc in docs)
    source_names = [doc.name for doc in docs]
    service = str(request.service or "").strip() or _first_match(
        [r"\bservice\s*[:=-]\s*([a-zA-Z0-9_.-]+)", r"\bapplication\s*[:=-]\s*([a-zA-Z0-9_.-]+)"],
        combined,
    )
    environment = str(request.environment or "").strip() or _first_match(
        [r"\benvironment\s*[:=-]\s*(prod|production|stage|staging|dev|test)", r"\benv\s*[:=-]\s*(prod|production|stage|staging|dev|test)"],
        combined,
    )
    owner = str(request.owner_team or "").strip() or _first_match(
        [r"\bowner(?:_team|\s+team)?\s*[:=-]\s*([a-zA-Z0-9_.@ -]+)", r"\bteam\s*[:=-]\s*([a-zA-Z0-9_.@ -]+)"],
        combined,
    )
    dependencies = _unique_tokens(
        re.findall(r"(?:depends on|dependency|upstream|downstream)\s*[:=-]\s*([a-zA-Z0-9_.-]+)", combined, flags=re.IGNORECASE)
        + re.findall(r"\b(redis|mysql|postgres|kafka|rabbitmq|servicebus|ledger|fraud|checkout|prometheus|grafana)\b", combined, flags=re.IGNORECASE),
        limit=12,
    )
    alert_patterns = _unique_tokens(
        re.findall(r"(?:alert|monitor|rule)\s*[:=-]\s*([^\n]{8,160})", combined, flags=re.IGNORECASE)
        + re.findall(r"([^\n]*(?:latency|availability|error rate|5xx|cpu|memory|queue|replication|timeout)[^\n]{0,140})", combined, flags=re.IGNORECASE),
        limit=10,
    )
    commands = _unique_tokens(
        re.findall(r"^\s*(?:cmd|command|script|query)?\s*:?\s*((?:kubectl|helm|terraform|ansible-playbook|mysql|redis-cli|curl|powershell|scripts/|\./)[^\n`]+)", combined, flags=re.IGNORECASE | re.MULTILINE),
        limit=10,
    )
    rollback = _unique_tokens(
        re.findall(r"(rollback[^\n]{6,180}|failback[^\n]{6,180}|restore[^\n]{6,180})", combined, flags=re.IGNORECASE),
        limit=6,
    )
    validation_checks = _unique_tokens(
        re.findall(r"(validate[^\n]{6,180}|verify[^\n]{6,180}|check[^\n]{6,180})", combined, flags=re.IGNORECASE),
        limit=8,
    )
    detected_docs = [
        {
            "name": doc.name,
            "category": doc.category or _classify_pack_document(doc.name, doc.text),
            "detected_kind": _classify_pack_document(doc.name, doc.text, doc.category),
            "excerpt": (doc.excerpt or re.sub(r"\s+", " ", doc.text).strip()[:220]),
        }
        for doc in docs
    ]
    facts = {
        "service": _fact(service, 0.96 if request.service else 0.78, source_names),
        "environment": _fact(environment or "prod", 0.92 if request.environment else 0.68, source_names, status="accepted" if environment else "needs_review"),
        "owner_team": _fact(owner, 0.92 if request.owner_team else 0.7, source_names),
        "dependencies": _fact(dependencies, 0.82 if dependencies else 0.0, source_names),
        "alert_patterns": _fact(alert_patterns, 0.84 if alert_patterns else 0.0, source_names),
        "commands": _fact(commands, 0.8 if commands else 0.0, source_names),
        "rollback_plan": _fact(rollback, 0.78 if rollback else 0.0, source_names),
        "validation_checks": _fact(validation_checks, 0.8 if validation_checks else 0.0, source_names),
    }
    validation = _compute_knowledge_pack_validation(facts)
    missing_required = validation["missing_required"]
    missing_recommended = validation["missing_recommended"]
    low_confidence = validation["low_confidence"]
    return {
        "contract_version": "kaiops.knowledge-pack.v1",
        "status": "ready" if not missing_required and not low_confidence[:1] else "needs_review",
        "document_count": len(docs),
        "detected_documents": detected_docs,
        "facts": facts,
        "validation": validation,
        "next_questions": [
            question
            for key, question in {
                "service": "Which service/application is this knowledge pack for?",
                "owner_team": "Who owns this service?",
                "alert_patterns": "Which alert pattern or monitor should KaiOps use for this service?",
                "rollback_plan": "What rollback or failback plan should be used if remediation fails?",
                "validation_checks": "How should KaiOps verify recovery after remediation?",
            }.items()
            if key in missing_required or key in missing_recommended or key in low_confidence
        ][:5],
    }


def _knowledge_pack_to_rag_request(pack: dict[str, Any], approved_by: str | None = None) -> RagDocumentRequest:
    facts = pack.get("facts") if isinstance(pack.get("facts"), dict) else {}

    def fact_value(key: str, default: Any = "") -> Any:
        row = facts.get(key) if isinstance(facts.get(key), dict) else {}
        value = row.get("value", default)
        return value if value not in (None, "") else default

    service = str(fact_value("service", "unknown-service")).strip() or "unknown-service"
    environment = str(fact_value("environment", "prod")).strip() or "prod"
    owner = str(fact_value("owner_team", approved_by or "unassigned")).strip() or "unassigned"
    dependencies = fact_value("dependencies", [])
    commands = fact_value("commands", [])
    validation = fact_value("validation_checks", [])
    rollback = fact_value("rollback_plan", [])
    alert_patterns = fact_value("alert_patterns", [])
    content = "\n".join(
        [
            f"Knowledge pack for {service} in {environment}.",
            "",
            "Alert patterns:",
            *[f"- {item}" for item in (alert_patterns if isinstance(alert_patterns, list) else [alert_patterns]) if str(item).strip()],
            "",
            "Dependencies:",
            *[f"- {item}" for item in (dependencies if isinstance(dependencies, list) else [dependencies]) if str(item).strip()],
            "",
            "Validation checks:",
            *[f"- {item}" for item in (validation if isinstance(validation, list) else [validation]) if str(item).strip()],
            "",
            "Rollback plan:",
            *[f"- {item}" for item in (rollback if isinstance(rollback, list) else [rollback]) if str(item).strip()],
        ]
    ).strip()
    return RagDocumentRequest(
        kind="runbook",
        title=f"{service} Knowledge Pack",
        summary=f"Approved KaiOps knowledge pack for {service}.",
        content=content or f"Approved KaiOps knowledge pack for {service}.",
        services=[service],
        dependencies=dependencies if isinstance(dependencies, list) else [],
        commands=commands if isinstance(commands, list) else [],
        queries=validation if isinstance(validation, list) else [],
        source_system="knowledge-pack",
        resolved_by=owner,
        metadata={
            "environment": environment,
            "knowledge_pack_status": str(pack.get("status") or "approved"),
            "knowledge_pack_confidence": str((pack.get("validation") or {}).get("overall_confidence", "")),
        },
    )


def render_document(request: RagDocumentRequest) -> str:
    metadata: dict[str, Any] = {
        "kind": request.kind,
        "title": request.title,
    }
    if request.alert_id:
        metadata["alert_id"] = request.alert_id
    if request.alert_type:
        metadata["alert_type"] = request.alert_type
    if request.severity:
        metadata["severity"] = request.severity.lower()
    if request.services:
        metadata["services"] = ", ".join(request.services)
    if request.deployment:
        metadata["deployment"] = request.deployment
    if request.dependencies:
        metadata["dependencies"] = ", ".join(request.dependencies)
    if request.change_id:
        metadata["change_id"] = request.change_id
    if request.source_system:
        metadata["source_system"] = request.source_system
    if request.source_ref:
        metadata["source_ref"] = request.source_ref
    if request.resolved_by:
        metadata["resolved_by"] = request.resolved_by
    if request.closed_at:
        metadata["closed_at"] = request.closed_at
    if request.root_cause:
        metadata["root_cause"] = request.root_cause
    if request.impact:
        metadata["impact"] = request.impact
    if request.execution_plan:
        metadata["execution_plan"] = request.execution_plan
    if request.recommended_action:
        metadata["recommended_action"] = request.recommended_action
    metadata.update(request.metadata)
    header = "\n".join(f"{key}: {value}" for key, value in metadata.items())
    body_lines = [f"# {request.title}"]
    if request.summary:
        body_lines.extend(["", "## Summary", request.summary.strip()])
    if request.content.strip():
        body_lines.extend(["", "## Description", request.content.strip()])
    if request.root_cause:
        body_lines.extend(["", "## Root Cause", request.root_cause.strip()])
    if request.impact:
        body_lines.extend(["", "## Impact", request.impact.strip()])
    if request.execution_plan:
        body_lines.extend(["", "## Execution Plan", request.execution_plan.strip()])
    script_lines = _execution_script_lines(request)
    if script_lines:
        body_lines.extend(["", "## Remediation Script"])
        for item in script_lines:
            body_lines.extend(["```bash", item, "```"])
    elif request.commands:
        body_lines.extend(["", "## Commands", *[f"- {item}" for item in request.commands if str(item).strip()]])
    return f"{header}\n\n" + "\n".join(body_lines).rstrip() + "\n"


def write_rag_document(request: RagDocumentRequest) -> dict[str, Any]:
    connector = vector_connector()
    root = connector.root_path()
    target_dir = root / kind_directory(request.kind)
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except FileExistsError:
        if not (target_dir.exists() and target_dir.is_dir()):
            fallback_root = Path("/tmp/kaiops/rag")
            target_dir = fallback_root / kind_directory(request.kind)
            target_dir.mkdir(parents=True, exist_ok=True)
    base_name = slugify(request.alert_id or request.title)
    target = target_dir / f"{base_name}.md"
    if not request.alert_id:
        counter = 2
        while target.exists():
            target = target_dir / f"{base_name}-{counter}.md"
            counter += 1
    target.write_text(render_document(request), encoding="utf-8")
    count = connector.reload()
    return {"path": str(target), "document_count": count, "index": connector.index_info()}


def write_rag_document_to_path(request: RagDocumentRequest, path: str) -> dict[str, Any]:
    connector = vector_connector()
    root = connector.root_path().resolve()
    target = Path(path).expanduser().resolve()
    if root not in target.parents:
        raise HTTPException(status_code=400, detail="Document path is outside the RAG directory")
    if target.suffix.lower() != ".md":
        raise HTTPException(status_code=400, detail="Document path must end with .md")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_document(request), encoding="utf-8")
    count = connector.reload()
    return {"path": str(target), "document_count": count, "index": connector.index_info()}


def _evidence_draft_dir() -> Path:
    # JSON drafts deliberately live outside the Markdown index. They cannot
    # participate in grounding until an explicit approval promotes them.
    target = vector_connector().root_path() / "_review"
    target.mkdir(parents=True, exist_ok=True)
    return target


def _draft_path(draft_id: str) -> Path:
    safe_id = slugify(draft_id)
    target = (_evidence_draft_dir() / f"{safe_id}.json").resolve()
    if _evidence_draft_dir().resolve() not in target.parents:
        raise HTTPException(status_code=400, detail="invalid draft id")
    return target


def _read_evidence_draft(draft_id: str) -> dict[str, Any]:
    path = _draft_path(draft_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="evidence RAG draft not found")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=500, detail="evidence RAG draft is unreadable") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="evidence RAG draft is invalid")
    return payload


def _write_evidence_draft(payload: dict[str, Any]) -> dict[str, Any]:
    draft_id = str(payload.get("draft_id") or "").strip()
    if not draft_id:
        raise ValueError("draft_id is required")
    _draft_path(draft_id).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


_GENERIC_EVIDENCE_TERMS = {
    "alert", "application", "critical", "error", "failed", "failure",
    "high", "incident", "monitor", "monitoring", "prod", "production",
    "service", "validation", "warning",
}


def _alert_identity_terms(alert: Alert) -> set[str]:
    raw_labels = getattr(alert, "labels", {})
    labels = raw_labels if isinstance(raw_labels, dict) else {}
    values = [
        alert.service,
        alert.name,
        labels.get("application"),
        labels.get("project"),
        labels.get("project_name"),
        labels.get("monitor_id"),
    ]
    terms: set[str] = set()
    for value in values:
        for token in re.findall(r"[a-z0-9][a-z0-9_.-]{2,}", str(value or "").lower()):
            if token not in _GENERIC_EVIDENCE_TERMS:
                terms.add(token)
    return terms


def _evidence_matches_alert(row: dict[str, Any], identity_terms: set[str]) -> bool:
    if not identity_terms:
        return False
    haystack = " ".join(
        str(row.get(key) or "")
        for key in ("source", "snippet", "summary", "uri", "path", "title")
    ).lower()
    return any(term in haystack for term in identity_terms)


def create_evidence_rag_draft(*, alert: Alert, incident: Incident, context: Context) -> dict[str, Any] | None:
    metadata = context.metadata if isinstance(context.metadata, dict) else {}
    discovery = metadata.get("discovery_report") if isinstance(metadata.get("discovery_report"), dict) else {}
    report = discovery.get("report") if isinstance(discovery.get("report"), dict) else {}
    evidence = discovery.get("evidence") if isinstance(discovery.get("evidence"), list) else []
    identity_terms = _alert_identity_terms(alert)
    grounded = [
        row for row in evidence
        if isinstance(row, dict)
        and str(row.get("evidence_id") or "").strip()
        and _evidence_matches_alert(row, identity_terms)
    ]
    if not grounded:
        return None
    draft_id = f"evidence-{alert.id}"
    path = _draft_path(draft_id)
    if path.exists():
        return _read_evidence_draft(draft_id)
    evidence_lines = [
        f"- [{row.get('evidence_id')}] {row.get('source', 'evidence')}: "
        f"{str(row.get('snippet') or row.get('summary') or '').strip()[:1200]} "
        f"({row.get('uri') or row.get('path') or 'source unavailable'})"
        for row in grounded[:40]
    ]
    hypotheses = report.get("hypotheses") if isinstance(report.get("hypotheses"), list) else []
    hypothesis_lines = [
        f"- {str(item.get('cause') or '').strip()} (confidence {item.get('confidence', 0)})"
        for item in hypotheses[:8]
        if isinstance(item, dict) and str(item.get("cause") or "").strip()
    ]
    content = "\n".join(
        [
            "## Alert",
            f"{alert.name} on {alert.service} ({alert.environment})",
            "",
            "## Evidence-backed summary",
            str(report.get("summary") or "Evidence collected; user review is required before grounding."),
            "",
            "## Hypotheses",
            *(hypothesis_lines or ["- No grounded hypothesis was produced."]),
            "",
            "## Collected evidence",
            *evidence_lines,
        ]
    )
    now = datetime.now(timezone.utc).isoformat()
    return _write_evidence_draft(
        {
            "draft_id": draft_id,
            "status": "draft",
            "alert_id": str(alert.id),
            "incident_id": str(incident.id),
            "alert_type": alert.name,
            "severity": str(getattr(alert.severity, "value", alert.severity)),
            "title": f"Evidence review: {alert.name}",
            "content": content,
            "services": [alert.service],
            "evidence_ids": [str(row["evidence_id"]) for row in grounded],
            "source_uris": [str(row.get("uri") or row.get("path") or "") for row in grounded if row.get("uri") or row.get("path")],
            "created_at": now,
            "updated_at": now,
            "reviewed_by": None,
            "review_notes": None,
            "approved_by": None,
            "approved_at": None,
            "rag_document_path": None,
            "evidence_relevance": {
                "verified": True,
                "identity_terms": sorted(identity_terms),
                "relevant_count": len(grounded),
                "retrieved_count": len(evidence),
            },
        }
    )


def _normalize_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def _first_content_line(content: str, fallback: str) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped
    return fallback


def rebuild_flow_catalog_from_rag(connector: VectorDBConnector) -> None:
    catalog_path = connector.root_path() / "flows.json"
    entries: list[dict[str, Any]] = []
    for doc in connector.documents:
        if str(doc.get("kind", "")).strip().lower() != "incident":
            continue
        full_doc = connector._load_full_document(str(doc.get("path", "")))
        alert_id = str(full_doc.get("alert_id") or full_doc.get("id") or "").strip()
        alert_name = str(full_doc.get("alert_name") or full_doc.get("title") or "Incident").strip() or "Incident"
        flow_id = slugify(alert_id or alert_name)
        services = _normalize_list(full_doc.get("services", []))
        service = services[0] if services else str(full_doc.get("service", "unknown")).strip() or "unknown"
        severity = str(full_doc.get("severity", "HIGH")).upper().strip()
        if severity not in {"CRITICAL", "HIGH", "WARNING"}:
            severity = "HIGH"
        recommended_action = str(full_doc.get("recommended_action") or full_doc.get("remediation_comment") or "Investigate issue")
        content = str(full_doc.get("content", "")).strip()
        summary = str(full_doc.get("summary") or _first_content_line(content, alert_name)).strip()
        execution_plan = str(full_doc.get("execution_plan") or "").strip()
        alert_type = str(full_doc.get("alert_type", "")).strip()
        entry = {
            "id": flow_id,
            "alert_id": alert_id or flow_id.upper(),
            "alert_name": alert_name,
            "alert_type": alert_type,
            "title": alert_name,
            "service": service,
            "severity": severity,
            "summary": summary[:220],
            "recommended_action": recommended_action,
            "description": summary[:220],
            "execution_plan": execution_plan[:220] or None,
            "deployment": str(full_doc.get("deployment", "")).strip() or None,
            "change_id": str(full_doc.get("change_id", "")).strip() or None,
            "root_cause": str(full_doc.get("root_cause", "")).strip() or None,
            "impact": str(full_doc.get("impact", "")).strip() or None,
            "source": "rag-incident",
        }
        entries.append({k: v for k, v in entry.items() if v not in (None, "")})

    by_id = {str(item.get("id")): item for item in entries if item.get("id")}
    merged = list(by_id.values())
    merged.sort(key=lambda item: str(item.get("title", "")).lower())
    catalog_path.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    markdown_path = connector.root_path() / "flows.md"
    markdown_path.write_text(render_flow_catalog_markdown(merged), encoding="utf-8")


def render_flow_catalog_markdown(entries: list[dict[str, Any]]) -> str:
    field_labels = [
        ("service", "Service"),
        ("severity", "Severity"),
        ("alert_type", "Alert Type"),
        ("alert_id", "Alert ID"),
        ("summary", "Summary"),
        ("recommended_action", "Recommended Action"),
        ("root_cause", "Root Cause"),
        ("impact", "Impact"),
        ("deployment", "Deployment"),
        ("change_id", "Change ID"),
        ("execution_plan", "Execution Plan"),
    ]
    lines = [
        "# Alert Flow Catalog",
        "",
        "_Auto-generated from RAG incident documents whenever flows.json is rebuilt. "
        "Edit the source incident docs and resubmit them — this file is overwritten "
        "on every rebuild and excluded from RAG document matching._",
        "",
    ]
    if not entries:
        lines.append("_No incident-kind RAG documents are currently onboarded._")
    for entry in entries:
        title = str(entry.get("title") or entry.get("alert_name") or "Untitled Alert")
        lines.append(f"## {title}")
        for key, label in field_labels:
            value = entry.get(key)
            if value not in (None, ""):
                lines.append(f"- **{label}:** {value}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def read_flow_catalog(connector: VectorDBConnector) -> list[dict[str, Any]]:
    catalog_path = connector.root_path() / "flows.json"
    if not catalog_path.exists():
        return []
    try:
        data = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


@app.post("/collect", response_model=Context)
async def collect(payload: dict, publish_events: bool = True) -> Context:
    alert = Alert.model_validate(payload["alert"])
    incident = Incident.model_validate(payload["incident"])
    context = await _collect_context_with_strategy(
        app, alert, incident, payload.get("context_strategy"), payload.get("context")
    )
    if publish_events:
        await app.state.producer.publish(
            CONTEXT_EVENTS,
            {
                "context": context,
                "incident": incident,
                "decision": payload.get("decision"),
            },
            key=alert.service,
        )
    return context


@app.get("/context/strategy")
async def context_strategy_status() -> dict[str, Any]:
    return {
        "default": _context_strategy(),
        "supported": ["auto", "realtime", "historical"],
        "auto": {
            "cache_aside": True,
            "ttl_seconds": int(getattr(settings, "context_knowledge_ttl_seconds", 0) or 0) or None,
            "refresh_policy": "new_type_or_unqualified_knowledge",
            "match_scope": ["tenant", "service", "environment", "alert-family"],
            "resolution_reuse_enabled": bool(getattr(settings, "context_resolution_reuse_enabled", True)),
            "resolution_reuse_min_score": float(getattr(settings, "context_resolution_reuse_min_score", 0.7) or 0.7),
        },
        "realtime": {"always_refresh": True},
        "historical": {"always_refresh": False, "cache_miss_collects_realtime": False},
    }


@app.post("/rag/documents")
async def ingest_rag_document(request: RagDocumentRequest) -> dict[str, Any]:
    result = write_rag_document(request)
    if request.kind == "incident":
        rebuild_flow_catalog_from_rag(vector_connector())
    document_flag_updated = False
    if request.alert_id and settings.database_enabled and getattr(app.state, "session_factory", None) is not None:
        async with app.state.session_factory() as session:
            repo = IncidentRepository(session)
            document_flag_updated = await repo.update_projection_document_flag(request.alert_id, True)
            await session.commit()
    return {"status": "ingested", "document_flag_updated": document_flag_updated, **result}


def _list_evidence_rag_drafts_sync(alert_id: str | None, status: str | None) -> list[dict[str, Any]]:
    if alert_id:
        path = _draft_path(f"evidence-{alert_id}")
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if not isinstance(payload, dict) or str(payload.get("alert_id") or "") != alert_id:
            return []
        if status and str(payload.get("status") or "").lower() != status.lower():
            return []
        return [payload]

    drafts: list[dict[str, Any]] = []
    for path in sorted(_evidence_draft_dir().glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        if status and str(payload.get("status") or "").lower() != status.lower():
            continue
        drafts.append(payload)
    return drafts


@app.get("/rag/evidence-drafts")
async def list_evidence_rag_drafts(alert_id: str | None = None, status: str | None = None) -> dict[str, Any]:
    # The review directory can live on a high-latency bind mount. Never block
    # RabbitMQ heartbeats and incident consumers while walking/stat-ing it.
    drafts = await asyncio.to_thread(_list_evidence_rag_drafts_sync, alert_id, status)
    return {"count": len(drafts), "drafts": drafts}


@app.post("/rag/evidence-drafts")
async def create_evidence_rag_draft_from_rca(request: dict[str, Any]) -> dict[str, Any]:
    """Create the reviewable alert document when the RCA pipeline has no draft."""
    alert_id = str(request.get("alert_id") or "").strip()
    content = str(request.get("content") or "").strip()
    if not alert_id:
        raise HTTPException(status_code=422, detail="alert_id is required")
    if len(content) < 20:
        raise HTTPException(status_code=422, detail="grounded RCA content is required")
    draft_id = f"evidence-{alert_id}"
    path = _draft_path(draft_id)
    if path.exists():
        return {"status": "existing", "draft": _read_evidence_draft(draft_id)}
    now = datetime.now(timezone.utc).isoformat()
    draft = _write_evidence_draft({
        "draft_id": draft_id,
        "status": "draft",
        "alert_id": alert_id,
        "incident_id": str(request.get("incident_id") or ""),
        "alert_type": str(request.get("alert_type") or "Alert"),
        "severity": str(request.get("severity") or "unknown"),
        "title": str(request.get("title") or f"RCA review: {request.get('alert_type') or alert_id}"),
        "content": content,
        "services": [str(item) for item in request.get("services", []) if str(item).strip()],
        "evidence_ids": [str(item) for item in request.get("evidence_ids", []) if str(item).strip()],
        "source_uris": [str(item) for item in request.get("source_uris", []) if str(item).strip()],
        "created_at": now, "updated_at": now, "reviewed_by": None,
        "review_notes": None, "approved_by": None, "approved_at": None,
        "rag_document_path": None,
    })
    return {"status": "created", "draft": draft}


@app.put("/rag/evidence-drafts/{draft_id}")
async def review_evidence_rag_draft(
    draft_id: str,
    request: EvidenceRagDraftReviewRequest,
) -> dict[str, Any]:
    draft = _read_evidence_draft(draft_id)
    if str(draft.get("status") or "") == "approved":
        raise HTTPException(status_code=409, detail="approved evidence documents cannot be edited")
    if request.title is not None:
        draft["title"] = request.title.strip()
    if request.content is not None:
        draft["content"] = request.content.strip()
    draft["status"] = "reviewed"
    draft["reviewed_by"] = request.reviewed_by.strip()
    draft["review_notes"] = str(request.review_notes or "").strip() or None
    draft["updated_at"] = datetime.now(timezone.utc).isoformat()
    return {"status": "reviewed", "draft": _write_evidence_draft(draft)}


@app.post("/rag/evidence-drafts/{draft_id}/approve")
async def approve_evidence_rag_draft(
    draft_id: str,
    request: EvidenceRagDraftApproveRequest,
) -> dict[str, Any]:
    draft = _read_evidence_draft(draft_id)
    if str(draft.get("status") or "") == "approved":
        return {"status": "approved", "draft": draft, "already_approved": True}
    title = str(request.title or draft.get("title") or "").strip()
    content = str(request.content or draft.get("content") or "").strip()
    if len(content) < 20:
        raise HTTPException(status_code=422, detail="approved evidence content is too short")
    approved_at = datetime.now(timezone.utc).isoformat()
    rag_request = RagDocumentRequest(
        kind="incident",
        alert_id=str(draft.get("alert_id") or "") or None,
        alert_type=str(draft.get("alert_type") or "") or None,
        severity=str(draft.get("severity") or "") or None,
        title=title,
        summary="User-reviewed evidence document approved for future grounding.",
        content=content,
        services=[str(item) for item in draft.get("services", []) if str(item).strip()],
        source_system="kaiops-evidence-review",
        source_ref=f"evidence-draft://{draft_id}",
        resolved_by=request.approved_by.strip(),
        metadata={
            "approval_status": "approved",
            "approved_by": request.approved_by.strip(),
            "approved_at": approved_at,
            "incident_id": str(draft.get("incident_id") or ""),
            "evidence_ids": ", ".join(str(item) for item in draft.get("evidence_ids", [])),
        },
    )
    result = write_rag_document(rag_request)
    draft.update(
        {
            "status": "approved",
            "title": title,
            "content": content,
            "approved_by": request.approved_by.strip(),
            "approved_at": approved_at,
            "updated_at": approved_at,
            "rag_document_path": result["path"],
        }
    )
    _write_evidence_draft(draft)
    return {"status": "approved", "draft": draft, "rag_document": result}


@app.post("/knowledge-pack/draft")
async def draft_knowledge_pack(request: KnowledgePackRequest) -> dict[str, Any]:
    pack = build_knowledge_pack(request)
    return {"status": "drafted", "knowledge_pack": pack}


@app.post("/knowledge-pack/validate")
async def validate_knowledge_pack(request: KnowledgePackRequest) -> dict[str, Any]:
    pack = build_knowledge_pack(request)
    return {
        "status": pack.get("status", "needs_review"),
        "knowledge_pack": pack,
        "validation": pack.get("validation", {}),
        "next_questions": pack.get("next_questions", []),
    }


@app.post("/knowledge-pack/approve")
async def approve_knowledge_pack(request: KnowledgePackApproveRequest) -> dict[str, Any]:
    pack = build_knowledge_pack(request)
    facts = pack.get("facts") if isinstance(pack.get("facts"), dict) else {}
    for key, value in request.accepted_facts.items():
        fact = facts.get(key) if isinstance(facts.get(key), dict) else None
        if fact is None:
            facts[key] = _fact(value, 0.9, ["manual-review"], status="accepted")
            continue
        fact["value"] = value
        fact["status"] = "accepted"
        fact["confidence"] = max(float(fact.get("confidence") or 0.0), 0.9)
        sources = fact.get("sources") if isinstance(fact.get("sources"), list) else []
        fact["sources"] = _unique_tokens([*sources, "manual-review"], limit=8)
    pack["facts"] = facts
    # accepted_facts overrides above change confidence/status per field, so
    # validation stats (esp. overall_confidence) must be recomputed here —
    # otherwise the persisted knowledge_pack_confidence reflects the stale
    # pre-override extraction average instead of what was actually approved.
    pack["validation"] = _compute_knowledge_pack_validation(facts)
    pack["status"] = "approved"
    rag_request = _knowledge_pack_to_rag_request(pack, request.approved_by)
    result = write_rag_document(rag_request)
    runbook_id = str(uuid5(NAMESPACE_URL, rag_request.content))
    governance = {"runbook_id": runbook_id, "version": 1, "status": "approved"}
    if settings.database_enabled and getattr(app.state, "session_factory", None) is not None:
        async with app.state.session_factory() as session:
            governance = await IncidentRepository(session).approve_runbook_version(
                runbook_id=runbook_id, version=1, approved_by=request.approved_by,
                payload={"rag_document": result, "knowledge_pack": pack},
            )
            await session.commit()
    return {"status": "approved", "knowledge_pack": pack, "rag_document": result, "runbook_governance": governance}


@app.put("/rag/documents")
async def update_rag_document(request: RagDocumentUpdateRequest) -> dict[str, Any]:
    payload = request.model_dump(exclude={"path"})
    result = write_rag_document_to_path(RagDocumentRequest(**payload), request.path)
    if request.kind == "incident":
        rebuild_flow_catalog_from_rag(vector_connector())
    document_flag_updated = False
    if request.alert_id and settings.database_enabled and getattr(app.state, "session_factory", None) is not None:
        async with app.state.session_factory() as session:
            repo = IncidentRepository(session)
            document_flag_updated = await repo.update_projection_document_flag(request.alert_id, True)
            await session.commit()
    return {"status": "updated", "document_flag_updated": document_flag_updated, **result}


_RAG_DOCUMENT_INTERNAL_FIELDS = {"_embedding", "_metadata_embedding", "_synthetic"}


def _public_rag_document(doc: dict[str, Any], connector: VectorDBConnector) -> dict[str, Any]:
    public = {key: value for key, value in doc.items() if key not in _RAG_DOCUMENT_INTERNAL_FIELDS}
    full_doc = connector._load_full_document(str(doc.get("path", "")))
    embedding_status = "embedded" if isinstance(doc.get("_metadata_embedding"), list) else "pending"
    if full_doc and not isinstance(full_doc.get("_embedding"), list):
        embedding_status = "metadata-only"
    public.setdefault("owner", str(public.get("resolved_by") or public.get("source_system") or "unassigned"))
    public.setdefault("version", str(public.get("version") or "v1"))
    public.setdefault("freshness_score", 1.0 if public.get("closed_at") or public.get("source_ref") else 0.75)
    public["embedding_status"] = embedding_status
    public["embedding_model"] = connector.embedding_info()
    public["vector_store"] = connector.vector_store_info()
    return public


@app.get("/rag/documents")
def list_rag_documents() -> dict[str, Any]:
    """Build the potentially large catalog on FastAPI's worker pool.

    Connector metadata and document projection are synchronous and can take
    seconds for a large RAG corpus. A synchronous route keeps that work off
    the event loop so health checks and incident consumers stay responsive.
    """
    connector = vector_connector()
    documents = [doc for doc in connector.documents if not doc.get("_synthetic")]
    return {
        "document_count": len(documents),
        "index": connector.index_info(),
        "documents": [_public_rag_document(doc, connector) for doc in documents],
    }


@app.get("/rag/documents/content")
async def get_rag_document_content(path: str) -> dict[str, Any]:
    connector = vector_connector()
    known_paths = {str(doc.get("path", "")) for doc in connector.documents}
    if path not in known_paths:
        raise HTTPException(status_code=404, detail="document not found")
    full_doc = connector._load_full_document(path)
    if not full_doc:
        raise HTTPException(status_code=404, detail="document not found")
    return {key: value for key, value in full_doc.items() if key not in _RAG_DOCUMENT_INTERNAL_FIELDS}


@app.post("/rag/reload")
async def reload_rag() -> dict[str, Any]:
    connector = vector_connector()
    count = await asyncio.to_thread(connector.reload)
    rebuild_flow_catalog_from_rag(connector)
    return {"status": "reloaded", "document_count": count, "index": connector.index_info()}


@app.get("/rag/index")
async def get_rag_index() -> dict[str, Any]:
    connector = vector_connector()
    return connector.index_info()


@app.get("/knowledge-graph")
async def get_knowledge_graph() -> dict[str, Any]:
    graph = knowledge_graph()
    return {"status": "ready", "summary": graph.summary(), "nodes": list(graph.nodes.values()), "edges": graph.edges}


@app.get("/knowledge-graph/context")
async def get_knowledge_graph_context(service: str, depth: int = 2, limit: int = 80) -> dict[str, Any]:
    return knowledge_graph().context(service, depth=max(0, min(depth, 4)), limit=max(1, min(limit, 250)))


@app.post("/rag/index/sync")
async def sync_rag_index() -> dict[str, Any]:
    connector = vector_connector()
    result = connector.sync_remote_index()
    return {"status": "synced" if result.get("indexed", 0) else "skipped", "result": result, "index": connector.index_info()}


@app.get("/rag/search")
async def search_rag(query: str, limit: int = 8, kind: str | None = None) -> dict[str, Any]:
    matches = vector_connector().search(
        query,
        limit=max(1, min(limit, 20)),
        preferred_kind=kind,
    )
    return {
        "query": query,
        "index": vector_connector().index_info(),
        "matches": [
            {
                "kind": match.get("kind"),
                "title": match.get("title"),
                "services": match.get("services", []),
                "deployment": match.get("deployment"),
                "path": match.get("path"),
                "score": match.get("_similarity", 0.0),
                "embedding_model": vector_connector().embedding_info(),
                "vector_store": vector_connector().vector_store_info(),
                "preview": str(match.get("content", ""))[:300],
            }
            for match in matches
        ],
    }


@app.get("/rag/flow-catalog")
async def flow_catalog() -> dict[str, Any]:
    connector = vector_connector()
    entries = read_flow_catalog(connector)
    return {
        "count": len(entries),
        "entries": entries,
        "path": str(connector.root_path() / "flows.json"),
    }
