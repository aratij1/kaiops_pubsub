from __future__ import annotations

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
app = create_app(title="KaiOps Context Intelligence Agent", settings=settings)


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
    count = vector_connector().reload()
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
