from __future__ import annotations

import asyncio
import os

from common.ai_layer_client import AiLayerClient
from common.config import get_settings
from common.event_publishers import build_event_consumer, build_orchestration_envelope, selected_event_bus_provider
from common.repository import IncidentRepository
from common.logging import get_logger
from common.models import Alert, Incident
from common.service import create_app
from common.telemetry import EVENTS_PROCESSED
from common.topics import ENRICHED_ALERTS, ORCHESTRATION_EVENTS, RESOLUTION_EVENTS
from fastapi import FastAPI, HTTPException
from orchestrator.message_bus import publish_orchestration_event
from orchestrator import OrchestratorAgent

settings = get_settings()
settings.service_name = "orchestrator"
agent = OrchestratorAgent()
ai_client = AiLayerClient(settings)
tasks: list[asyncio.Task] = []
logger = get_logger(__name__)
MESSAGE_BUS_DUAL_CONSUME_ENABLED = str(
    os.getenv("MESSAGE_BUS_DUAL_CONSUME_ENABLED", "false")
).strip().lower() in {"1", "true", "yes", "on"}
ORCHESTRATOR_INLINE_RESOLUTION_ENABLED = str(
    os.getenv("ORCHESTRATOR_INLINE_RESOLUTION_ENABLED", "false")
).strip().lower() in {"1", "true", "yes", "on"}


async def _persist_orchestration_event(app: FastAPI, envelope: dict) -> None:
    session_factory = getattr(app.state, "session_factory", None)
    if session_factory is None:
        logger.warning("orchestrator metadata persistence skipped; database session factory unavailable")
        return

    async with session_factory() as session:
        repo = IncidentRepository(session)
        await repo.save_incident_event(envelope)
        await session.commit()


async def _run_resolution_and_publish(
    app: FastAPI,
    *,
    alert: Alert,
    incident: Incident,
    decision_dict: dict,
) -> None:
    # Orchestrator only *decided* a workflow above; nothing previously consumed
    # ORCHESTRATION_EVENTS to actually run Context/Resolution, so real alerts
    # never got a recommendation.generated audit row and the UI showed no RCA.
    # This closes that gap using the same AiLayerClient methods the
    # local-demo workflow (monitoring-adapter.run_local_payment_workflow)
    # already calls, so Context/Resolution logic is not duplicated here.
    context = await ai_client.collect_context(alert=alert, incident=incident)
    recommendation = await ai_client.resolve(context=context)
    recommendation.incident_id = incident.id
    recommendation.metadata["orchestration_decision"] = decision_dict

    session_factory = getattr(app.state, "session_factory", None)
    if session_factory is not None:
        async with session_factory() as session:
            repo = IncidentRepository(session)
            await repo.save_recommendation_as_audit(recommendation)
            await session.commit()

    await app.state.producer.publish(
        RESOLUTION_EVENTS,
        {
            "alert": alert.model_dump(mode="json"),
            "incident": incident.model_dump(mode="json"),
            "decision": decision_dict,
            "recommendation": recommendation.model_dump(mode="json"),
        },
        key=str(incident.id),
    )


def _build_ingress_consumers() -> list[tuple[str, object, object]]:
    workers = max(1, int(getattr(settings, "message_bus_worker_count", 1) or 1))
    consumers: list[tuple[str, object, object]] = []
    for worker in range(workers):
        consumer, loop, provider = build_event_consumer(settings, ENRICHED_ALERTS)
        consumers.append((f"{provider}-w{worker + 1}", consumer, loop))
    return consumers


async def startup(app: FastAPI) -> None:
    app.state.temporal_client = None
    if settings.temporal_pilot_enabled:
        from temporalio.client import Client

        app.state.temporal_client = await Client.connect(
            settings.temporal_address,
            namespace=settings.temporal_namespace,
        )
    app.state.message_bus_provider = selected_event_bus_provider(settings)

    async def handle(payload: dict) -> None:
        alert = Alert.model_validate(payload["alert"])
        incident = Incident.model_validate(payload["incident"])
        decision = await agent.decide_workflow_async_with_runtime(alert, incident)
        transport_provider = str(decision.__dict__.get("message_bus_provider") or "kafka")
        event_envelope = build_orchestration_envelope(
            alert=alert,
            incident=incident,
            decision=decision.__dict__,
            transport_provider=transport_provider,
            channel=ORCHESTRATION_EVENTS,
        )
        try:
            await _persist_orchestration_event(app, event_envelope)
        except Exception:
            logger.exception("orchestrator metadata persistence failed")
        if settings.temporal_pilot_enabled:
            workflow_id = f"kaiops-incident-{incident.id}"
            try:
                await app.state.temporal_client.start_workflow(
                    "KaiOpsIncidentPilotWorkflow",
                    {
                        "alert": alert.model_dump(mode="json"),
                        "incident": incident.model_dump(mode="json"),
                        "decision": decision.__dict__,
                        "trace_id": str(alert.trace_id or ""),
                        "approval_timeout_hours": settings.temporal_approval_timeout_hours,
                    },
                    id=workflow_id,
                    task_queue=settings.temporal_task_queue,
                )
            except Exception as exc:
                if "already started" not in str(exc).lower():
                    raise
                logger.info("temporal pilot workflow already started", extra={"workflow_id": workflow_id})
            EVENTS_PROCESSED.labels(settings.service_name, f"{ENRICHED_ALERTS}:temporal", "ok").inc()
            return

        provider_used = await publish_orchestration_event(
            producer=app.state.producer,
            publishers={app.state.message_bus_provider: app.state.producer},
            topic=ORCHESTRATION_EVENTS,
            alert=alert,
            incident=incident,
            decision=decision.__dict__,
            deployment_provider=app.state.message_bus_provider,
        )
        EVENTS_PROCESSED.labels(settings.service_name, f"{ENRICHED_ALERTS}:{provider_used}", "ok").inc()
        # The normal path is event-driven:
        # orchestration-events -> context-agent -> context-events -> resolution-agent.
        # Running the same work inline as well duplicates context retrieval, model
        # calls, persistence records, and downstream approval messages.
        if ORCHESTRATOR_INLINE_RESOLUTION_ENABLED:
            try:
                await _run_resolution_and_publish(
                    app,
                    alert=alert,
                    incident=incident,
                    decision_dict=decision.__dict__,
                )
            except Exception:
                logger.exception(
                    "inline resolution fallback failed for incident=%s; event-driven processing remains active",
                    incident.id,
                )
            else:
                EVENTS_PROCESSED.labels(settings.service_name, RESOLUTION_EVENTS, "ok").inc()

    for source, consumer, consume_forever in _build_ingress_consumers():
        task = asyncio.create_task(consume_forever(consumer, handle), name=f"orchestrator-{source}-consumer")
        tasks.append(task)


async def shutdown(app: FastAPI) -> None:
    for task in tasks:
        task.cancel()


app = create_app(title="KaiMS Orchestrator", settings=settings, startup=startup, shutdown=shutdown)


def _temporal_handle(incident_id: str):
    client = getattr(app.state, "temporal_client", None)
    if not settings.temporal_pilot_enabled or client is None:
        raise HTTPException(status_code=503, detail="Temporal pilot is not enabled")
    return client.get_workflow_handle(f"kaiops-incident-{incident_id}")


@app.post("/temporal/workflows/{incident_id}/approval")
async def signal_temporal_approval(incident_id: str, payload: dict) -> dict:
    await _temporal_handle(incident_id).signal("approval", payload)
    return {"signaled": True, "incident_id": incident_id}


@app.post("/temporal/workflows/{incident_id}/cancel")
async def signal_temporal_cancel(incident_id: str, payload: dict | None = None) -> dict:
    await _temporal_handle(incident_id).signal("cancel", str((payload or {}).get("reason") or "operator requested cancellation"))
    return {"signaled": True, "incident_id": incident_id}


@app.get("/temporal/workflows/{incident_id}/status")
async def query_temporal_status(incident_id: str) -> dict:
    return await _temporal_handle(incident_id).query("status")


@app.post("/decide")
async def decide(payload: dict) -> dict:
    alert = Alert.model_validate(payload["alert"])
    incident = Incident.model_validate(payload["incident"])
    return (await agent.decide_workflow_async_with_runtime(alert, incident)).__dict__
