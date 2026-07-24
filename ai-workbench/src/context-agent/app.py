from __future__ import annotations

import asyncio
import json
from pathlib import Path
import re
from typing import Any

from common.config import get_settings
from common.event_publishers import EventPublisher, RabbitMQPublisher, build_agent_event_contract, build_event_envelope
from common.kafka import KafkaConsumer, consume_forever as consume_kafka_forever
from ai_workbench_common.models import Context
from common.models import Alert, Incident
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
                    "deployment": context.deployment,
                    "related_incidents": len(context.related_incidents),
                    "dependency_services": len(context.dependency_services),
                    "document_available": bool(context.metadata.get("rag_service_tagged_match", False)),
                    "discovery_report": context.metadata.get("discovery_report", {}),
                    "discovery_evidence": context.metadata.get("discovery_evidence", {}),
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
            "discovery": {
                "protocol": discovery.get("protocol"),
                "summary": report.get("summary"),
                "hypotheses": report.get("hypotheses", []),
                "retrieval_stages": discovery.get("retrieval_stages", []),
                "evidence": evidence,
                "model_usage": discovery.get("model_usage", {}),
                "model_interaction": discovery.get("model_interaction", {}),
                "insufficient_evidence": report.get("insufficient_evidence", False),
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


def _metadata_value(metadata: dict[str, str], *keys: str, default: str = "") -> str:
    for key in keys:
        value = str(metadata.get(key) or "").strip()
        if value:
            return value
    return default


def _single_remediation_script(request: RagDocumentRequest) -> str:
    service = (request.services[0] if request.services else request.alert_type or "kaiops-service").strip()
    environment = _metadata_value(request.metadata, "environment", default="prod")
    api_gateway_url = _metadata_value(
        request.metadata,
        "api_gateway_url",
        "apiGatewayUrl",
        "gateway_url",
        default="http://api-gateway:8000",
    )
    prometheus_url = _metadata_value(
        request.metadata,
        "prometheus_url",
        "monitoring_url",
        "metrics_endpoint",
        default="http://prometheus:9090",
    )
    mysql_host = _metadata_value(request.metadata, "mysql_host", "database_host", default="mysql")
    mysql_database = _metadata_value(request.metadata, "mysql_database", "database_name", default="kaiops")
    mysql_user = _metadata_value(request.metadata, "mysql_user", "database_user", default="kaiops")
    return (
        "bash scripts/remediation/kaiops_alert_health_triage.sh "
        f"--service {service or 'kaiops-service'} "
        f"--environment {environment or 'prod'} "
        f"--api-gateway-url {api_gateway_url} "
        f"--prometheus-url {prometheus_url} "
        f"--mysql-host {mysql_host} "
        f"--mysql-database {mysql_database} "
        f"--mysql-user {mysql_user} "
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
        "contract_version": "kaiops.knowledge-pack.v1",
        "status": "ready" if not missing_required and not low_confidence[:1] else "needs_review",
        "document_count": len(docs),
        "detected_documents": detected_docs,
        "facts": facts,
        "validation": {
            "missing_required": missing_required,
            "missing_recommended": missing_recommended,
            "low_confidence": low_confidence,
            "overall_confidence": overall_confidence,
        },
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
    pack["status"] = "approved"
    rag_request = _knowledge_pack_to_rag_request(pack, request.approved_by)
    result = write_rag_document(rag_request)
    return {"status": "approved", "knowledge_pack": pack, "rag_document": result}


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
async def list_rag_documents() -> dict[str, Any]:
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
    count = connector.reload()
    rebuild_flow_catalog_from_rag(connector)
    return {"status": "reloaded", "document_count": count, "index": connector.index_info()}


@app.get("/rag/index")
async def get_rag_index() -> dict[str, Any]:
    connector = vector_connector()
    return connector.index_info()


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
