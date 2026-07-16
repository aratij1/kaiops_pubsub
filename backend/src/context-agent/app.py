from __future__ import annotations

import asyncio
import json
from pathlib import Path
import re
from typing import Any

from common.config import get_settings
from common.event_publishers import EventPublisher, RabbitMQPublisher, build_agent_event_contract, build_event_envelope
from common.kafka import KafkaConsumer, consume_forever as consume_kafka_forever
from common.models import Alert, Context, Incident
from common.rabbitmq import RabbitMQConsumer, consume_forever as consume_rabbitmq_forever
from common.repository import IncidentRepository
from common.service import create_app
from common.telemetry import EVENTS_PROCESSED
from common.topics import CONTEXT_EVENTS, ORCHESTRATION_EVENTS
from context_agent import ContextIntelligenceAgent
from context_agent.connectors import VectorDBConnector
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

settings = get_settings()
settings.service_name = "context-agent"
agent = ContextIntelligenceAgent()
tasks: list[asyncio.Task] = []


def _extract_message_bus_provider(payload: dict[str, Any]) -> str:
    decision = payload.get("decision")
    if isinstance(decision, dict):
        provider = str(decision.get("message_bus_provider", "rabbitmq")).strip().lower()
        if provider in {"kafka", "rabbitmq", "pubsub"}:
            return provider
    transport = str(payload.get("transport", "")).strip().lower()
    if transport in {"kafka", "rabbitmq", "pubsub"}:
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
                    "deployment": context.deployment,
                    "related_incidents": len(context.related_incidents),
                    "dependency_services": len(context.dependency_services),
                    "document_available": bool(context.metadata.get("rag_service_tagged_match", False)),
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
        },
        metadata={
            "workflow": decision_payload.get("workflow"),
            "requires_approval": decision_payload.get("requires_approval"),
            "message_bus_provider": decision_payload.get("message_bus_provider"),
        },
        confidence=0.8,
        reasoning="connector fusion across observability, cmdb, and rag context",
        citations=[f"rag://{alert.service}", "cmdb://dependencies"],
        evidence_ids=[f"alert:{alert.id}", f"incident:{incident.id}"],
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
    if settings.kafka_enabled:
        for worker in range(workers):
            consumers.insert(
                worker,
                (f"kafka-w{worker + 1}", KafkaConsumer(settings, ORCHESTRATION_EVENTS), consume_kafka_forever),
            )
    return consumers


async def startup(app: FastAPI) -> None:
    vector_connector().reload()

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
        context = await agent.collect_with_runtime(alert, incident)
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
    kind: str = Field(pattern="^(runbook|incident|deployment|change|dependency)$")
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
    recommended_action: str | None = None
    source_system: str | None = None
    source_ref: str | None = None
    resolved_by: str | None = None
    closed_at: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class RagDocumentUpdateRequest(RagDocumentRequest):
    path: str = Field(min_length=3)


def vector_connector() -> VectorDBConnector:
    for connector in agent.connectors:
        if isinstance(connector, VectorDBConnector):
            return connector
    raise RuntimeError("VectorDBConnector is not configured")


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
    }[kind]


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
    return {"path": str(target), "document_count": count}


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
    return {"path": str(target), "document_count": count}


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
async def collect(payload: dict) -> Context:
    alert = Alert.model_validate(payload["alert"])
    incident = Incident.model_validate(payload["incident"])
    context = await agent.collect(alert, incident)
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


@app.get("/rag/documents")
async def list_rag_documents() -> dict[str, Any]:
    connector = vector_connector()
    documents = [doc for doc in connector.documents if not doc.get("_synthetic")]
    return {
        "document_count": len(documents),
        "documents": [
            {
                "kind": doc.get("kind"),
                "title": doc.get("title"),
                "alert_id": doc.get("alert_id"),
                "alert_type": doc.get("alert_type"),
                "severity": doc.get("severity"),
                "services": doc.get("services", []),
                "path": doc.get("path"),
            }
            for doc in documents
        ],
    }


@app.post("/rag/reload")
async def reload_rag() -> dict[str, Any]:
    connector = vector_connector()
    count = connector.reload()
    rebuild_flow_catalog_from_rag(connector)
    return {"status": "reloaded", "document_count": count}


@app.get("/rag/search")
async def search_rag(query: str, limit: int = 8, kind: str | None = None) -> dict[str, Any]:
    matches = vector_connector().search(
        query,
        limit=max(1, min(limit, 20)),
        preferred_kind=kind,
    )
    return {
        "query": query,
        "matches": [
            {
                "kind": match.get("kind"),
                "title": match.get("title"),
                "services": match.get("services", []),
                "deployment": match.get("deployment"),
                "path": match.get("path"),
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
