from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class KnowledgeQuery:
    service: str
    incident_id: str | None = None
    preferred_kinds: set[str] = field(default_factory=set)
    limit: int = 5


class KnowledgeSource:
    async def search(self, query: KnowledgeQuery) -> list[dict[str, Any]]:
        raise NotImplementedError


@dataclass(slots=True)
class KnowledgeRouter:
    sources: dict[str, KnowledgeSource] = field(default_factory=dict)

    def register(self, name: str, source: KnowledgeSource) -> None:
        self.sources[name] = source

    async def route(self, query: KnowledgeQuery) -> dict[str, list[dict[str, Any]]]:
        results: dict[str, list[dict[str, Any]]] = {}
        for name, source in self.sources.items():
            items = await source.search(query)
            results[name] = items
        return results
