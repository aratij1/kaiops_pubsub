from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from time import monotonic
from typing import Any

from redis.asyncio import Redis

from common.config import Settings

_cancelled_cache: dict[str, tuple[float, set[str]]] = {}
_cancellation_clients: dict[str, Redis] = {}


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


def extract_processing_identities(payload: dict[str, Any]) -> list[str]:
    envelope = payload.get("event_envelope") if isinstance(payload.get("event_envelope"), dict) else {}
    contract = payload.get("event_contract") if isinstance(payload.get("event_contract"), dict) else {}
    candidates = [payload.get("alert_id"), payload.get("incident_id"), payload.get("id"), envelope.get("alert_id"), envelope.get("incident_id"), contract.get("alert_id"), contract.get("incident_id"), extract_message_identity(payload)]
    return list(dict.fromkeys(str(value).strip() for value in candidates if str(value or "").strip()))


async def processing_cancelled(settings: Settings, payload: dict[str, Any]) -> bool:
    identities = extract_processing_identities(payload)
    if not identities:
        return False
    cached_at, cancelled = _cancelled_cache.get(settings.redis_url, (0.0, set()))
    if monotonic() - cached_at < 2.0:
        return any(identity in cancelled for identity in identities)
    client = _cancellation_clients.get(settings.redis_url)
    if client is None:
        client = Redis.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=1, socket_timeout=1)
        _cancellation_clients[settings.redis_url] = client
    try:
        cancelled = {str(value) for value in await client.smembers("kaims:cancelled-processing")}
        _cancelled_cache[settings.redis_url] = (monotonic(), cancelled)
        return any(identity in cancelled for identity in identities)
    except Exception:
        # Queue processing must fail open if the cancellation control store is
        # temporarily unavailable; broker durability remains authoritative.
        return False


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
