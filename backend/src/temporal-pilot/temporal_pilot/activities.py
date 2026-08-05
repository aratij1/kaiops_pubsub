from __future__ import annotations

from typing import Any
from time import perf_counter

import httpx
from common.config import get_settings
from temporalio import activity
from common.telemetry import WORKFLOW_FAILURES, WORKFLOW_LATENCY
from opentelemetry import trace

settings = get_settings()


async def _post(base: str, path: str, payload: dict[str, Any], params: dict[str, Any] | None = None) -> dict[str, Any]:
    info = activity.info()
    headers = {"Idempotency-Key": str(info.activity_id)}
    if settings.ai_layer_auth_token:
        headers["Authorization"] = f"Bearer {settings.ai_layer_auth_token}"
    started = perf_counter()
    stage = path.strip("/") or "activity"
    try:
        with trace.get_tracer("kaiops.temporal").start_as_current_span(f"temporal.activity.{stage}") as span:
            span.set_attribute("temporal.workflow.id", info.workflow_id)
            span.set_attribute("temporal.activity.id", info.activity_id)
            async with httpx.AsyncClient(timeout=settings.ai_layer_request_timeout_seconds, headers=headers) as client:
                response = await client.post(f"{base.rstrip('/')}/{path.lstrip('/')}", json=payload, params=params)
                response.raise_for_status()
                data = response.json()
        WORKFLOW_LATENCY.labels("temporal-incident-pilot", stage, "ok").observe(perf_counter() - started)
        return data if isinstance(data, dict) else {"data": data}
    except Exception:
        WORKFLOW_LATENCY.labels("temporal-incident-pilot", stage, "error").observe(perf_counter() - started)
        WORKFLOW_FAILURES.labels("temporal-incident-pilot", stage).inc()
        raise


@activity.defn(name="collect_context")
async def collect_context(payload: dict[str, Any]) -> dict[str, Any]:
    return await _post(settings.context_agent_url, "/collect", payload, {"publish_events": "false"})


@activity.defn(name="resolve_recommendation")
async def resolve_recommendation(context: dict[str, Any]) -> dict[str, Any]:
    return await _post(settings.resolution_agent_url, "/resolve", context, {"publish_events": "false"})


@activity.defn(name="execute_remediation_decision")
async def execute_remediation_decision(approval: dict[str, Any]) -> dict[str, Any]:
    return await _post(settings.remediation_engine_url, "/execute", approval)


@activity.defn(name="request_compensation")
async def request_compensation(payload: dict[str, Any]) -> dict[str, Any]:
    # There is no truthful rollback endpoint yet. This durable hook records that
    # compensation is required without claiming that rollback ran.
    activity.logger.warning("temporal_compensation_required", extra=payload)
    return {"status": "rollback_required", **payload}
