from __future__ import annotations

import asyncio
import heapq
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from common.agent_runtime import AgentRuntime, ContextFailure
from common.agentic import AgentContext, BaseAgent
from common.embeddings import HashingEmbeddingModel, cosine_similarity
from common.models import Alert, Context, Incident
from common.resilience import retry_async
from common.tool_registry import ToolRegistry, ToolSpec


class BaseConnector:
    name = "base"

    async def fetch(self, alert: Alert, incident: Incident) -> dict[str, Any]:
        raise NotImplementedError


class ServiceNowConnector(BaseConnector):
    name = "servicenow"

    async def fetch(self, alert: Alert, incident: Incident) -> dict[str, Any]:
        await asyncio.sleep(0)
        return {"ticket": incident.ticket_id, "change_records": []}


class PrometheusConnector(BaseConnector):
    name = "prometheus"

    async def fetch(self, alert: Alert, incident: Incident) -> dict[str, Any]:
        await asyncio.sleep(0)
        # The alert itself is evidence; do not manufacture point-in-time telemetry
        # when no Prometheus query has been executed by this connector.
        return {}


class KubernetesConnector(BaseConnector):
    name = "kubernetes"

    async def fetch(self, alert: Alert, incident: Incident) -> dict[str, Any]:
        await asyncio.sleep(0)
        return {"namespace": alert.environment, "deployment": alert.labels.get("deployment", alert.service)}


class JenkinsConnector(BaseConnector):
    name = "jenkins"

    async def fetch(self, alert: Alert, incident: Incident) -> dict[str, Any]:
        await asyncio.sleep(0)
        deployment = str(alert.labels.get("deployment") or alert.metadata.get("deployment") or "").strip()
        return {"recent_deployments": [{"version": deployment, "status": "observed"}]} if deployment else {"recent_deployments": []}


class GitHubConnector(BaseConnector):
    name = "github"

    async def fetch(self, alert: Alert, incident: Incident) -> dict[str, Any]:
        await asyncio.sleep(0)
        return {"recent_commits": []}


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
    _document_cache: dict[str, dict[str, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.documents:
            self.documents = self.load_documents()

    async def fetch(self, alert: Alert, incident: Incident) -> dict[str, Any]:
        await asyncio.sleep(0)
        query_vector = self.embedding_model.embed(f"{alert.service} {alert.name} {alert.description}")
        ranked = self._rank_documents(
            query_vector=query_vector,
            limit=8,
            preferred_kinds={"runbook", "incident", "deployment", "dependency", "change"},
            service=str(alert.service or "").strip(),
        )
        return {"matches": ranked, "document_count": len(self.documents)}

    def load_documents(self) -> list[dict[str, Any]]:
        root = self.rag_root or self._discover_rag_root()
        if root is None or not root.exists():
            return []
        self._document_cache.clear()
        documents = [self._parse_metadata_document(path) for path in sorted(root.rglob("*.md"))]
        derived_documents: list[dict[str, Any]] = []
        for doc in documents:
            if str(doc.get("kind", "")).strip().lower() != "incident":
                continue
            dependencies = doc.get("dependencies", [])
            if isinstance(dependencies, str):
                dependencies = [item.strip() for item in dependencies.split(",") if item.strip()]
            if isinstance(dependencies, list) and dependencies:
                filtered_dependencies = [str(item).strip() for item in dependencies if str(item).strip().lower() != "not explicitly documented."]
                if filtered_dependencies:
                    dependency_doc = {
                        **doc,
                        "kind": "dependency",
                        "title": f"{doc.get('title', 'Incident')} dependency context",
                        "content": "Dependency context derived from incident metadata.",
                        "dependencies": filtered_dependencies,
                        "_synthetic": True,
                    }
                    dependency_doc["_metadata_embedding"] = self.embedding_model.embed(self._metadata_text(dependency_doc))
                    dependency_doc["_embedding"] = self.embedding_model.embed(self._document_text(dependency_doc))
                    derived_documents.append(dependency_doc)

            deployment = str(doc.get("deployment") or "").strip()
            if deployment and deployment.lower() != "not explicitly documented.":
                deployment_doc = {
                    **doc,
                    "kind": "deployment",
                    "title": f"{doc.get('title', 'Incident')} deployment context",
                    "content": "Deployment context derived from incident metadata.",
                    "deployment": deployment,
                    "_synthetic": True,
                }
                deployment_doc["_metadata_embedding"] = self.embedding_model.embed(self._metadata_text(deployment_doc))
                deployment_doc["_embedding"] = self.embedding_model.embed(self._document_text(deployment_doc))
                derived_documents.append(deployment_doc)

            change_id = str(doc.get("change_id") or "").strip()
            if change_id:
                change_doc = {
                    **doc,
                    "kind": "change",
                    "title": f"{doc.get('title', 'Incident')} change context",
                    "content": "Change context derived from incident metadata.",
                    "change_id": change_id,
                    "_synthetic": True,
                }
                change_doc["_metadata_embedding"] = self.embedding_model.embed(self._metadata_text(change_doc))
                change_doc["_embedding"] = self.embedding_model.embed(self._document_text(change_doc))
                derived_documents.append(change_doc)

        return documents + derived_documents

    def reload(self) -> int:
        self.documents = self.load_documents()
        return len(self.documents)

    def search(
        self,
        query: str,
        limit: int = 8,
        *,
        preferred_kind: str | None = None,
        service: str | None = None,
    ) -> list[dict[str, Any]]:
        query_vector = self.embedding_model.embed(query)
        preferred_kinds = {preferred_kind.strip().lower()} if preferred_kind and preferred_kind.strip() else None
        return self._rank_documents(
            query_vector=query_vector,
            limit=limit,
            preferred_kinds=preferred_kinds,
            service=service,
        )

    def root_path(self) -> Path:
        root = self.rag_root or self._discover_rag_root()
        if root is None:
            root = Path.cwd() / "rag"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _discover_rag_root(self) -> Path | None:
        candidates = [Path.cwd(), *Path.cwd().parents, Path("/app")]
        for candidate in candidates:
            rag_root = candidate / "rag"
            if rag_root.exists():
                return rag_root
        return None

    def _parse_metadata_document(self, path: Path) -> dict[str, Any]:
        metadata = self._read_metadata(path)
        metadata["_metadata_embedding"] = self.embedding_model.embed(self._metadata_text(metadata))
        return metadata

    def _load_full_document(self, path: str) -> dict[str, Any]:
        cached = self._document_cache.get(path)
        if cached is not None:
            return dict(cached)

        if not path:
            return {}

        file_path = Path(path)
        if not file_path.exists():
            return {}
        raw = file_path.read_text(encoding="utf-8")
        metadata: dict[str, Any] = {"path": path, "kind": file_path.parent.name.rstrip("s")}
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

        title = str(metadata.get("title") or file_path.stem.replace("-", " "))
        content = "\n".join(body_lines).strip()
        services = metadata.get("services", [])
        if isinstance(services, str):
            services = [item.strip() for item in services.split(",") if item.strip()]
        elif not isinstance(services, list):
            services = []
        document = {**metadata, "title": title, "content": content, "services": services}
        document["_embedding"] = self.embedding_model.embed(self._document_text(document))
        self._document_cache[path] = document
        return dict(document)

    def _read_metadata(self, path: Path) -> dict[str, Any]:
        metadata: dict[str, Any] = {"path": str(path), "kind": path.parent.name.rstrip("s")}
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    stripped = line.strip()
                    if not stripped:
                        break
                    if ":" in line:
                        key, value = line.split(":", 1)
                        metadata[key.strip()] = self._parse_metadata_value(value.strip())
        except OSError:
            return metadata

        title = str(metadata.get("title") or path.stem.replace("-", " "))
        services = metadata.get("services", [])
        if isinstance(services, str):
            services = [item.strip() for item in services.split(",") if item.strip()]
        elif not isinstance(services, list):
            services = []
        metadata["title"] = title
        metadata["services"] = services
        return metadata

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

    def _metadata_text(self, doc: dict[str, Any]) -> str:
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
                str(doc.get("change_id", "")),
            ]
        )

    def _service_matches(self, doc: dict[str, Any], service: str | None) -> bool:
        normalized_service = str(service or "").strip().lower()
        if not normalized_service:
            return True
        doc_services = doc.get("services", [])
        if isinstance(doc_services, str):
            doc_services = [doc_services]
        if not isinstance(doc_services, list) or not doc_services:
            return True
        normalized_doc_services = {str(item).strip().lower() for item in doc_services if str(item).strip()}
        return normalized_service in normalized_doc_services or any(
            normalized_service in item or item in normalized_service for item in normalized_doc_services
        )

    def _kind_matches(self, doc: dict[str, Any], preferred_kinds: set[str] | None) -> bool:
        if not preferred_kinds:
            return True
        return str(doc.get("kind", "")).strip().lower() in preferred_kinds

    def _metadata_rank_score(self, query_vector: list[float], doc: dict[str, Any]) -> float:
        embedding = doc.get("_metadata_embedding")
        if not isinstance(embedding, list):
            embedding = self.embedding_model.embed(self._metadata_text(doc))
            doc["_metadata_embedding"] = embedding
        return cosine_similarity(query_vector, embedding)

    def _rank_documents(
        self,
        *,
        query_vector: list[float],
        limit: int,
        preferred_kinds: set[str] | None = None,
        service: str | None = None,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 20))
        candidates = [
            doc
            for doc in self.documents
            if self._kind_matches(doc, preferred_kinds) and self._service_matches(doc, service)
        ]
        if not candidates and preferred_kinds and not str(service or "").strip():
            candidates = [doc for doc in self.documents if self._service_matches(doc, service)]
        if not candidates and not str(service or "").strip():
            candidates = list(self.documents)

        shortlist_size = min(max(limit * 4, 12), len(candidates))
        shortlisted = heapq.nlargest(
            shortlist_size,
            candidates,
            key=lambda doc: self._metadata_rank_score(query_vector, doc),
        )
        hydrated = [dict(doc) if doc.get("_synthetic") else self._load_full_document(str(doc.get("path", ""))) for doc in shortlisted]
        return heapq.nlargest(
            limit,
            hydrated,
            key=lambda doc: cosine_similarity(query_vector, doc.get("_embedding") or self.embedding_model.embed(self._document_text(doc))),
        )


@dataclass
class ContextIntelligenceAgent(BaseAgent):
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
    name: str = "context-agent"
    runtime: AgentRuntime = field(default_factory=AgentRuntime)
    tool_registry: ToolRegistry = field(default_factory=ToolRegistry)

    def __post_init__(self) -> None:
        if self.tool_registry.tools:
            return

        for connector in self.connectors:
            tool_name = f"connector.{connector.name}"

            async def _handler(payload: dict[str, Any], _connector: BaseConnector = connector) -> dict[str, Any]:
                alert_payload = payload.get("alert")
                incident_payload = payload.get("incident")
                if not isinstance(alert_payload, dict) or not isinstance(incident_payload, dict):
                    raise ValueError("connector payload must include alert and incident objects")
                alert = Alert.model_validate(alert_payload)
                incident = Incident.model_validate(incident_payload)
                return await _connector.fetch(alert, incident)

            self.tool_registry.register(
                ToolSpec(
                    name=tool_name,
                    handler=_handler,
                    timeout_seconds=10.0,
                    permissions={"context-agent"},
                )
            )

    async def _run_connector(self, connector: BaseConnector, alert: Alert, incident: Incident) -> dict[str, Any]:
        return await self.tool_registry.execute(
            f"connector.{connector.name}",
            {
                "alert": alert.model_dump(mode="json"),
                "incident": incident.model_dump(mode="json"),
            },
            role="context-agent",
        )

    async def can_execute(self, context: AgentContext) -> bool:
        return context.alert is not None and context.incident is not None

    async def collect(self, alert: Alert, incident: Incident) -> Context:
        results = await asyncio.gather(
            *[
                retry_async(lambda connector=connector: self._run_connector(connector, alert, incident))
                for connector in self.connectors
            ]
        )
        by_name = {connector.name: result for connector, result in zip(self.connectors, results, strict=True)}
        vector_matches = by_name["vector-db"]["matches"]

        def service_evidence(doc: dict[str, Any]) -> bool:
            services = doc.get("services", [])
            if isinstance(services, str):
                services = [services]
            normalized = {str(item).strip().lower() for item in services if str(item).strip()}
            target = str(alert.service or "").strip().lower()
            return bool(target and normalized and (target in normalized or any(target in item or item in target for item in normalized)))

        runbook = next((doc["content"] for doc in vector_matches if doc["kind"] == "runbook" and service_evidence(doc)), "")
        related = [doc for doc in vector_matches if doc["kind"] == "incident" and service_evidence(doc)]
        deployment_doc = next((doc for doc in vector_matches if doc["kind"] == "deployment" and service_evidence(doc)), {})
        dependency_docs = [doc for doc in vector_matches if doc["kind"] == "dependency" and service_evidence(doc)]
        change_docs = [doc for doc in vector_matches if doc["kind"] == "change" and service_evidence(doc)]
        deployment = (
            next((item.get("version") for item in by_name["jenkins"].get("recent_deployments", []) if item.get("version")), None)
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

    async def execute(self, context: AgentContext) -> Context:
        if context.alert is None or context.incident is None:
            raise ContextFailure("AgentContext must include alert and incident")
        result = await self.collect(context.alert, context.incident)
        context.set_result(self.name, result.model_dump(mode="json"))
        return result

    async def validate(self, result: Any) -> bool:
        return isinstance(result, Context)

    async def collect_with_runtime(self, alert: Alert, incident: Incident) -> Context:
        runtime_context = AgentContext(alert=alert, incident=incident)
        runtime_result = await self.runtime.run(self, runtime_context)
        if not isinstance(runtime_result.result, Context):
            raise ContextFailure("context runtime produced non-context output")
        return runtime_result.result
