from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
import logging
from typing import Any

from common.config import get_settings
from common.kafka import KafkaConsumer, consume_forever as consume_kafka_forever
from common.notifications import notify
from common.rabbitmq import RabbitMQConsumer, consume_forever as consume_rabbitmq_forever
from common.repository import IncidentRepository
from common.service import create_app
from common.topics import RAW_ALERTS, RESOLUTION_EVENTS
from fastapi import Body, FastAPI

settings = get_settings()
settings.service_name = "notification-service"
tasks: list[asyncio.Task] = []
logger = logging.getLogger("kaiops.notification_service")

ConsumeRunner = Callable[[Any, Callable[[dict], Awaitable[None]]], Coroutine[Any, Any, None]]

_SEVERITY_RANK = {"low": 0, "medium": 1, "warning": 1, "high": 2, "critical": 3}
_LAST_KNOWN_INCIDENT_STATUS: dict[str, str] = {}


def _severity_meets_threshold(severity: str) -> bool:
    minimum = _SEVERITY_RANK.get(str(settings.notification_min_alert_severity or "high").strip().lower(), 2)
    return _SEVERITY_RANK.get(str(severity or "").strip().lower(), 0) >= minimum


async def _handle_raw_alert(payload: dict) -> None:
    alert = payload.get("alert") or {}
    severity = str(alert.get("severity") or "")
    if not _severity_meets_threshold(severity):
        return
    await notify(
        settings,
        title=f"[KaiOps] {severity.upper()} alert: {alert.get('name', 'unknown')}",
        body=str(alert.get("description") or "No description provided."),
        facts={
            "Service": str(alert.get("service") or "unknown"),
            "Environment": str(alert.get("environment") or "unknown"),
            "Severity": severity or "unknown",
            "Source": str(alert.get("source") or "unknown"),
        },
    )


async def _handle_resolution_event(payload: dict) -> None:
    recommendation = payload.get("recommendation") or {}
    incident = payload.get("incident") or {}
    incident_id = str(recommendation.get("incident_id") or incident.get("id") or "unknown")
    await notify(
        settings,
        title=f"[KaiOps] Approval requested for incident {incident_id}",
        body=str(recommendation.get("rationale") or "A recommended action is awaiting human approval."),
        facts={
            "Incident": incident_id,
            "Service": str(incident.get("service") or "unknown"),
            "Recommended action": str(recommendation.get("recommended_action") or "unknown"),
            "Risk": str(recommendation.get("risk") or "unknown"),
        },
    )


async def _incident_status_poll_worker(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            if settings.database_enabled:
                async with app.state.session_factory() as session:
                    repo = IncidentRepository(session)
                    projections = await repo.list_incident_projections(limit=200)
                for projection in projections:
                    incident_id = str(projection.get("incident_id"))
                    status = str(projection.get("status") or "")
                    previous_status = _LAST_KNOWN_INCIDENT_STATUS.get(incident_id)
                    _LAST_KNOWN_INCIDENT_STATUS[incident_id] = status
                    if previous_status is not None and previous_status != status:
                        await notify(
                            settings,
                            title=f"[KaiOps] Incident {incident_id} status changed",
                            body=f"Status changed from '{previous_status}' to '{status}'.",
                            facts={
                                "Incident": incident_id,
                                "Service": str(projection.get("service") or "unknown"),
                                "Previous status": previous_status,
                                "New status": status,
                            },
                        )
        except Exception as exc:
            logger.warning("incident_status_poll_failed", extra={"error": str(exc)})

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=float(settings.notification_incident_poll_interval_seconds))
        except asyncio.TimeoutError:
            continue


async def startup(app: FastAPI) -> None:
    workers = max(1, int(getattr(settings, "message_bus_worker_count", 1) or 1))
    consumers: list[tuple[str, Any, ConsumeRunner]] = []
    # Only RESOLUTION_EVENTS is subscribed here: that's the "approval requested" event,
    # which is the only notification that actually requires the user to take action
    # (approve/reject). Raw alerts are informational only and are intentionally not
    # subscribed to anymore.
    for worker in range(workers):
        consumers.append(
            (f"rabbitmq-resolutions-w{worker + 1}", RabbitMQConsumer(settings, RESOLUTION_EVENTS), consume_rabbitmq_forever)
        )
    if settings.kafka_enabled:
        for worker in range(workers):
            consumers.append(
                (f"kafka-resolutions-w{worker + 1}", KafkaConsumer(settings, RESOLUTION_EVENTS), consume_kafka_forever)
            )

    for source, consumer, consume_forever in consumers:
        handler = _handle_raw_alert if "alerts" in source else _handle_resolution_event
        task = asyncio.create_task(consume_forever(consumer, handler), name=f"notification-service-{source}-consumer")
        tasks.append(task)

    # Incident status-changed notifications (investigating -> remediating -> closed) are
    # informational only, not action-required, so the poll worker is intentionally not
    # started anymore.
    app.state.notification_stop_event = asyncio.Event()
    app.state.incident_status_poll_task = None


async def shutdown(_: FastAPI) -> None:
    stop_event = getattr(app.state, "notification_stop_event", None)
    if stop_event is not None:
        stop_event.set()
    poll_task = getattr(app.state, "incident_status_poll_task", None)
    if poll_task is not None:
        poll_task.cancel()
    for task in tasks:
        task.cancel()


app = create_app(title="KaiMS Notification Service", settings=settings, startup=startup, shutdown=shutdown)


@app.post("/notify/test")
async def send_test_notification(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    title = str(payload.get("title") or "[KaiOps] Test notification")
    body = str(payload.get("body") or "This is a test notification from KaiOps.")
    await notify(settings, title=title, body=body, facts={"Triggered by": "manual test"})
    return {
        "sent": True,
        "email_enabled": settings.smtp_enabled,
        "teams_enabled": settings.teams_enabled,
    }






# from __future__ import annotations

# import asyncio
# from collections.abc import Awaitable, Callable, Coroutine
# import logging
# from typing import Any

# from common.config import get_settings
# from common.kafka import KafkaConsumer, consume_forever as consume_kafka_forever
# from common.notifications import notify
# from common.rabbitmq import RabbitMQConsumer, consume_forever as consume_rabbitmq_forever
# from common.repository import IncidentRepository
# from common.service import create_app
# from common.topics import RAW_ALERTS, RESOLUTION_EVENTS
# from fastapi import Body, FastAPI

# settings = get_settings()
# settings.service_name = "notification-service"
# tasks: list[asyncio.Task] = []
# logger = logging.getLogger("kaiops.notification_service")

# ConsumeRunner = Callable[[Any, Callable[[dict], Awaitable[None]]], Coroutine[Any, Any, None]]

# _SEVERITY_RANK = {"low": 0, "medium": 1, "warning": 1, "high": 2, "critical": 3}
# _LAST_KNOWN_INCIDENT_STATUS: dict[str, str] = {}


# def _severity_meets_threshold(severity: str) -> bool:
#     minimum = _SEVERITY_RANK.get(str(settings.notification_min_alert_severity or "high").strip().lower(), 2)
#     return _SEVERITY_RANK.get(str(severity or "").strip().lower(), 0) >= minimum


# async def _handle_raw_alert(payload: dict) -> None:
#     alert = payload.get("alert") or {}
#     severity = str(alert.get("severity") or "")
#     if not _severity_meets_threshold(severity):
#         return
#     await notify(
#         settings,
#         title=f"[KaiOps] {severity.upper()} alert: {alert.get('name', 'unknown')}",
#         body=str(alert.get("description") or "No description provided."),
#         facts={
#             "Service": str(alert.get("service") or "unknown"),
#             "Environment": str(alert.get("environment") or "unknown"),
#             "Severity": severity or "unknown",
#             "Source": str(alert.get("source") or "unknown"),
#         },
#     )


# async def _handle_resolution_event(payload: dict) -> None:
#     recommendation = payload.get("recommendation") or {}
#     incident = payload.get("incident") or {}
#     incident_id = str(recommendation.get("incident_id") or incident.get("id") or "unknown")
#     await notify(
#         settings,
#         title=f"[KaiOps] Approval requested for incident {incident_id}",
#         body=str(recommendation.get("rationale") or "A recommended action is awaiting human approval."),
#         facts={
#             "Incident": incident_id,
#             "Service": str(incident.get("service") or "unknown"),
#             "Recommended action": str(recommendation.get("recommended_action") or "unknown"),
#             "Risk": str(recommendation.get("risk") or "unknown"),
#         },
#     )


# async def _incident_status_poll_worker(stop_event: asyncio.Event) -> None:
#     while not stop_event.is_set():
#         try:
#             if settings.database_enabled:
#                 async with app.state.session_factory() as session:
#                     repo = IncidentRepository(session)
#                     projections = await repo.list_incident_projections(limit=200)
#                 for projection in projections:
#                     incident_id = str(projection.get("incident_id"))
#                     status = str(projection.get("status") or "")
#                     previous_status = _LAST_KNOWN_INCIDENT_STATUS.get(incident_id)
#                     _LAST_KNOWN_INCIDENT_STATUS[incident_id] = status
#                     if previous_status is not None and previous_status != status:
#                         await notify(
#                             settings,
#                             title=f"[KaiOps] Incident {incident_id} status changed",
#                             body=f"Status changed from '{previous_status}' to '{status}'.",
#                             facts={
#                                 "Incident": incident_id,
#                                 "Service": str(projection.get("service") or "unknown"),
#                                 "Previous status": previous_status,
#                                 "New status": status,
#                             },
#                         )
#         except Exception as exc:
#             logger.warning("incident_status_poll_failed", extra={"error": str(exc)})

#         try:
#             await asyncio.wait_for(stop_event.wait(), timeout=float(settings.notification_incident_poll_interval_seconds))
#         except asyncio.TimeoutError:
#             continue


# async def startup(app: FastAPI) -> None:
#     workers = max(1, int(getattr(settings, "message_bus_worker_count", 1) or 1))
#     consumers: list[tuple[str, Any, ConsumeRunner]] = []
#     for worker in range(workers):
#         consumers.append((f"rabbitmq-alerts-w{worker + 1}", RabbitMQConsumer(settings, RAW_ALERTS), consume_rabbitmq_forever))
#         consumers.append((f"rabbitmq-alerts-w{worker + 1}", RabbitMQConsumer(settings, RAW_ALERTS), consume_rabbitmq_forever))
#         consumers.append(
#             (f"rabbitmq-resolutions-w{worker + 1}", RabbitMQConsumer(settings, RESOLUTION_EVENTS), consume_rabbitmq_forever)
#         )
#     if settings.kafka_enabled:
#         for worker in range(workers):
#             consumers.append((f"kafka-alerts-w{worker + 1}", KafkaConsumer(settings, RAW_ALERTS), consume_kafka_forever))
#             consumers.append((f"kafka-alerts-w{worker + 1}", KafkaConsumer(settings, RAW_ALERTS), consume_kafka_forever))
#             consumers.append(
#                 (f"kafka-resolutions-w{worker + 1}", KafkaConsumer(settings, RESOLUTION_EVENTS), consume_kafka_forever)
#             )

#     for source, consumer, consume_forever in consumers:
#         handler = _handle_raw_alert if "alerts" in source else _handle_resolution_event
#         task = asyncio.create_task(consume_forever(consumer, handler), name=f"notification-service-{source}-consumer")
#         tasks.append(task)

#     app.state.notification_stop_event = asyncio.Event()
#     app.state.incident_status_poll_task = asyncio.create_task(
#         _incident_status_poll_worker(app.state.notification_stop_event)
#     )


# async def shutdown(_: FastAPI) -> None:
#     stop_event = getattr(app.state, "notification_stop_event", None)
#     if stop_event is not None:
#         stop_event.set()
#     poll_task = getattr(app.state, "incident_status_poll_task", None)
#     if poll_task is not None:
#         poll_task.cancel()
#     for task in tasks:
#         task.cancel()


# app = create_app(title="KaiMS Notification Service", settings=settings, startup=startup, shutdown=shutdown)


# @app.post("/notify/test")
# async def send_test_notification(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
#     title = str(payload.get("title") or "[KaiOps] Test notification")
#     body = str(payload.get("body") or "This is a test notification from KaiOps.")
#     await notify(settings, title=title, body=body, facts={"Triggered by": "manual test"})
#     return {
#         "sent": True,
#         "email_enabled": settings.smtp_enabled,
#         "teams_enabled": settings.teams_enabled,
#     }
