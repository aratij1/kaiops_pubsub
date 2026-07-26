from __future__ import annotations

import email
import imaplib
import logging
import re
from dataclasses import dataclass
from email.header import decode_header
from email.utils import parsedate_to_datetime
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


def fetch_unseen_emails(config: ImapConfig, *, limit: int = 25) -> list[dict[str, Any]]:
    """Connect to the mailbox, fetch unseen messages, and return them as plain dicts.

    This is a blocking, synchronous call (imaplib has no async API) — callers
    running inside an asyncio event loop should invoke it via asyncio.to_thread.
    """
    results: list[dict[str, Any]] = []
    connection_cls = imaplib.IMAP4_SSL if config.use_ssl else imaplib.IMAP4
    connection = connection_cls(config.host, config.port, timeout=max(1.0, config.timeout_seconds))
    try:
        connection.login(config.username, config.password)
        connection.select(config.mailbox)
        status, data = connection.search(None, "UNSEEN")
        if status != "OK":
            logger.warning("IMAP search failed: %s", status)
            return results
        message_ids = data[0].split()[:limit]
        for message_id in message_ids:
            status, msg_data = connection.fetch(message_id, "(RFC822)")
            if status != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                continue
            raw_message = msg_data[0][1]
            message = email.message_from_bytes(raw_message)
            subject = _decode_mime_header(message.get("Subject")) or "(no subject)"
            if config.subject_pattern and re.search(config.subject_pattern, subject) is None:
                continue
            received_at = ""
            try:
                date_header = message.get("Date")
                if date_header:
                    received_at = parsedate_to_datetime(date_header).isoformat()
            except (TypeError, ValueError):
                received_at = ""
            results.append(
                {
                    "message_id": _decode_mime_header(message.get("Message-ID")) or message_id.decode("utf-8", errors="replace"),
                    "subject": subject,
                    "from": _decode_mime_header(message.get("From")),
                    "to": _decode_mime_header(message.get("To")),
                    "received_at": received_at,
                    "body": _extract_body(message)[:4000],
                }
            )
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


def infer_severity_from_subject(subject: str) -> str:
    lowered = subject.lower()
    if any(token in lowered for token in ("critical", "urgent", "sev1", "p1", "down")):
        return "critical"
    if any(token in lowered for token in ("high", "sev2", "p2")):
        return "high"
    if any(token in lowered for token in ("low", "sev4", "sev5", "info", "fyi")):
        return "info"
    return "warning"


def email_to_alert_payload(message: dict[str, Any], *, default_service: str = "email-inbox") -> dict[str, Any]:
    """Normalize a fetched email dict into the same mapped-payload shape the
    Prometheus/Alertmanager and Jira ingestion paths produce, so it flows
    through the identical _build_alert_from_payload -> publish -> landing-pad
    pipeline regardless of source.
    """
    subject = str(message.get("subject") or "(no subject)")
    sender = str(message.get("from") or "unknown-sender")
    body = str(message.get("body") or "")
    return {
        "source": "email",
        "name": subject,
        "service": default_service,
        "environment": "prod",
        "severity": infer_severity_from_subject(subject),
        "description": body[:500] or subject,
        "labels": {
            "alert_status": "firing",
            "email_from": sender,
            "email_message_id": str(message.get("message_id") or ""),
        },
        "annotations": {
            "summary": subject,
            "body": body,
            "received_at": str(message.get("received_at") or ""),
        },
    }
