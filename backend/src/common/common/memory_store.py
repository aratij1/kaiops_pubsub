from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class MemoryStore:
    async def append(self, namespace: str, item: dict[str, Any]) -> None:
        raise NotImplementedError

    async def recent(self, namespace: str, limit: int = 20) -> list[dict[str, Any]]:
        raise NotImplementedError


@dataclass(slots=True)
class InMemoryStore(MemoryStore):
    _store: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    async def append(self, namespace: str, item: dict[str, Any]) -> None:
        bucket = self._store.setdefault(namespace, [])
        bucket.append(dict(item))

    async def recent(self, namespace: str, limit: int = 20) -> list[dict[str, Any]]:
        bucket = self._store.get(namespace, [])
        return bucket[-max(1, int(limit)) :]
