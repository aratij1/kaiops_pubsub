from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Any


def extract_message_identity(payload: dict[str, Any]) -> str | None:
    if not isinstance(payload, dict):
        return None

    candidates = []
    event_envelope = payload.get("event_envelope") if isinstance(payload.get("event_envelope"), dict) else {}
    event_contract = payload.get("event_contract") if isinstance(payload.get("event_contract"), dict) else {}
    idempotency = payload.get("idempotency") if isinstance(payload.get("idempotency"), dict) else {}
    envelope_idempotency = (
        event_envelope.get("idempotency") if isinstance(event_envelope.get("idempotency"), dict) else {}
    )

    candidates.extend(
        [
            event_envelope.get("event_id"),
            envelope_idempotency.get("idempotency_key"),
            event_contract.get("event_id"),
            payload.get("event_id"),
            idempotency.get("idempotency_key"),
        ]
    )

    for candidate in candidates:
        token = str(candidate or "").strip()
        if token:
            return token
    return None


class ProcessedMessageCache:
    def __init__(self, *, ttl_seconds: int = 3600, max_entries: int = 10000) -> None:
        self._ttl = timedelta(seconds=max(60, int(ttl_seconds or 3600)))
        self._max_entries = max(100, int(max_entries or 10000))
        self._entries: OrderedDict[str, datetime] = OrderedDict()

    def _purge_expired(self) -> None:
        cutoff = datetime.now(timezone.utc) - self._ttl
        while self._entries:
            key, value = next(iter(self._entries.items()))
            if value >= cutoff:
                break
            self._entries.pop(key, None)

    def contains(self, key: str | None) -> bool:
        if not key:
            return False
        self._purge_expired()
        token = str(key).strip()
        if not token:
            return False
        return token in self._entries

    def mark(self, key: str | None) -> None:
        if not key:
            return
        token = str(key).strip()
        if not token:
            return
        self._purge_expired()
        self._entries.pop(token, None)
        self._entries[token] = datetime.now(timezone.utc)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)