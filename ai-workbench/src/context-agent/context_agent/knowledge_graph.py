from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Iterable


def _tokens(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _node_id(kind: str, value: str) -> str:
    return f"{kind}:{value.strip().lower()}"


@dataclass(slots=True)
class KnowledgeGraph:
    nodes: dict[str, dict[str, Any]] = field(default_factory=dict)
    edges: list[dict[str, str]] = field(default_factory=list)
    _adjacency: dict[str, list[tuple[str, str]]] = field(default_factory=lambda: defaultdict(list))

    def add_node(self, node_id: str, kind: str, label: str, **metadata: Any) -> None:
        current = self.nodes.setdefault(node_id, {"id": node_id, "kind": kind, "label": label})
        current.update({key: value for key, value in metadata.items() if value not in (None, "", [])})

    def add_edge(self, source: str, relation: str, target: str) -> None:
        if source == target or source not in self.nodes or target not in self.nodes:
            return
        edge = {"source": source, "relation": relation, "target": target}
        if edge in self.edges:
            return
        self.edges.append(edge)
        self._adjacency[source].append((relation, target))
        self._adjacency[target].append((f"inverse:{relation}", source))

    @classmethod
    def from_documents(cls, documents: Iterable[dict[str, Any]]) -> "KnowledgeGraph":
        graph = cls()
        for index, document in enumerate(documents):
            if not isinstance(document, dict):
                continue
            path = str(document.get("path") or f"document-{index}").strip()
            kind = str(document.get("kind") or "document").strip().lower()
            title = str(document.get("title") or path).strip()
            document_id = _node_id("document", path)
            graph.add_node(document_id, kind, title, node_type="document", path=path, severity=document.get("severity"))

            services = _tokens(document.get("services"))
            primary_service = str(document.get("service") or "").strip()
            if primary_service and primary_service not in services:
                services.append(primary_service)
            for service in services:
                service_id = _node_id("service", service)
                graph.add_node(service_id, "service", service)
                graph.add_edge(service_id, "HAS_KNOWLEDGE", document_id)

                for dependency in _tokens(document.get("dependencies")):
                    dependency_id = _node_id("service", dependency)
                    graph.add_node(dependency_id, "service", dependency)
                    graph.add_edge(service_id, "DEPENDS_ON", dependency_id)

                deployment = str(document.get("deployment") or "").strip()
                if deployment:
                    deployment_id = _node_id("deployment", deployment)
                    graph.add_node(deployment_id, "deployment", deployment)
                    graph.add_edge(service_id, "DEPLOYED_AS", deployment_id)

            incident_id = str(document.get("incident_id") or document.get("alert_id") or "").strip()
            if incident_id:
                incident_node = _node_id("incident", incident_id)
                graph.add_node(incident_node, "incident", incident_id)
                graph.add_edge(incident_node, "DESCRIBED_BY", document_id)
                for service in services:
                    graph.add_edge(_node_id("service", service), "AFFECTED_BY", incident_node)
        return graph

    def context(self, service: str, *, depth: int = 2, limit: int = 80) -> dict[str, Any]:
        root = _node_id("service", service)
        if root not in self.nodes:
            return {"service": service, "root": root, "nodes": [], "edges": [], "dependencies": [], "documents": []}
        visited = {root}
        queue: deque[tuple[str, int]] = deque([(root, 0)])
        while queue and len(visited) < max(1, limit):
            current, level = queue.popleft()
            if level >= max(0, depth):
                continue
            for _, target in self._adjacency.get(current, []):
                if target not in visited:
                    visited.add(target)
                    queue.append((target, level + 1))
        edges = [edge for edge in self.edges if edge["source"] in visited and edge["target"] in visited]
        nodes = [self.nodes[node_id] for node_id in sorted(visited)]
        dependencies = [
            self.nodes[edge["target"]]["label"]
            for edge in edges
            if edge["source"] == root and edge["relation"] == "DEPENDS_ON"
        ]
        documents = [node for node in nodes if node.get("node_type") == "document"]
        return {
            "service": service,
            "root": root,
            "nodes": nodes,
            "edges": edges,
            "dependencies": dependencies,
            "documents": documents,
        }

    def summary(self) -> dict[str, Any]:
        kinds: dict[str, int] = defaultdict(int)
        relations: dict[str, int] = defaultdict(int)
        for node in self.nodes.values():
            kinds[str(node.get("kind") or "unknown")] += 1
        for edge in self.edges:
            relations[edge["relation"]] += 1
        return {
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
            "node_kinds": dict(sorted(kinds.items())),
            "relations": dict(sorted(relations.items())),
        }
