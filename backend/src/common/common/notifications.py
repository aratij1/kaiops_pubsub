from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage
from typing import Any

import httpx

from common.config import Settings

logger = logging.getLogger("kaiops.notifications")


def _recipient_list(settings: Settings) -> list[str]:
    raw = settings.notification_recipient_emails or ""
    return [address.strip() for address in raw.split(",") if address.strip()]


def _send_email_sync(settings: Settings, subject: str, body: str, recipients: list[str]) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_from_address
    message["To"] = ", ".join(recipients)
    message.set_content(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as client:
        if settings.smtp_use_tls:
            client.starttls()
        if settings.smtp_username:
            client.login(settings.smtp_username, settings.smtp_password)
        client.send_message(message)


async def send_email(settings: Settings, *, subject: str, body: str) -> bool:
    if not settings.smtp_enabled or not settings.smtp_host:
        return False
    recipients = _recipient_list(settings)
    if not recipients:
        logger.warning("email_notification_skipped_no_recipients")
        return False
    try:
        await asyncio.to_thread(_send_email_sync, settings, subject, body, recipients)
        return True
    except Exception as exc:
        logger.warning("email_notification_failed", extra={"error": str(exc)})
        return False


def _teams_card(title: str, text: str, facts: dict[str, str]) -> dict[str, Any]:
    return {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "summary": title,
        "themeColor": "E81123",
        "title": title,
        "text": text,
        "sections": [
            {
                "facts": [{"name": key, "value": value} for key, value in facts.items()],
            }
        ],
    }


async def send_teams_message(settings: Settings, *, title: str, text: str, facts: dict[str, str] | None = None) -> bool:
    if not settings.teams_enabled or not settings.teams_webhook_url:
        return False
    payload = _teams_card(title, text, facts or {})
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(settings.teams_webhook_url, json=payload)
            response.raise_for_status()
        return True
    except Exception as exc:
        logger.warning("teams_notification_failed", extra={"error": str(exc)})
        return False


async def notify(settings: Settings, *, title: str, body: str, facts: dict[str, str] | None = None) -> None:
    await asyncio.gather(
        send_email(settings, subject=title, body=body),
        send_teams_message(settings, title=title, text=body, facts=facts),
    )
