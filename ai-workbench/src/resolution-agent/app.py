from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable, Coroutine
from datetime import UTC, datetime
from time import monotonic
from typing import Any
from uuid import UUID, uuid4

import httpx
from ai_workbench_common.models import Context
from common.config import get_settings
from common.event_publishers import build_agent_event_contract, build_event_envelope
from common.kafka import KafkaConsumer
from common.kafka import consume_forever as consume_kafka_forever
from common.models import Incident, Recommendation
from common.rabbitmq import RabbitMQConsumer
from common.rabbitmq import consume_forever as consume_rabbitmq_forever
from common.repository import IncidentRepository
from common.service import create_app
from common.telemetry import CONTEXT_KNOWLEDGE_OPERATIONS, EVENTS_PROCESSED
from common.topics import CONTEXT_EVENTS, RESOLUTION_EVENTS
from fastapi import FastAPI
from pydantic import BaseModel, Field
from resolution_agent import ResolutionIntelligenceAgent
from resolution_agent.catalog import (
    RESOLUTION_CATALOG,
    prepare_resolution_plan,
    register_global_knowledge,
    relevant_resolutions,
)

settings = get_settings()
settings.service_name = "resolution-agent"
agent = ResolutionIntelligenceAgent()
tasks: list[asyncio.Task] = []
_GLOBAL_KNOWLEDGE_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_GLOBAL_KNOWLEDGE_CACHE_TTL_SECONDS = 300.0
_GLOBAL_KNOWLEDGE_CACHE_MAX_ENTRIES = 256
MESSAGE_BUS_DUAL_CONSUME_ENABLED = str(os.getenv("MESSAGE_BUS_DUAL_CONSUME_ENABLED", "false")).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

ConsumeRunner = Callable[[Any, Callable[[dict], Awaitable[None]]], Coroutine[Any, Any, None]]


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


def _resolution_reuse_threshold() -> float:
    configured = float(getattr(settings, "context_resolution_reuse_min_score", 0.7) or 0.7)
    return max(0.0, min(configured, 1.0))


async def _resolve_context(context: Context) -> Recommendation:
    metadata = context.metadata if isinstance(context.metadata, dict) else {}
    prior = metadata.get("prior_resolution") if isinstance(metadata.get("prior_resolution"), dict) else {}
    score = _resolution_quality_score(prior)
    may_reuse = (
        bool(getattr(settings, "context_resolution_reuse_enabled", True))
        and bool(metadata.get("context_reused"))
        and not bool(metadata.get("force_full_analysis"))
        and score > _resolution_reuse_threshold()
    )
    if not may_reuse:
        return await agent.resolve_with_runtime(context)
    try:
        cached_recommendation = Recommendation.model_validate(prior)
    except Exception:
        CONTEXT_KNOWLEDGE_OPERATIONS.labels("reuse_resolution", "invalid").inc()
        return await agent.resolve_with_runtime(context)
    recommendation = cached_recommendation.model_copy(
        update={
            "id": uuid4(),
            "created_at": datetime.now(UTC),
            "incident_id": context.incident_id,
            "trace_id": str(context.alert.trace_id or "") or None,
        }
    )
    recommendation.metadata = {
        **(recommendation.metadata if isinstance(recommendation.metadata, dict) else {}),
        "analysis_reused": True,
        "analysis_source": "qualified_context_resolution_cache",
        "analysis_source_incident_id": metadata.get("context_source_incident_id"),
        "analysis_source_alert_id": metadata.get("context_source_alert_id"),
        "analysis_reuse_score": score,
        "analysis_reuse_threshold": _resolution_reuse_threshold(),
        "analysis_reused_at": datetime.now(UTC).isoformat(),
    }
    CONTEXT_KNOWLEDGE_OPERATIONS.labels("reuse_resolution", "success").inc()
    return recommendation


def _build_resolution_event_payload(
    *,
    context: Context,
    incident: Incident,
    recommendation: Recommendation,
    decision_payload: dict[str, Any],
) -> dict[str, Any]:
    flow_id = str(decision_payload.get("flow_id") or incident.id)
    event_contract = build_agent_event_contract(
        flow_id=flow_id,
        incident_id=str(incident.id),
        trace_id=str(incident.trace_id or context.alert.trace_id or ""),
        correlation_id=str(context.alert.correlation_id or "") or None,
        agent="resolution-agent",
        payload={
            "recommended_action": recommendation.recommended_action,
            "risk": recommendation.risk,
            "topic": RESOLUTION_EVENTS,
        },
        metadata={
            "policy_version": recommendation.metadata.get("policy_version"),
            "policy_reason": recommendation.metadata.get("policy_reason"),
            "workflow": decision_payload.get("workflow"),
        },
        confidence=float(recommendation.confidence),
        reasoning=str(recommendation.metadata.get("reasoning") or recommendation.rationale or ""),
        citations=list(recommendation.metadata.get("citations", [])),
        evidence_ids=list(recommendation.metadata.get("evidence_ids", [])),
    )
    return {
        "recommendation": recommendation,
        "context": context,
        "incident": incident,
        "decision": decision_payload,
        "event_contract": event_contract,
    }


async def _persist_resolution_event(
    *,
    app: FastAPI,
    context: Context,
    incident: Incident,
    recommendation: Recommendation,
    decision_payload: dict[str, Any],
) -> None:
    if not settings.database_enabled or getattr(app.state, "session_factory", None) is None:
        return
    metadata = recommendation.metadata if isinstance(recommendation.metadata, dict) else {}
    orchestration = (
        metadata.get("orchestration_decision") if isinstance(metadata.get("orchestration_decision"), dict) else {}
    )
    requires_approval = decision_payload.get("requires_approval")
    if requires_approval is None:
        requires_approval = orchestration.get("requires_approval")
    status = "awaiting_approval" if bool(requires_approval) else "remediating"
    provider = decision_payload.get("message_bus_provider") or orchestration.get("message_bus_provider") or "unknown"
    async with app.state.session_factory() as session:
        repo = IncidentRepository(session)
        await repo.save_incident_event(
            build_event_envelope(
                event_type="incident.recommendation.generated",
                identity={
                    "incident_id": str(incident.id),
                    "alert_id": str(context.alert.id),
                    "trace_id": str(incident.trace_id or context.alert.trace_id or ""),
                    "correlation_id": str(context.alert.correlation_id or "") or None,
                    "causation_id": None,
                    "parent_event_id": None,
                },
                scope={
                    "tenant_id": "default",
                    "service": str(context.alert.service or "unknown"),
                    "environment": str(context.alert.environment or "prod"),
                    "region": None,
                    "team": str(context.alert.metadata.get("owner_team") or "") or None,
                },
                state={
                    "severity": str(
                        getattr(context.alert.severity, "value", context.alert.severity) or "warning"
                    ).lower(),
                    "status": status,
                    "owner": None,
                },
                policy={
                    "risk_tier": str(decision_payload.get("risk_tier") or orchestration.get("risk_tier") or "unknown"),
                    "execution_mode": str(
                        decision_payload.get("execution_mode") or orchestration.get("execution_mode") or "unknown"
                    ),
                    "requires_approval": requires_approval,
                    "policy_version": decision_payload.get("policy_version")
                    or orchestration.get("policy_version")
                    or metadata.get("policy_version"),
                    "policy_reason": decision_payload.get("policy_reason")
                    or orchestration.get("policy_reason")
                    or metadata.get("policy_reason"),
                },
                transport={
                    "provider": str(provider),
                    "channel": RESOLUTION_EVENTS,
                    "partition": None,
                    "offset": None,
                    "delivery_tag": None,
                },
                ai={
                    "confidence": float(recommendation.confidence),
                    "model_provider": str(
                        (metadata.get("model_usage") or [{}])[0].get("provider")
                        if isinstance(metadata.get("model_usage"), list) and metadata.get("model_usage")
                        else ""
                    )
                    or None,
                    "model_name": str(
                        (metadata.get("model_usage") or [{}])[0].get("model")
                        if isinstance(metadata.get("model_usage"), list) and metadata.get("model_usage")
                        else ""
                    )
                    or None,
                    "fallback_reason": None,
                },
                payload={
                    "recommendation_id": str(recommendation.id),
                    "recommended_action": recommendation.recommended_action,
                    "root_cause": recommendation.root_cause,
                    "impact": recommendation.impact,
                    "risk": recommendation.risk,
                },
            )
        )
        await session.commit()
    knowledge_id = str(context.metadata.get("context_knowledge_id") or "").strip()
    if not knowledge_id:
        CONTEXT_KNOWLEDGE_OPERATIONS.labels("attach_resolution", "not_linked").inc()
        return
    quality_score = _resolution_quality_score(recommendation.model_dump(mode="json"))
    if (
        not bool(getattr(settings, "context_resolution_reuse_enabled", True))
        or quality_score <= _resolution_reuse_threshold()
    ):
        CONTEXT_KNOWLEDGE_OPERATIONS.labels("attach_resolution", "below_threshold").inc()
        return
    try:
        async with app.state.session_factory() as session:
            repo = IncidentRepository(session)
            attached = await repo.attach_context_knowledge_resolution(
                knowledge_id,
                recommendation.model_dump(mode="json"),
            )
            await session.commit()
        CONTEXT_KNOWLEDGE_OPERATIONS.labels("attach_resolution", "success" if attached else "not_found").inc()
    except Exception:
        CONTEXT_KNOWLEDGE_OPERATIONS.labels("attach_resolution", "error").inc()


async def startup(app: FastAPI) -> None:
    workers = max(1, int(getattr(settings, "message_bus_worker_count", 1) or 1))
    consumers: list[tuple[str, Any, ConsumeRunner]] = []
    for worker in range(workers):
        consumers.append(
            (f"rabbitmq-w{worker + 1}", RabbitMQConsumer(settings, CONTEXT_EVENTS), consume_rabbitmq_forever)
        )
    if settings.kafka_enabled and MESSAGE_BUS_DUAL_CONSUME_ENABLED:
        for worker in range(workers):
            consumers.insert(
                worker,
                (f"kafka-w{worker + 1}", KafkaConsumer(settings, CONTEXT_EVENTS), consume_kafka_forever),
            )

    async def handle(payload: dict) -> None:
        context = Context.model_validate(payload["context"])
        incident = Incident.model_validate(payload["incident"])
        decision_payload = payload.get("decision", {}) if isinstance(payload.get("decision"), dict) else {}
        recommendation = await _resolve_context(context)
        recommendation.trace_id = str(incident.trace_id or context.alert.trace_id or "") or None
        recommendation.metadata["rag_documents"] = context.metadata.get("rag_documents", 0)
        recommendation.metadata["rag_matches"] = context.metadata.get("rag_matches", [])
        recommendation.metadata["rag_top_similarity"] = context.metadata.get("rag_top_similarity", 0.0)
        recommendation.metadata["rag_service_tagged_match"] = context.metadata.get("rag_service_tagged_match", False)
        recommendation.metadata["discovery_report"] = context.metadata.get("discovery_report", {})
        recommendation.metadata["discovery_evidence"] = context.metadata.get("discovery_evidence", {})
        recommendation.metadata["runbook_found"] = bool(context.runbook)
        policy_version = str(decision_payload.get("policy_version") or "").strip()
        policy_reason = str(decision_payload.get("policy_reason") or "").strip()
        if policy_version:
            recommendation.metadata["policy_version"] = policy_version
        if policy_reason:
            recommendation.metadata["policy_reason"] = policy_reason
        if decision_payload:
            recommendation.metadata["orchestration_decision"] = {
                "workflow": decision_payload.get("workflow"),
                "requires_approval": decision_payload.get("requires_approval"),
                "message_bus_provider": decision_payload.get("message_bus_provider"),
                "stream_count": decision_payload.get("stream_count"),
                "stream_threshold": decision_payload.get("stream_threshold"),
            }
        if settings.database_enabled:
            async with app.state.session_factory() as session:
                repo = IncidentRepository(session)
                await repo.save_recommendation_as_audit(recommendation)
                await session.commit()
        await _persist_resolution_event(
            app=app,
            context=context,
            incident=incident,
            recommendation=recommendation,
            decision_payload=decision_payload,
        )
        payload_out = _build_resolution_event_payload(
            context=context,
            incident=incident,
            recommendation=recommendation,
            decision_payload=decision_payload,
        )
        await app.state.producer.publish(RESOLUTION_EVENTS, payload_out, key=str(context.incident_id))
        EVENTS_PROCESSED.labels(settings.service_name, CONTEXT_EVENTS, "ok").inc()

    for source, consumer, consume_forever in consumers:
        task = asyncio.create_task(consume_forever(consumer, handle), name=f"resolution-agent-{source}-consumer")
        tasks.append(task)


async def shutdown(_: FastAPI) -> None:
    for task in tasks:
        task.cancel()


app = create_app(title="KaiMS Resolution Intelligence Agent", settings=settings, startup=startup, shutdown=shutdown)


class ResolutionCatalogRequest(BaseModel):
    issue: str
    service: str = "unknown"
    recommended_action: str = ""


class ResolutionSelectionRequest(BaseModel):
    option_id: str
    issue: str
    service: str = "unknown"
    incident_id: str = ""


class ExecutionFailureRequest(BaseModel):
    incident_id: UUID
    action_id: UUID
    action_type: str
    target: str
    service: str = "unknown"
    environment: str = "prod"
    error: str
    execution_result: dict[str, Any] = Field(default_factory=dict)
    previous_recommendation: dict[str, Any] = Field(default_factory=dict)
    attempt: int = Field(default=1, ge=1)


@app.post("/reconsider-execution")
async def reconsider_execution(request: ExecutionFailureRequest) -> dict[str, Any]:
    """Produce a new recommendation after a failed executor attempt.

    The response always requires a fresh human approval; it never retries a
    mutating operation directly from failure feedback.
    """
    previous = request.previous_recommendation
    previous_metadata = previous.get("metadata", {}) if isinstance(previous.get("metadata"), dict) else {}
    failure = request.error.strip()
    platform = os.getenv("REMEDIATION_EXECUTION_PLATFORM", "kubernetes").strip().lower()
    safe_service = "".join(ch for ch in request.service if ch.isalnum() or ch in "_.-") or "unknown"
    if platform in {"docker", "docker-compose", "compose"}:
        project = os.getenv("REMEDIATION_COMPOSE_PROJECT", "kaiops_azure").strip()
        safe_project = "".join(ch for ch in project if ch.isalnum() or ch in "_.-") or "kaiops_azure"
        container = f"{safe_project}-{safe_service}-1"
        commands = [
            f"curl --fail --silent --show-error -X POST http://docker-socket-proxy:2375/containers/{container}/restart?t=30",
            f"curl --fail --silent --show-error --retry 15 --retry-connrefused --retry-delay 2 http://{safe_service}:8000/healthz",
        ]
        rationale = (
            f"The previous executor attempt failed ({failure}). Re-plan against the configured Docker Compose runtime."
        )
    else:
        namespace = str(previous_metadata.get("namespace") or "default")
        commands = [
            f"kubectl rollout undo deployment/{request.target} -n {namespace}",
            f"kubectl rollout status deployment/{request.target} -n {namespace} --timeout=180s",
        ]
        rationale = (
            f"The previous executor attempt failed ({failure}). Verify Jenkins tooling "
            "and cluster credentials before approving this revised Kubernetes plan."
        )
    recommendation_id = uuid4()
    recommendation = {
        "id": str(recommendation_id),
        "incident_id": str(request.incident_id),
        "root_cause": f"Execution of {request.action_type} failed: {failure}",
        "confidence": 0.8,
        "impact": "Incident remains unresolved until a corrected execution plan succeeds and recovery is validated.",
        "recommended_action": f"Reconsider and retry {request.action_type} with the corrected executor plan",
        "severity": str(previous.get("severity") or "warning"),
        "rationale": rationale,
        "commands": commands,
        "risk": "high",
        "metadata": {
            **previous_metadata,
            "execution_plan": {"commands": commands, "scripts": [], "queries": [f"http://{safe_service}:8000/healthz"]},
            "execution_reconsideration_attempt": request.attempt,
            "failed_action_id": str(request.action_id),
            "failure_feedback": failure,
            "auto_approved": False,
        },
    }
    return {
        "recommendation": recommendation,
        "incident": {
            "id": str(request.incident_id),
            "service": request.service,
            "environment": request.environment,
            "severity": recommendation["severity"],
        },
        "decision": {
            "flow_id": str(request.incident_id),
            "requires_approval": True,
            "execution_mode": "human_approval",
            "risk_tier": "high",
            "policy_reason": "A failed execution must be re-planned and approved before retry.",
        },
    }


@app.post("/resolution-catalog/relevant")
async def resolution_catalog(request: ResolutionCatalogRequest) -> dict[str, Any]:
    rows = relevant_resolutions(
        issue=request.issue, service=request.service, recommended_action=request.recommended_action
    )
    best_relevance = float(rows[0].get("relevance") or 0.0) if rows else 0.0
    fallback = {"used": False, "cache_hit": False, "reason": None, "repository": "context-agent-rag", "error": None}
    if best_relevance < 0.35:
        fallback["reason"] = "No governed local option cleared the 0.35 relevance threshold."
        query = " ".join(
            part for part in (request.issue, request.service, request.recommended_action, "remediation runbook") if part
        ).strip()
        try:
            cache_key = " ".join(query.lower().split())
            cached = _GLOBAL_KNOWLEDGE_CACHE.get(cache_key)
            if cached and monotonic() - cached[0] < _GLOBAL_KNOWLEDGE_CACHE_TTL_SECONDS:
                matches = cached[1]
                fallback["cache_hit"] = True
            else:
                async with httpx.AsyncClient(timeout=httpx.Timeout(12.0)) as client:
                    response = await client.get(
                        f"{settings.context_agent_url.rstrip('/')}/rag/search",
                        params={"query": query, "limit": 6, "kind": "runbook"},
                    )
                    response.raise_for_status()
                    payload_matches = response.json().get("matches", [])
                matches = payload_matches if isinstance(payload_matches, list) else []
                if len(_GLOBAL_KNOWLEDGE_CACHE) >= _GLOBAL_KNOWLEDGE_CACHE_MAX_ENTRIES:
                    oldest_key = min(_GLOBAL_KNOWLEDGE_CACHE, key=lambda key: _GLOBAL_KNOWLEDGE_CACHE[key][0])
                    _GLOBAL_KNOWLEDGE_CACHE.pop(oldest_key, None)
                _GLOBAL_KNOWLEDGE_CACHE[cache_key] = (monotonic(), matches)
            knowledge_rows = register_global_knowledge(matches if isinstance(matches, list) else [])
            if knowledge_rows:
                rows = [*rows, *knowledge_rows]
                fallback["used"] = True
        except Exception as exc:
            fallback["error"] = str(exc)[:240]
    return {
        "rows": rows[:12],
        "catalog_size": len(RESOLUTION_CATALOG),
        "local_best_relevance": best_relevance,
        "global_knowledge_fallback": fallback,
    }


@app.post("/resolution-catalog/select")
async def select_resolution(request: ResolutionSelectionRequest) -> dict[str, Any]:
    try:
        plan = prepare_resolution_plan(option_id=request.option_id, issue=request.issue, service=request.service)
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"incident_id": request.incident_id, "selected": plan}


@app.post("/resolve", response_model=Recommendation)
async def resolve(context: Context, publish_events: bool = True) -> Recommendation:
    recommendation = await _resolve_context(context)
    recommendation.trace_id = str(context.alert.trace_id or "") or None
    recommendation.metadata["rag_documents"] = context.metadata.get("rag_documents", 0)
    recommendation.metadata["rag_matches"] = context.metadata.get("rag_matches", [])
    recommendation.metadata["rag_top_similarity"] = context.metadata.get("rag_top_similarity", 0.0)
    recommendation.metadata["rag_service_tagged_match"] = context.metadata.get("rag_service_tagged_match", False)
    recommendation.metadata["discovery_report"] = context.metadata.get("discovery_report", {})
    recommendation.metadata["discovery_evidence"] = context.metadata.get("discovery_evidence", {})
    recommendation.metadata["runbook_found"] = bool(context.runbook)
    synthetic_incident = Incident(
        id=context.incident_id,
        service=context.alert.service,
        severity=context.alert.severity,
        title=f"{context.alert.service}: {context.alert.name}",
    )
    payload_out = _build_resolution_event_payload(
        context=context,
        incident=synthetic_incident,
        recommendation=recommendation,
        decision_payload={},
    )
    # Temporal invokes this endpoint with publish_events=false because it owns
    # durable orchestration and must not create a second bus delivery. The
    # recommendation is still a business result and must always be persisted;
    # previously it was returned to Temporal and then lost from the incident
    # projection, leaving the cockpit permanently stuck at "RCA pending".
    if settings.database_enabled:
        async with app.state.session_factory() as session:
            repo = IncidentRepository(session)
            await repo.save_recommendation_as_audit(recommendation)
            await session.commit()
    await _persist_resolution_event(
        app=app,
        context=context,
        incident=synthetic_incident,
        recommendation=recommendation,
        decision_payload={},
    )
    if publish_events:
        await app.state.producer.publish(RESOLUTION_EVENTS, payload_out)
    return recommendation
