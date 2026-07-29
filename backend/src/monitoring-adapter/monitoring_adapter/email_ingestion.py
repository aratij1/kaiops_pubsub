from __future__ import annotations

import email
import imaplib
import json
import logging
import re
from dataclasses import dataclass, field
from email.header import decode_header
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("monitoring-adapter.email-ingestion")


@dataclass
class ImapConfig:
    host: str
    port: int
    username: str
    password: str
    mailbox: str = "INBOX"
    use_ssl: bool = True
    mark_seen: bool = True
    timeout_seconds: float = 20.0
    subject_pattern: str = r"(?i)\b(alert|incident|critical|warning|error|failure|failed|down|sev[1-5]|p[1-5])\b"
    search_criterion: str = "UNSEEN"


@dataclass
class EmailPollState:
    """Persists the highest processed IMAP UID per mailbox, so ingestion
    tracks new mail independently of the \\Seen flag — any other client
    (webmail, mobile app) opening a message no longer hides it from the
    poller, unlike a pure UNSEEN-search approach."""

    state_path: Path
    _cache: dict[str, int] = field(default_factory=dict, init=False, repr=False)

    def _load(self) -> dict[str, int]:
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            return {str(k): int(v) for k, v in payload.items()} if isinstance(payload, dict) else {}
        except (OSError, ValueError):
            return {}

    def last_uid(self, key: str) -> int:
        if not self._cache:
            self._cache = self._load()
        return int(self._cache.get(key, 0))

    def set_last_uid(self, key: str, uid: int) -> None:
        if not self._cache:
            self._cache = self._load()
        self._cache[key] = uid
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps(self._cache), encoding="utf-8")
        except OSError:
            logger.exception("failed to persist email ingestion state")


def _decode_mime_header(value: str | None) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    decoded = []
    for text, charset in parts:
        if isinstance(text, bytes):
            decoded.append(text.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(text)
    return "".join(decoded).strip()


def _extract_body(message: email.message.Message) -> str:
    if message.is_multipart():
        for part in message.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition") or "")
            if content_type == "text/plain" and "attachment" not in disposition:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace").strip()
        return ""
    payload = message.get_payload(decode=True)
    if not payload:
        return str(message.get_payload() or "").strip()
    charset = message.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace").strip()


def fetch_unseen_emails(
    config: ImapConfig, *, limit: int = 25, state: EmailPollState | None = None
) -> list[dict[str, Any]]:
    """Connect to the mailbox and return new alert-matching messages as plain dicts.

    When `state` is provided, new mail is determined by IMAP UID (persisted
    checkpoint) rather than the `\\Seen` flag — a message opened by any other
    mail client (webmail, phone) before this poller's next cycle no longer
    makes it invisible to ingestion, which a pure `SEARCH UNSEEN` approach
    cannot avoid. Falls back to `config.search_criterion` (default UNSEEN)
    when no state is given, preserving prior behavior for callers/tests that
    don't pass one.

    This is a blocking, synchronous call (imaplib has no async API) — callers
    running inside an asyncio event loop should invoke it via asyncio.to_thread.
    """
    results: list[dict[str, Any]] = []
    connection_cls = imaplib.IMAP4_SSL if config.use_ssl else imaplib.IMAP4
    connection = connection_cls(config.host, config.port, timeout=max(1.0, config.timeout_seconds))
    try:
        connection.login(config.username, config.password)
        connection.select(config.mailbox)

        if state is not None:
            state_key = f"{config.host}:{config.username}:{config.mailbox}"
            last_uid = state.last_uid(state_key)
            status, data = connection.uid("search", None, f"UID {last_uid + 1}:*")
            if status != "OK":
                logger.warning("IMAP UID search failed: %s", status)
                return results
            # "UID x:*" can return the mailbox's single highest UID even when
            # it's <= x (RFC 3501 edge case on some servers) — filter it out
            # explicitly rather than trusting the search result verbatim.
            candidate_uids = [uid for uid in data[0].split() if int(uid) > last_uid]
            # On first connection, start from the newest messages instead of
            # replaying an entire long-lived mailbox from UID 1. Subsequent
            # polls remain ascending so no newly arrived messages are skipped.
            uids = (
                candidate_uids[-limit:]
                if last_uid <= 0
                else candidate_uids[:limit]
            )
            max_uid_seen = last_uid
            for uid in uids:
                status, msg_data = connection.uid("fetch", uid, "(RFC822)")
                if status != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                    continue
                max_uid_seen = max(max_uid_seen, int(uid))
                message = email.message_from_bytes(msg_data[0][1])
                subject = _decode_mime_header(message.get("Subject")) or "(no subject)"
                if config.subject_pattern and re.search(config.subject_pattern, subject) is None:
                    continue
                results.append(_message_to_dict(message, fallback_id=uid.decode("utf-8", errors="replace")))
                if config.mark_seen:
                    connection.uid("store", uid, "+FLAGS", "\\Seen")
            if max_uid_seen > last_uid:
                state.set_last_uid(state_key, max_uid_seen)
            return results

        criterion = str(config.search_criterion or "UNSEEN").strip().upper()
        if criterion not in {"UNSEEN", "ALL"}:
            criterion = "UNSEEN"
        status, data = connection.search(None, criterion)
        if status != "OK":
            logger.warning("IMAP search failed: %s", status)
            return results
        message_ids = data[0].split()[-limit:]
        for message_id in message_ids:
            status, msg_data = connection.fetch(message_id, "(RFC822)")
            if status != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                continue
            message = email.message_from_bytes(msg_data[0][1])
            subject = _decode_mime_header(message.get("Subject")) or "(no subject)"
            if config.subject_pattern and re.search(config.subject_pattern, subject) is None:
                continue
            results.append(_message_to_dict(message, fallback_id=message_id.decode("utf-8", errors="replace")))
            if config.mark_seen:
                connection.store(message_id, "+FLAGS", "\\Seen")
        return results
    finally:
        try:
            connection.close()
        except Exception:
            pass
        try:
            connection.logout()
        except Exception:
            pass


def _message_to_dict(message: email.message.Message, *, fallback_id: str) -> dict[str, Any]:
    received_at = ""
    try:
        date_header = message.get("Date")
        if date_header:
            received_at = parsedate_to_datetime(date_header).isoformat()
    except (TypeError, ValueError):
        received_at = ""
    return {
        "message_id": _decode_mime_header(message.get("Message-ID")) or fallback_id,
        "subject": _decode_mime_header(message.get("Subject")) or "(no subject)",
        "from": _decode_mime_header(message.get("From")),
        "to": _decode_mime_header(message.get("To")),
        "received_at": received_at,
        "body": _extract_body(message)[:4000],
    }


def infer_severity_from_subject(subject: str) -> str:
    lowered = subject.lower()
    if any(token in lowered for token in ("critical", "urgent", "sev1", "p1", "down")):
        return "critical"
    if any(token in lowered for token in ("high", "sev2", "p2")):
        return "high"
    if any(token in lowered for token in ("low", "sev4", "sev5", "info", "fyi")):
        return "info"
    return "warning"


def infer_affected_service(*values: object, fallback: str = "unresolved-service") -> str:
    """Extract the affected workload without confusing its transport with it."""
    text = " ".join(str(value or "") for value in values)
    patterns = (
        r"\b(?:service|application|app|component|workload)\s*[:=]\s*([a-z0-9][a-z0-9._-]{1,80})",
        r"\b(?:on|affecting|for)\s+([a-z0-9][a-z0-9._-]{1,80}-(?:api|service|worker|db|database|frontend|backend))\b",
        r"\b([a-z0-9][a-z0-9._-]{1,80}-(?:api|service|worker|db|database|frontend|backend))\b",
    )
    ignored = {
        "email-inbox",
        "email-service",
        "jira-service",
        "jira-tickets",
        "ticket-service",
    }
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            candidate = match.group(1).strip(" .,:;()[]{}").lower()
            if candidate and candidate not in ignored:
                return candidate
    normalized_fallback = str(fallback or "").strip().lower()
    return normalized_fallback if normalized_fallback and normalized_fallback not in ignored else "unresolved-service"


def email_to_alert_payload(message: dict[str, Any], *, default_service: str = "email-inbox") -> dict[str, Any]:
    """Normalize a fetched email dict into the same mapped-payload shape the
    Prometheus/Alertmanager and Jira ingestion paths produce, so it flows
    through the identical _build_alert_from_payload -> publish -> landing-pad
    pipeline regardless of source.
    """
    subject = str(message.get("subject") or "(no subject)")
    sender = str(message.get("from") or "unknown-sender")
    body = str(message.get("body") or "")
    affected_service = infer_affected_service(subject, body, fallback=default_service)
    return {
        "source": "email",
        "name": subject,
        "service": affected_service,
        "environment": "prod",
        "severity": infer_severity_from_subject(subject),
        "description": body[:500] or subject,
        "labels": {
            "alert_status": "firing",
            "origin_system": "email",
            "ingestion_channel": "email",
            "email_from": sender,
            "email_message_id": str(message.get("message_id") or ""),
        },
        "annotations": {
            "summary": subject,
            "body": body,
            "received_at": str(message.get("received_at") or ""),
        },
    }
