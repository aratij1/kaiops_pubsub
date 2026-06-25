from __future__ import annotations

import json
import re
from typing import Any

from common.config import get_settings
from common.models import Alert, Context, Incident
from common.service import create_app
from common.topics import CONTEXT_EVENTS
from context_agent import ContextIntelligenceAgent
from context_agent.connectors import VectorDBConnector
from pydantic import BaseModel, Field

settings = get_settings()
settings.service_name = "context-agent"
agent = ContextIntelligenceAgent()


async def startup(_: Any) -> None:
    vector_connector().reload()


app = create_app(title="KaiOps Context Intelligence Agent", settings=settings, startup=startup)


class RagDocumentRequest(BaseModel):
    kind: str = Field(pattern="^(runbook|incident|deployment|change|dependency)$")
    title: str = Field(min_length=3, max_length=160)
    content: str = Field(min_length=20)
    services: list[str] = Field(default_factory=list)
    deployment: str | None = None
    dependencies: list[str] = Field(default_factory=list)
    change_id: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


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
    if request.services:
        metadata["services"] = ", ".join(request.services)
    if request.deployment:
        metadata["deployment"] = request.deployment
    if request.dependencies:
        metadata["dependencies"] = ", ".join(request.dependencies)
    if request.change_id:
        metadata["change_id"] = request.change_id
    metadata.update(request.metadata)
    header = "\n".join(f"{key}: {value}" for key, value in metadata.items())
    return f"{header}\n\n# {request.title}\n\n{request.content.strip()}\n"


def write_rag_document(request: RagDocumentRequest) -> dict[str, Any]:
    connector = vector_connector()
    root = connector.root_path()
    target_dir = root / kind_directory(request.kind)
    target_dir.mkdir(parents=True, exist_ok=True)
    base_name = slugify(request.title)
    target = target_dir / f"{base_name}.md"
    counter = 2
    while target.exists():
        target = target_dir / f"{base_name}-{counter}.md"
        counter += 1
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
        alert_id = str(doc.get("alert_id") or doc.get("id") or "").strip()
        alert_name = str(doc.get("alert_name") or doc.get("title") or "Incident").strip() or "Incident"
        flow_id = slugify(alert_id or alert_name)
        services = _normalize_list(doc.get("services", []))
        service = services[0] if services else str(doc.get("service", "unknown")).strip() or "unknown"
        severity = str(doc.get("severity", "HIGH")).upper().strip()
        if severity not in {"CRITICAL", "HIGH", "WARNING"}:
            severity = "HIGH"
        recommended_action = str(doc.get("recommended_action") or doc.get("remediation_comment") or "Investigate issue")
        content = str(doc.get("content", "")).strip()
        description = _first_content_line(content, alert_name)[:220]
        alert_type = str(doc.get("alert_type", "")).strip()
        entry = {
            "id": flow_id,
            "alert_id": alert_id or flow_id.upper(),
            "alert_name": alert_name,
            "alert_type": alert_type,
            "title": alert_name,
            "service": service,
            "severity": severity,
            "recommended_action": recommended_action,
            "description": description,
            "deployment": str(doc.get("deployment", "")).strip() or None,
            "change_id": str(doc.get("change_id", "")).strip() or None,
            "source": "rag-incident",
        }
        entries.append({k: v for k, v in entry.items() if v not in (None, "")})

    by_id = {str(item.get("id")): item for item in entries if item.get("id")}
    merged = list(by_id.values())
    merged.sort(key=lambda item: str(item.get("title", "")).lower())
    catalog_path.write_text(json.dumps(merged, indent=2), encoding="utf-8")


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
    await app.state.producer.publish(CONTEXT_EVENTS, {"context": context, "incident": incident}, key=alert.service)
    return context


@app.post("/rag/documents")
async def ingest_rag_document(request: RagDocumentRequest) -> dict[str, Any]:
    result = write_rag_document(request)
    if request.kind == "incident":
        rebuild_flow_catalog_from_rag(vector_connector())
    return {"status": "ingested", **result}


@app.get("/rag/documents")
async def list_rag_documents() -> dict[str, Any]:
    connector = vector_connector()
    return {
        "document_count": len(connector.documents),
        "documents": [
            {
                "kind": doc.get("kind"),
                "title": doc.get("title"),
                "services": doc.get("services", []),
                "path": doc.get("path"),
            }
            for doc in connector.documents
        ],
    }


@app.post("/rag/reload")
async def reload_rag() -> dict[str, Any]:
    connector = vector_connector()
    count = connector.reload()
    rebuild_flow_catalog_from_rag(connector)
    return {"status": "reloaded", "document_count": count}


@app.get("/rag/search")
async def search_rag(query: str, limit: int = 8) -> dict[str, Any]:
    matches = vector_connector().search(query, limit=max(1, min(limit, 20)))
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
