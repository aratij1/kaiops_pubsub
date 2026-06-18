from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from common.embeddings import HashingEmbeddingModel, cosine_similarity
from common.models import Alert, Context, Incident
from common.resilience import retry_async


class BaseConnector:
    name = "base"

    async def fetch(self, alert: Alert, incident: Incident) -> dict[str, Any]:
        raise NotImplementedError


class ServiceNowConnector(BaseConnector):
    name = "servicenow"

    async def fetch(self, alert: Alert, incident: Incident) -> dict[str, Any]:
        await asyncio.sleep(0)
        return {"ticket": incident.ticket_id, "change_records": [{"id": "CHG-1024", "service": alert.service}]}


class PrometheusConnector(BaseConnector):
    name = "prometheus"

    async def fetch(self, alert: Alert, incident: Incident) -> dict[str, Any]:
        await asyncio.sleep(0)
        return {"latency_p95_ms": 1250, "cpu_percent": 71, "error_rate": 0.08, "alerts_cleared": False}


class KubernetesConnector(BaseConnector):
    name = "kubernetes"

    async def fetch(self, alert: Alert, incident: Incident) -> dict[str, Any]:
        await asyncio.sleep(0)
        return {"namespace": alert.environment, "deployment": alert.labels.get("deployment", alert.service)}


class JenkinsConnector(BaseConnector):
    name = "jenkins"

    async def fetch(self, alert: Alert, incident: Incident) -> dict[str, Any]:
        await asyncio.sleep(0)
        return {"recent_deployments": [{"version": "Deployment 2.5", "status": "success"}]}


class GitHubConnector(BaseConnector):
    name = "github"

    async def fetch(self, alert: Alert, incident: Incident) -> dict[str, Any]:
        await asyncio.sleep(0)
        return {"recent_commits": [{"sha": "abc1234", "message": "Tune payment timeout"}]}


class CMDBConnector(BaseConnector):
    name = "cmdb"

    async def fetch(self, alert: Alert, incident: Incident) -> dict[str, Any]:
        await asyncio.sleep(0)
        return {
            "owner_team": alert.metadata.get("owner_team", "platform-ops"),
            "tier": "tier-1" if alert.service in {"payments", "checkout"} else "tier-2",
            "dependencies": ["checkout", "ledger", "fraud"] if alert.service == "payments" else [],
        }


@dataclass
class VectorDBConnector(BaseConnector):
    name: str = "vector-db"
    embedding_model: HashingEmbeddingModel = field(default_factory=HashingEmbeddingModel)
    rag_root: Path | None = None
    documents: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.documents:
            self.documents = self.load_documents()

    async def fetch(self, alert: Alert, incident: Incident) -> dict[str, Any]:
        await asyncio.sleep(0)
        query_vector = self.embedding_model.embed(f"{alert.service} {alert.name} {alert.description}")
        ranked = sorted(
            self.documents,
            key=lambda doc: cosine_similarity(query_vector, self.embedding_model.embed(self._document_text(doc))),
            reverse=True,
        )
        return {"matches": ranked[:8], "document_count": len(self.documents)}

    def load_documents(self) -> list[dict[str, Any]]:
        root = self.rag_root or self._discover_rag_root()
        if root is None or not root.exists():
            return []
        return [self._parse_document(path) for path in sorted(root.rglob("*.md"))]

    def _discover_rag_root(self) -> Path | None:
        candidates = [Path.cwd(), *Path.cwd().parents, Path("/app")]
        for candidate in candidates:
            rag_root = candidate / "rag"
            if rag_root.exists():
                return rag_root
        return None

    def _parse_document(self, path: Path) -> dict[str, Any]:
        raw = path.read_text(encoding="utf-8")
        metadata: dict[str, Any] = {"path": str(path), "kind": path.parent.name.rstrip("s")}
        body_lines: list[str] = []
        in_metadata = True
        for line in raw.splitlines():
            if in_metadata and not line.strip():
                in_metadata = False
                continue
            if in_metadata and ":" in line:
                key, value = line.split(":", 1)
                metadata[key.strip()] = self._parse_metadata_value(value.strip())
            else:
                in_metadata = False
                body_lines.append(line)

        title = str(metadata.get("title") or path.stem.replace("-", " "))
        content = "\n".join(body_lines).strip()
        return {**metadata, "title": title, "content": content}

    def _parse_metadata_value(self, value: str) -> Any:
        if "," in value:
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    def _document_text(self, doc: dict[str, Any]) -> str:
        services = doc.get("services", [])
        dependencies = doc.get("dependencies", [])
        if isinstance(services, list):
            services = " ".join(services)
        if isinstance(dependencies, list):
            dependencies = " ".join(dependencies)
        return " ".join(
            [
                str(doc.get("kind", "")),
                str(doc.get("title", "")),
                str(services),
                str(dependencies),
                str(doc.get("deployment", "")),
                str(doc.get("content", "")),
            ]
        )


@dataclass
class ContextIntelligenceAgent:
    connectors: list[BaseConnector] = field(
        default_factory=lambda: [
            ServiceNowConnector(),
            PrometheusConnector(),
            KubernetesConnector(),
            JenkinsConnector(),
            GitHubConnector(),
            CMDBConnector(),
            VectorDBConnector(),
        ]
    )

    async def collect(self, alert: Alert, incident: Incident) -> Context:
        results = await asyncio.gather(
            *[
                retry_async(lambda connector=connector: connector.fetch(alert, incident))
                for connector in self.connectors
            ]
        )
        by_name = {connector.name: result for connector, result in zip(self.connectors, results, strict=True)}
        vector_matches = by_name["vector-db"]["matches"]
        runbook = next((doc["content"] for doc in vector_matches if doc["kind"] == "runbook"), "")
        related = [doc for doc in vector_matches if doc["kind"] == "incident"]
        deployment_doc = next((doc for doc in vector_matches if doc["kind"] == "deployment"), {})
        dependency_docs = [doc for doc in vector_matches if doc["kind"] == "dependency"]
        change_docs = [doc for doc in vector_matches if doc["kind"] == "change"]
        deployment = (
            by_name["jenkins"].get("recent_deployments", [{}])[0].get("version")
            or alert.labels.get("deployment")
            or deployment_doc.get("deployment")
        )
        dependencies = list(by_name["cmdb"].get("dependencies", []))
        for doc in dependency_docs:
            for dependency in doc.get("dependencies", []):
                if dependency not in dependencies:
                    dependencies.append(dependency)
        recent_changes = (
            by_name["servicenow"].get("change_records", [])
            + by_name["github"].get("recent_commits", [])
            + [
                {
                    "id": doc.get("change_id", doc.get("title")),
                    "source": "rag",
                    "title": doc.get("title"),
                    "deployment": doc.get("deployment"),
                }
                for doc in change_docs
            ]
        )
        return Context(
            incident_id=incident.id,
            alert=alert,
            deployment=deployment,
            related_incidents=related,
            runbook=runbook,
            dependency_services=dependencies,
            recent_changes=recent_changes,
            cmdb=by_name["cmdb"],
            kubernetes=by_name["kubernetes"],
            observability=by_name["prometheus"],
            metadata={
                "rag_documents": by_name["vector-db"]["document_count"],
                "rag_matches": [
                    {"kind": doc.get("kind"), "title": doc.get("title"), "path": doc.get("path")}
                    for doc in vector_matches
                ],
            },
        )
