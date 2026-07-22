from __future__ import annotations

import asyncio
import heapq
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypedDict

import httpx
from langchain_core.embeddings import Embeddings
from langgraph.graph import END, StateGraph

from ai_workbench_common.agent_runtime import AgentRuntime, ContextFailure
from ai_workbench_common.agentic import AgentContext, BaseAgent
from common.config import get_settings
from ai_workbench_common.embeddings import describe_embedding_model, get_embedding_model, cosine_similarity
from ai_workbench_common.models import Context
from common.models import Alert, Incident
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


class AzureAISearchVectorStore:
    """REST-backed Azure AI Search adapter for production RAG retrieval."""

    def __init__(self, *, settings: Any, embedding_model: Embeddings) -> None:
        self._endpoint = str(getattr(settings, "azure_ai_search_endpoint", "") or "").strip().rstrip("/")
        self._api_key = str(getattr(settings, "azure_ai_search_api_key", "") or "").strip()
        self._index_name = str(getattr(settings, "azure_ai_search_index_name", "kaiops-rag") or "kaiops-rag").strip()
        self._api_version = str(getattr(settings, "azure_ai_search_api_version", "2024-07-01") or "2024-07-01")
        self._content_field = str(getattr(settings, "azure_ai_search_content_field", "content") or "content")
        self._vector_field = str(getattr(settings, "azure_ai_search_vector_field", "content_vector") or "content_vector")
        self._timeout_seconds = float(getattr(settings, "azure_ai_search_timeout_seconds", 8.0) or 8.0)
        self._embedding_model = embedding_model
        self.enabled = bool(getattr(settings, "azure_ai_search_enabled", False))
        self.last_error: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.enabled and self._endpoint and self._api_key and self._index_name)

    def info(self) -> dict[str, Any]:
        return {
            "provider": "azure-ai-search" if self.configured else "file-backed-memory",
            "engine": "AzureAISearchVectorStore" if self.configured else "VectorDBConnector",
            "persistent_index": bool(self.configured),
            "storage": "azure-ai-search-index" if self.configured else "markdown-files",
            "endpoint": self._endpoint if self.configured else "",
            "index_name": self._index_name if self.configured else "",
            "content_field": self._content_field if self.configured else "",
            "vector_field": self._vector_field if self.configured else "",
            "last_error": self.last_error,
            "enterprise_ready": bool(self.configured),
        }

    def _headers(self) -> dict[str, str]:
        return {"api-key": self._api_key, "Content-Type": "application/json"}

    def _url(self, path: str) -> str:
        return f"{self._endpoint}/indexes/{self._index_name}{path}?api-version={self._api_version}"

    def _odata_literal(self, value: str) -> str:
        return "'" + str(value).replace("'", "''") + "'"

    def _filter(self, *, preferred_kinds: set[str] | None, service: str | None) -> str | None:
        filters: list[str] = []
        kinds = sorted({str(item).strip().lower() for item in (preferred_kinds or set()) if str(item).strip()})
        if kinds:
            filters.append("(" + " or ".join(f"kind eq {self._odata_literal(kind)}" for kind in kinds) + ")")
        normalized_service = str(service or "").strip().lower()
        if normalized_service:
            filters.append(f"services/any(service: search.in(service, {self._odata_literal(normalized_service)}, ','))")
        return " and ".join(filters) if filters else None

    def _chunk_text(self, text: str, *, max_chars: int = 1800, overlap_chars: int = 240) -> list[str]:
        normalized = re.sub(r"\n{3,}", "\n\n", str(text or "").strip())
        if not normalized:
            return []
        chunks: list[str] = []
        start = 0
        while start < len(normalized):
            end = min(len(normalized), start + max_chars)
            if end < len(normalized):
                paragraph_break = normalized.rfind("\n\n", start, end)
                if paragraph_break > start + 400:
                    end = paragraph_break
            chunk = normalized[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(normalized):
                break
            start = max(0, end - overlap_chars)
        return chunks

    def search(
        self,
        *,
        query: str,
        query_vector: list[float],
        limit: int,
        preferred_kinds: set[str] | None = None,
        service: str | None = None,
    ) -> list[dict[str, Any]]:
        if not self.configured:
            return []
        payload: dict[str, Any] = {
            "search": query or "*",
            "top": max(1, min(limit, 50)),
            "select": (
                "id,document_id,chunk_id,kind,title,content,services,deployment,dependencies,change_id,"
                "alert_id,incident_id,source_system,source_ref,owner,version,freshness_score,embedding_model,path"
            ),
            "vectorQueries": [
                {
                    "kind": "vector",
                    "vector": query_vector,
                    "fields": self._vector_field,
                    "k": max(1, min(limit * 3, 50)),
                }
            ],
        }
        filter_expression = self._filter(preferred_kinds=preferred_kinds, service=service)
        if filter_expression:
            payload["filter"] = filter_expression
        try:
            with httpx.Client(timeout=self._timeout_seconds) as client:
                response = client.post(self._url("/docs/search"), headers=self._headers(), json=payload)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            self.last_error = str(exc)
            return []
        rows = data.get("value") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            return []
        results: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            doc = dict(row)
            score = float(doc.pop("@search.score", 0.0) or 0.0)
            doc["_similarity"] = score
            doc["_semantic_score"] = score
            doc["_metadata_match_score"] = 0.0
            doc["match_confidence"] = score
            doc["_vector_store"] = "azure-ai-search"
            services = doc.get("services", [])
            if isinstance(services, str):
                doc["services"] = [item.strip() for item in services.split(",") if item.strip()]
            results.append(doc)
        return results

    def upsert_documents(self, documents: list[dict[str, Any]]) -> dict[str, Any]:
        if not self.configured:
            return {"attempted": False, "indexed": 0, "reason": "azure ai search is not configured"}
        rows = []
        for doc in documents:
            content = str(doc.get("content") or "").strip()
            if not content:
                continue
            doc_id = re.sub(r"[^a-zA-Z0-9_-]", "-", str(doc.get("path") or doc.get("title") or "document"))[:512]
            chunks = self._chunk_text(content)
            services = doc.get("services", [])
            if isinstance(services, str):
                services = [item.strip() for item in services.split(",") if item.strip()]
            elif not isinstance(services, list):
                services = []
            for index, chunk in enumerate(chunks or [content]):
                chunk_id = f"chunk-{index + 1}"
                rows.append(
                    {
                        "@search.action": "mergeOrUpload",
                        "id": f"{doc_id}-{chunk_id}"[:512],
                        "document_id": str(doc.get("path") or doc_id),
                        "chunk_id": chunk_id,
                        "kind": str(doc.get("kind") or "document").strip().lower(),
                        "title": str(doc.get("title") or doc_id),
                        self._content_field: chunk,
                        self._vector_field: self._embedding_model.embed(chunk),
                        "services": [str(item).strip().lower() for item in services if str(item).strip()],
                        "deployment": str(doc.get("deployment") or ""),
                        "dependencies": doc.get("dependencies", []) if isinstance(doc.get("dependencies"), list) else [],
                        "change_id": str(doc.get("change_id") or ""),
                        "alert_id": str(doc.get("alert_id") or ""),
                        "incident_id": str(doc.get("incident_id") or ""),
                        "source_system": str(doc.get("source_system") or ""),
                        "source_ref": str(doc.get("source_ref") or ""),
                        "owner": str(doc.get("owner") or doc.get("resolved_by") or "unassigned"),
                        "version": str(doc.get("version") or "v1"),
                        "freshness_score": float(doc.get("freshness_score") or 0.75),
                        "embedding_model": str(describe_embedding_model(self._embedding_model).get("model") or ""),
                        "path": str(doc.get("path") or ""),
                    }
                )
        if not rows:
            return {"attempted": True, "indexed": 0, "reason": "no documents with content"}
        try:
            with httpx.Client(timeout=self._timeout_seconds) as client:
                response = client.post(self._url("/docs/index"), headers=self._headers(), json={"value": rows})
            response.raise_for_status()
        except Exception as exc:
            self.last_error = str(exc)
            return {"attempted": True, "indexed": 0, "error": str(exc)}
        self.last_error = ""
        return {"attempted": True, "indexed": len(rows), "index_name": self._index_name}


@dataclass
class VectorDBConnector(BaseConnector):
    name: str = "vector-db"
    embedding_model: Embeddings = field(default_factory=lambda: get_embedding_model(get_settings()))
    rag_root: Path | None = None
    documents: list[dict[str, Any]] = field(default_factory=list)
    _document_cache: dict[str, dict[str, Any]] = field(default_factory=dict)
    _remote_store: AzureAISearchVectorStore | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if not self.documents:
            self.documents = self.load_documents()

    async def fetch(self, alert: Alert, incident: Incident) -> dict[str, Any]:
        await asyncio.sleep(0)
        query = " ".join(
            [
                str(alert.service or ""),
                str(alert.name or ""),
                str(alert.description or ""),
                " ".join(f"{key}={value}" for key, value in alert.labels.items()),
                " ".join(f"{key}={value}" for key, value in alert.annotations.items()),
            ]
        )
        ranked = self.search(
            query,
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
        documents = [
            self._parse_metadata_document(path)
            for path in sorted(root.rglob("*.md"))
            if path.name != "flows.md"
        ]
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
        self.sync_remote_index()
        return len(self.documents)

    def embedding_info(self) -> dict[str, Any]:
        return describe_embedding_model(self.embedding_model)

    def vector_store_info(self) -> dict[str, Any]:
        remote = self.remote_store()
        if remote.configured:
            return remote.info()
        return {
            "provider": "local-hybrid-vector-index",
            "engine": self.__class__.__name__,
            "persistent_index": False,
            "storage": "markdown-files-with-in-memory-vector-rerank",
            "root_path": str(self.root_path()),
            "remote_configured": False,
            "enterprise_ready": False,
            "recommended_enterprise_store": "azure-ai-search",
            "remote_last_error": remote.last_error,
        }

    def remote_store(self) -> AzureAISearchVectorStore:
        if self._remote_store is None:
            self._remote_store = AzureAISearchVectorStore(settings=get_settings(), embedding_model=self.embedding_model)
        return self._remote_store

    def sync_remote_index(self) -> dict[str, Any]:
        remote = self.remote_store()
        if not remote.configured:
            return {"attempted": False, "indexed": 0, "reason": "azure ai search is not configured"}
        full_docs = [
            dict(doc) if doc.get("_synthetic") else self._load_full_document(str(doc.get("path", "")))
            for doc in self.documents
            if not doc.get("_synthetic")
        ]
        return remote.upsert_documents([doc for doc in full_docs if doc])

    def index_info(self) -> dict[str, Any]:
        docs = [doc for doc in self.documents if not doc.get("_synthetic")]
        synthetic_docs = [doc for doc in self.documents if doc.get("_synthetic")]
        by_kind: dict[str, int] = {}
        embedded_metadata = 0
        for doc in docs:
            kind = str(doc.get("kind") or "unknown").strip().lower() or "unknown"
            by_kind[kind] = by_kind.get(kind, 0) + 1
            if isinstance(doc.get("_metadata_embedding"), list):
                embedded_metadata += 1
        return {
            "contract_version": "kaiops.rag-index.v1",
            "status": "ready" if docs else "empty",
            "vector_store": self.vector_store_info(),
            "embedding_model": self.embedding_info(),
            "remote_index_enabled": self.remote_store().configured,
            "enterprise_index_enabled": self.remote_store().configured,
            "document_count": len(docs),
            "synthetic_document_count": len(synthetic_docs),
            "metadata_embedding_count": embedded_metadata,
            "full_document_cache_count": len(self._document_cache),
            "kinds": by_kind,
            "quality_gates": {
                "semantic_embeddings": self.embedding_info().get("provider") in {"openai", "azure-openai"},
                "persistent_vector_store": self.remote_store().configured,
                "service_scoped_retrieval": True,
                "metadata_prefilter": True,
                "full_document_rerank": True,
                "metadata_confidence_scoring": True,
            },
            "index_strategy": {
                "chunking": "chunk-level-for-remote-document-level-for-local",
                "metadata_shortlist": True,
                "full_document_rerank": True,
                "service_filter": True,
                "score_components": ["semantic_score", "metadata_match_score", "match_confidence"],
                "preferred_kinds": ["runbook", "incident", "deployment", "dependency", "change"],
            },
        }

    def search(
        self,
        query: str,
        limit: int = 8,
        *,
        preferred_kind: str | None = None,
        preferred_kinds: set[str] | None = None,
        service: str | None = None,
    ) -> list[dict[str, Any]]:
        query_vector = self.embedding_model.embed(query)
        kind_filter = (
            {preferred_kind.strip().lower()}
            if preferred_kind and preferred_kind.strip()
            else ({str(item).strip().lower() for item in preferred_kinds if str(item).strip()} if preferred_kinds else None)
        )
        remote_matches = self.remote_store().search(
            query=query,
            query_vector=query_vector,
            limit=limit,
            preferred_kinds=kind_filter,
            service=service,
        )
        if remote_matches:
            return remote_matches
        return self._rank_documents(
            query=query,
            query_vector=query_vector,
            limit=limit,
            preferred_kinds=kind_filter,
            service=service,
        )

    def root_path(self) -> Path:
        root = self.rag_root or self._discover_rag_root()
        if root is None:
            root = Path.cwd() / "backend" / "rag"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _discover_rag_root(self) -> Path | None:
        candidates = [Path.cwd(), *Path.cwd().parents, Path("/app")]
        for candidate in candidates:
            for rag_root in (candidate / "backend" / "rag", candidate / "rag"):
                if rag_root.exists():
                    return rag_root
        return None

    def _parse_metadata_document(self, path: Path) -> dict[str, Any]:
        metadata = self._read_metadata(path)
        metadata["_metadata_embedding"] = self.embedding_model.embed(self._metadata_text(metadata))
        return metadata

    def _resolve_document_path(self, path: str) -> Path | None:
        if not path:
            return None
        file_path = Path(path)
        if file_path.exists():
            return file_path

        root = self.root_path()
        raw = str(path).replace("\\", "/")
        for marker in ("/rag/", "rag/"):
            if marker not in raw:
                continue
            relative = raw.split(marker, 1)[1]
            candidate = root / relative
            if candidate.exists():
                return candidate
        candidate = root / file_path.name
        if candidate.exists():
            return candidate
        matches = list(root.rglob(file_path.name))
        return matches[0] if matches else None

    def _load_full_document(self, path: str) -> dict[str, Any]:
        cached = self._document_cache.get(path)
        if cached is not None:
            return dict(cached)

        if not path:
            return {}

        file_path = self._resolve_document_path(path)
        if file_path is None:
            return {}
        raw = file_path.read_text(encoding="utf-8")
        metadata: dict[str, Any] = {"path": path, "kind": file_path.parent.name.rstrip("s")}
        body_lines: list[str] = []
        in_metadata = True
        for line in raw.splitlines():
            stripped = line.strip()
            # Some generated docs have stray blank lines (or bare \r line
            # endings that splitlines() treats as blanks) within the header
            # block; skip them instead of ending metadata mode early.
            if in_metadata and not stripped:
                continue
            if in_metadata and stripped.startswith("#"):
                in_metadata = False
                body_lines.append(line)
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
                        # Some generated docs have stray blank lines (or bare
                        # \r line endings that read() splits into blanks)
                        # within the header block; skip rather than stop.
                        continue
                    if stripped.startswith("#"):
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

    def has_service_tagged_match(self, alert: Alert, min_similarity: float = 0.1) -> bool:
        """True only if some doc explicitly declares this alert's service.

        Unlike _rank_documents (used for general context enrichment, which
        deliberately falls back to the whole corpus so it can still surface
        loosely-related info), this is the strict signal behind
        "document_available": with hundreds of similar-domain ops documents,
        a bare similarity score can't reliably tell "genuinely relevant" from
        "coincidentally shares vocabulary" apart. Requiring an explicit
        services tag first narrows the candidate pool enough that similarity
        becomes a meaningful sanity check rather than the only signal.
        """
        service = str(alert.service or "").strip().lower()
        if not service:
            return False
        candidates = []
        for doc in self.documents:
            doc_services = doc.get("services", [])
            if isinstance(doc_services, str):
                doc_services = [doc_services]
            if not isinstance(doc_services, list) or not doc_services:
                continue
            normalized = {str(item).strip().lower() for item in doc_services if str(item).strip()}
            if service in normalized or any(service in item or item in service for item in normalized):
                candidates.append(doc)
        if not candidates:
            return False
        hydrated = [dict(doc) if doc.get("_synthetic") else self._load_full_document(str(doc.get("path", ""))) for doc in candidates]
        query_vector = self.embedding_model.embed(f"{alert.service} {alert.name} {alert.description}")
        best_score = max(
            cosine_similarity(query_vector, doc.get("_embedding") or self.embedding_model.embed(self._document_text(doc)))
            for doc in hydrated
        )
        return best_score >= min_similarity

    @staticmethod
    def _tokenize(text: Any) -> set[str]:
        return {
            token
            for token in re.findall(r"[a-z0-9][a-z0-9_.:-]{2,}", str(text or "").lower())
            if token not in {"the", "and", "for", "with", "from", "this", "that", "alert", "service"}
        }

    def _doc_match_text(self, doc: dict[str, Any]) -> str:
        services = doc.get("services", [])
        dependencies = doc.get("dependencies", [])
        if isinstance(services, list):
            services = " ".join(str(item) for item in services)
        if isinstance(dependencies, list):
            dependencies = " ".join(str(item) for item in dependencies)
        return " ".join(
            [
                str(doc.get("kind", "")),
                str(doc.get("title", "")),
                str(doc.get("alert_type", "")),
                str(doc.get("alert_id", "")),
                str(doc.get("incident_id", "")),
                str(doc.get("source_ref", "")),
                str(doc.get("source_system", "")),
                str(services),
                str(dependencies),
                str(doc.get("deployment", "")),
                str(doc.get("content", "")),
            ]
        ).lower()

    def _metadata_exact_score(
        self,
        *,
        query: str,
        doc: dict[str, Any],
        service: str | None,
        preferred_kinds: set[str] | None,
    ) -> float:
        query_text = str(query or "").lower()
        doc_text = self._doc_match_text(doc)
        query_tokens = self._tokenize(query_text)
        doc_tokens = self._tokenize(doc_text)

        score = 0.0
        service_token = str(service or "").strip().lower()
        if service_token and service_token in doc_tokens:
            score += 0.22

        doc_kind = str(doc.get("kind") or "").strip().lower()
        if preferred_kinds and doc_kind in preferred_kinds:
            score += 0.08

        alert_tokens = {token for token in query_tokens if "alert" in token or token.endswith("high") or token.endswith("down")}
        if alert_tokens and any(token in doc_text for token in alert_tokens):
            score += 0.18

        metric_tokens = {token for token in query_tokens if "_" in token or token.startswith(("mysql", "kaiops", "http", "queue"))}
        if metric_tokens:
            matched = len([token for token in metric_tokens if token in doc_text])
            score += min(0.18, 0.06 * matched)

        connector_tokens = {"database", "table", "environment", "project", "fingerprint", "source_ref"}
        keyed_tokens = {
            piece.split("=", 1)[1].strip().lower()
            for piece in query_text.split()
            if "=" in piece and piece.split("=", 1)[0].strip().lower() in connector_tokens
        }
        if keyed_tokens:
            matched = len([token for token in keyed_tokens if token and token in doc_text])
            score += min(0.16, 0.05 * matched)

        if "kaiops_alert_health_triage.sh" in query_text and "kaiops_alert_health_triage.sh" in doc_text:
            score += 0.08

        overlap = len(query_tokens & doc_tokens) / max(1, len(query_tokens))
        score += min(0.10, overlap)
        return min(score, 1.0)

    def _metadata_rank_score(self, *, query: str, query_vector: list[float], doc: dict[str, Any], service: str | None, preferred_kinds: set[str] | None) -> float:
        embedding = doc.get("_metadata_embedding")
        if not isinstance(embedding, list):
            embedding = self.embedding_model.embed(self._metadata_text(doc))
            doc["_metadata_embedding"] = embedding
        semantic_score = cosine_similarity(query_vector, embedding)
        exact_score = self._metadata_exact_score(
            query=query,
            doc=doc,
            service=service,
            preferred_kinds=preferred_kinds,
        )
        return (0.55 * semantic_score) + (0.45 * exact_score)

    def _rank_documents(
        self,
        *,
        query: str,
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
        if not candidates and preferred_kinds:
            candidates = [doc for doc in self.documents if self._service_matches(doc, service)]
        if not candidates:
            candidates = list(self.documents)

        shortlist_size = min(max(limit * 4, 12), len(candidates))
        shortlisted = heapq.nlargest(
            shortlist_size,
            candidates,
            key=lambda doc: self._metadata_rank_score(
                query=query,
                query_vector=query_vector,
                doc=doc,
                service=service,
                preferred_kinds=preferred_kinds,
            ),
        )
        hydrated = [dict(doc) if doc.get("_synthetic") else self._load_full_document(str(doc.get("path", ""))) for doc in shortlisted]
        scored = []
        for doc in hydrated:
            semantic_score = cosine_similarity(
                query_vector,
                doc.get("_embedding") or self.embedding_model.embed(self._document_text(doc)),
            )
            metadata_score = self._metadata_exact_score(
                query=query,
                doc=doc,
                service=service,
                preferred_kinds=preferred_kinds,
            )
            match_confidence = max(semantic_score, (0.65 * metadata_score) + (0.35 * max(semantic_score, 0.0)))
            scored.append((match_confidence, semantic_score, metadata_score, doc))
        top = heapq.nlargest(limit, scored, key=lambda item: item[0])
        results = []
        for score, semantic_score, metadata_score, doc in top:
            doc = dict(doc)
            doc["_similarity"] = score
            doc["_semantic_score"] = semantic_score
            doc["_metadata_match_score"] = metadata_score
            doc["match_confidence"] = score
            results.append(doc)
        return results


class ContextGraphState(TypedDict, total=False):
    alert: Alert
    incident: Incident
    connector_results: dict[str, dict[str, Any]]
    context: Context
    graph_stages: list[str]


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
    graph: Any = field(init=False)

    def __post_init__(self) -> None:
        if not self.tool_registry.tools:
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
        self.graph = self._build_graph()

    def _build_graph(self):
        workflow = StateGraph(ContextGraphState)
        workflow.add_node("validate_event", self.validate_event)
        workflow.add_node("collect_connector_evidence", self.collect_connector_evidence)
        workflow.add_node("assemble_context", self.assemble_context)
        workflow.set_entry_point("validate_event")
        workflow.add_edge("validate_event", "collect_connector_evidence")
        workflow.add_edge("collect_connector_evidence", "assemble_context")
        workflow.add_edge("assemble_context", END)
        return workflow.compile()

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

    async def validate_event(self, state: ContextGraphState) -> ContextGraphState:
        if not isinstance(state.get("alert"), Alert) or not isinstance(state.get("incident"), Incident):
            raise ContextFailure("context graph requires alert and incident")
        state["graph_stages"] = [*state.get("graph_stages", []), "validate_event"]
        return state

    async def collect_connector_evidence(self, state: ContextGraphState) -> ContextGraphState:
        alert = state["alert"]
        incident = state["incident"]
        results = await asyncio.gather(
            *[
                retry_async(lambda connector=connector: self._run_connector(connector, alert, incident))
                for connector in self.connectors
            ]
        )
        state["connector_results"] = {
            connector.name: result for connector, result in zip(self.connectors, results, strict=True)
        }
        state["graph_stages"] = [*state.get("graph_stages", []), "collect_connector_evidence"]
        return state

    async def assemble_context(self, state: ContextGraphState) -> ContextGraphState:
        alert = state["alert"]
        incident = state["incident"]
        by_name = state["connector_results"]
        vector_matches = by_name["vector-db"]["matches"]
        vector_connector = next((c for c in self.connectors if isinstance(c, VectorDBConnector)), None)
        service_tagged_match = bool(vector_connector and vector_connector.has_service_tagged_match(alert))
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
        context = Context(
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
                    {
                        "kind": doc.get("kind"),
                        "title": doc.get("title"),
                        "path": doc.get("path"),
                        "similarity": float(doc.get("_similarity", 0.0) or 0.0),
                        "semantic_score": float(doc.get("_semantic_score", doc.get("_similarity", 0.0)) or 0.0),
                        "metadata_match_score": float(doc.get("_metadata_match_score", 0.0) or 0.0),
                        "match_confidence": float(doc.get("match_confidence", doc.get("_similarity", 0.0)) or 0.0),
                    }
                    for doc in vector_matches
                ],
                "rag_top_similarity": max((doc.get("_similarity", 0.0) for doc in vector_matches), default=0.0),
                "rag_top_semantic_score": max((doc.get("_semantic_score", 0.0) for doc in vector_matches), default=0.0),
                "rag_top_metadata_match_score": max((doc.get("_metadata_match_score", 0.0) for doc in vector_matches), default=0.0),
                "rag_top_match_confidence": max((doc.get("match_confidence", doc.get("_similarity", 0.0)) for doc in vector_matches), default=0.0),
                "rag_service_tagged_match": service_tagged_match,
                "rag_index": vector_connector.index_info() if vector_connector else {},
                "context_graph": {
                    "enabled": True,
                    "stages": [*state.get("graph_stages", []), "assemble_context"],
                    "connector_count": len(self.connectors),
                },
            },
        )
        state["context"] = context
        state["graph_stages"] = [*state.get("graph_stages", []), "assemble_context"]
        return state

    async def collect(self, alert: Alert, incident: Incident) -> Context:
        state = await self.graph.ainvoke({"alert": alert, "incident": incident, "graph_stages": []})
        context = state.get("context")
        if not isinstance(context, Context):
            raise ContextFailure("context graph produced non-context output")
        return context

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
