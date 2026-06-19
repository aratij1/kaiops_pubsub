from __future__ import annotations

import asyncio
from collections import deque
from time import perf_counter
from typing import Any
from urllib.parse import urlencode
from uuid import uuid4

import httpx
from api_gateway import SafetyAnalyzer
from common.config import get_settings
from common.kafka import normalize_payload
from common.models import GatewayAuditEvent, SafetyDecision
from common.service import create_app
from common.telemetry import REQUEST_LATENCY
from fastapi import Body, Header, HTTPException, Request
from opentelemetry import trace
from prometheus_client import Counter

REQUEST_BODY = Body(default={})

settings = get_settings()
settings.service_name = "api-gateway"
app = create_app(title="KaiOps API Gateway", settings=settings)
analyzer = SafetyAnalyzer()
AUDIT_EVENTS: deque[GatewayAuditEvent] = deque(maxlen=200)

GATEWAY_REQUESTS = Counter(
    "kaiops_gateway_requests_total",
    "API gateway requests by path and safety decision",
    ["path", "decision", "status"],
)
GATEWAY_SAFETY_BLOCKS = Counter(
    "kaiops_gateway_safety_blocks_total",
    "API gateway blocked requests by category",
    ["category"],
)


def trace_id_from_header(value: str | None) -> str:
    return value or uuid4().hex


def preview(payload: Any) -> dict[str, Any]:
    normalized = normalize_payload(payload)
    if not isinstance(normalized, dict):
        return {"value": str(normalized)[:500]}
    return {key: normalized[key] for key in list(normalized)[:10]}


async def proxy(
    *,
    method: str,
    path: str,
    target_base: str,
    payload: Any,
    trace_id: str,
) -> tuple[int, dict[str, Any]]:
    target_url = f"{target_base.rstrip('/')}/{path.lstrip('/')}"
    headers = {"x-trace-id": trace_id}
    last_error: Exception | None = None
    timeout = httpx.Timeout(settings.gateway_request_timeout_seconds, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for attempt in range(1, 6):
            try:
                response = await client.request(method, target_url, json=payload or None, headers=headers)
                response.raise_for_status()
                return response.status_code, response.json()
            except httpx.HTTPStatusError:
                raise
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt == 5:
                    break
                await asyncio.sleep(0.5 * attempt)
    assert last_error is not None
    raise last_error


async def guarded_proxy(
    *,
    request: Request,
    method: str,
    path: str,
    target_base: str,
    payload: Any,
    trace_id: str,
) -> dict[str, Any]:
    start = perf_counter()
    safety = analyzer.analyze({"path": path, "payload": payload})
    target_url = f"{target_base.rstrip('/')}/{path.lstrip('/')}"
    tracer = trace.get_tracer("kaiops.api_gateway")

    with tracer.start_as_current_span("api_gateway.guarded_proxy") as span:
        span.set_attribute("kaiops.trace_id", trace_id)
        span.set_attribute("kaiops.gateway.path", path)
        span.set_attribute("kaiops.gateway.safety_decision", safety.decision.value)
        span.set_attribute("kaiops.gateway.safety_score", safety.score)

        if safety.decision == SafetyDecision.BLOCK:
            for category in safety.categories or ["unknown"]:
                GATEWAY_SAFETY_BLOCKS.labels(category).inc()
            latency_ms = (perf_counter() - start) * 1000
            event = GatewayAuditEvent(
                trace_id=trace_id,
                method=method,
                path=str(request.url.path),
                target_url=target_url,
                status_code=403,
                latency_ms=latency_ms,
                safety=safety,
                request_preview=preview(payload),
            )
            AUDIT_EVENTS.appendleft(event)
            GATEWAY_REQUESTS.labels(path, safety.decision.value, "blocked").inc()
            REQUEST_LATENCY.labels(settings.service_name, path).observe(latency_ms / 1000)
            raise HTTPException(
                status_code=403,
                detail={
                    "message": "Request blocked by API Gateway safety policy",
                    "trace_id": trace_id,
                    "safety": safety.model_dump(mode="json"),
                },
            )

        try:
            status_code, response_payload = await proxy(
                method=method,
                path=path,
                target_base=target_base,
                payload=payload,
                trace_id=trace_id,
            )
            status = "ok"
        except httpx.HTTPError as exc:
            status_code = 502
            response_payload = {
                "error": str(exc),
                "trace_id": trace_id,
                "target_url": target_url,
                "hint": "Confirm the downstream service is running and has the requested route.",
            }
            status = "error"

        latency_ms = (perf_counter() - start) * 1000
        wrapped = {
            "trace_id": trace_id,
            "gateway": {
                "path": str(request.url.path),
                "target_url": target_url,
                "safety": safety.model_dump(mode="json"),
                "latency_ms": round(latency_ms, 2),
            },
            "data": response_payload,
        }
        event = GatewayAuditEvent(
            trace_id=trace_id,
            method=method,
            path=str(request.url.path),
            target_url=target_url,
            status_code=status_code,
            latency_ms=latency_ms,
            safety=safety,
            request_preview=preview(payload),
            response_preview=preview(response_payload),
        )
        AUDIT_EVENTS.appendleft(event)
        GATEWAY_REQUESTS.labels(path, safety.decision.value, status).inc()
        REQUEST_LATENCY.labels(settings.service_name, path).observe(latency_ms / 1000)

        if status_code >= 400:
            raise HTTPException(status_code=status_code, detail=wrapped)
        return wrapped


@app.post("/alerts")
async def ingest_alert(
    request: Request,
    payload: dict[str, Any] = REQUEST_BODY,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="POST",
        path="/alerts",
        target_base=settings.monitoring_adapter_url,
        payload=payload,
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.post("/sample/payment-latency")
async def sample_payment_latency(
    request: Request,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="POST",
        path="/sample/payment-latency",
        target_base=settings.monitoring_adapter_url,
        payload={},
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.post("/sample/payment-latency/workflow")
async def sample_payment_latency_workflow(
    request: Request,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="POST",
        path="/sample/payment-latency/workflow",
        target_base=settings.monitoring_adapter_url,
        payload={},
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.get("/sample/flows")
async def sample_flows(
    request: Request,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="GET",
        path="/sample/flows",
        target_base=settings.monitoring_adapter_url,
        payload={},
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.post("/sample/{flow_id}/workflow")
async def sample_flow_workflow(
    flow_id: str,
    request: Request,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="POST",
        path=f"/sample/{flow_id}/workflow",
        target_base=settings.monitoring_adapter_url,
        payload={},
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.post("/approval/{action}")
async def approval_action(
    action: str,
    request: Request,
    payload: dict[str, Any] = REQUEST_BODY,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    if action not in {"approve", "reject", "modify"}:
        raise HTTPException(status_code=404, detail="unknown approval action")
    return await guarded_proxy(
        request=request,
        method="POST",
        path=f"/{action}",
        target_base=settings.approval_service_url,
        payload=payload,
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.post("/rag/documents")
async def ingest_rag_document(
    request: Request,
    payload: dict[str, Any] = REQUEST_BODY,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="POST",
        path="/rag/documents",
        target_base=settings.context_agent_url,
        payload=payload,
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.get("/rag/documents")
async def list_rag_documents(
    request: Request,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="GET",
        path="/rag/documents",
        target_base=settings.context_agent_url,
        payload={},
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.post("/rag/reload")
async def reload_rag(
    request: Request,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="POST",
        path="/rag/reload",
        target_base=settings.context_agent_url,
        payload={},
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.get("/rag/search")
async def search_rag(
    query: str,
    request: Request,
    limit: int = 8,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    query_string = urlencode({"query": query, "limit": limit})
    return await guarded_proxy(
        request=request,
        method="GET",
        path=f"/rag/search?{query_string}",
        target_base=settings.context_agent_url,
        payload={},
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.get("/approval/incident/{incident_id}")
async def get_incident(
    incident_id: str,
    request: Request,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="GET",
        path=f"/incident/{incident_id}",
        target_base=settings.approval_service_url,
        payload={},
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.post("/security/check")
async def security_check(payload: dict[str, Any] = REQUEST_BODY) -> dict[str, Any]:
    safety = analyzer.analyze(payload)
    return {"safety": safety.model_dump(mode="json")}


@app.get("/observability/recent")
async def recent_events(limit: int = 25) -> dict[str, Any]:
    events = list(AUDIT_EVENTS)[: max(1, min(limit, 100))]
    return {"events": [event.model_dump(mode="json") for event in events]}


@app.get("/observability/summary")
async def observability_summary() -> dict[str, Any]:
    events = list(AUDIT_EVENTS)
    blocked = sum(1 for event in events if event.safety.decision == SafetyDecision.BLOCK)
    review = sum(1 for event in events if event.safety.decision == SafetyDecision.REVIEW)
    allowed = sum(1 for event in events if event.safety.decision == SafetyDecision.ALLOW)
    return {
        "total_events": len(events),
        "allowed": allowed,
        "review": review,
        "blocked": blocked,
        "latest_trace_id": events[0].trace_id if events else None,
    }
