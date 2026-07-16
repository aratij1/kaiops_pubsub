from __future__ import annotations

import asyncio
from collections import deque
import logging
from time import perf_counter
from typing import Any
from urllib.parse import urlencode
from uuid import uuid4

import httpx
import pymysql
from api_gateway import SafetyAnalyzer
from api_gateway.modules.users.router import router as user_management_router
from api_gateway.modules.users.service import UserService
from common.config import get_settings
from common.database import AuditLogRecord
from common.event_publishers import build_agent_event_contract
from common.kafka import normalize_payload
from common.models import GatewayAuditEvent, SafetyDecision
from common.service import create_app
from common.telemetry import REQUEST_LATENCY
from fastapi import Body, Header, HTTPException, Request
from opentelemetry import trace
from prometheus_client import Counter, Gauge
from sqlalchemy import func, select

REQUEST_BODY = Body(default={})

settings = get_settings()
settings.service_name = "api-gateway"
analyzer = SafetyAnalyzer()
AUDIT_EVENTS: deque[GatewayAuditEvent] = deque(maxlen=200)
logger = logging.getLogger("api-gateway")


async def _persist_gateway_audit_event(app: FastAPI, event: GatewayAuditEvent) -> None:
    session_factory = getattr(app.state, "session_factory", None)
    if not settings.database_enabled or session_factory is None:
        return
    payload = event.model_dump(mode="json")
    async with session_factory() as session:
        session.add(
            AuditLogRecord(
                id=event.id,
                actor="api-gateway",
                action="gateway.request",
                resource_type="gateway",
                resource_id=str(event.trace_id or event.id),
                payload=payload,
            )
        )
        await session.commit()


def _gateway_event_from_audit_payload(payload: dict[str, Any]) -> GatewayAuditEvent | None:
    if not isinstance(payload, dict):
        return None
    try:
        return GatewayAuditEvent.model_validate(payload)
    except Exception:
        return None


async def _load_recent_gateway_audit_events(app: FastAPI, limit: int) -> list[GatewayAuditEvent]:
    session_factory = getattr(app.state, "session_factory", None)
    safe_limit = max(1, min(int(limit), 100))
    if not settings.database_enabled or session_factory is None:
        return list(AUDIT_EVENTS)[:safe_limit]
    async with session_factory() as session:
        result = await session.execute(
            select(AuditLogRecord)
            .where(AuditLogRecord.resource_type == "gateway")
            .where(AuditLogRecord.action == "gateway.request")
            .order_by(AuditLogRecord.created_at.desc())
            .limit(safe_limit)
        )
        rows = result.scalars().all()
    events = [_gateway_event_from_audit_payload(row.payload or {}) for row in rows]
    return [event for event in events if event is not None]


async def _load_gateway_audit_summary(app: FastAPI) -> dict[str, Any]:
    session_factory = getattr(app.state, "session_factory", None)
    if not settings.database_enabled or session_factory is None:
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

    recent_events = await _load_recent_gateway_audit_events(app, 250)
    async with session_factory() as session:
        total = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(AuditLogRecord)
                    .where(AuditLogRecord.resource_type == "gateway")
                    .where(AuditLogRecord.action == "gateway.request")
                )
            ).scalar_one()
        )
    blocked = sum(1 for event in recent_events if event.safety.decision == SafetyDecision.BLOCK)
    review = sum(1 for event in recent_events if event.safety.decision == SafetyDecision.REVIEW)
    allowed = sum(1 for event in recent_events if event.safety.decision == SafetyDecision.ALLOW)
    latest_event = recent_events[0] if recent_events else None
    return {
        "total_events": total,
        "window_events": len(recent_events),
        "allowed": allowed,
        "review": review,
        "blocked": blocked,
        "latest_trace_id": latest_event.trace_id if latest_event else None,
    }


def _query_alerts_table_row_count() -> float:
    if not settings.database_enabled:
        return 0.0
    connection = None
    try:
        connection = pymysql.connect(
            host=settings.db_host,
            port=int(settings.db_port),
            user=settings.db_user,
            password=settings.db_password,
            database=settings.db_database,
            connect_timeout=3,
            read_timeout=3,
            write_timeout=3,
            cursorclass=pymysql.cursors.Cursor,
            autocommit=True,
        )
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM alerts")
            row = cursor.fetchone()
            return float((row or [0])[0] or 0)
    except Exception as exc:
        logger.warning("alerts_table_row_count_query_failed", extra={"error": str(exc)})
        return 0.0
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass


async def startup(app: FastAPI) -> None:
    if settings.database_enabled:
        app.state.user_service = UserService(settings=settings, session_factory=app.state.session_factory)
        await app.state.user_service.bootstrap_defaults()
    else:
        app.state.user_service = UserService(settings=settings, session_factory=None)

    ALERTS_TABLE_ROWS.labels(settings.db_database, "alerts").set_function(_query_alerts_table_row_count)


app = create_app(title="KaiMS API Gateway", settings=settings, startup=startup)
app.include_router(user_management_router)

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
ALERTS_TABLE_ROWS = Gauge(
    "kaiops_mysql_alerts_table_rows",
    "Current number of records in MySQL alerts table",
    ["database", "table"],
)


def trace_id_from_header(value: str | None) -> str:
    return value or uuid4().hex


def preview(payload: Any) -> dict[str, Any]:
    normalized = normalize_payload(payload)
    if not isinstance(normalized, dict):
        return {"value": str(normalized)[:500]}
    return {key: normalized[key] for key in list(normalized)[:10]}


def _build_gateway_audit_contract(event: GatewayAuditEvent) -> dict[str, Any]:
    status_code = int(event.status_code or 0)
    confidence = 1.0 if status_code < 400 else 0.5
    return build_agent_event_contract(
        flow_id=str(event.trace_id or event.id),
        incident_id=str(event.trace_id or event.id),
        trace_id=str(event.trace_id or ""),
        correlation_id=None,
        agent="api-gateway",
        payload={
            "path": event.path,
            "method": event.method,
            "status_code": status_code,
            "decision": event.safety.decision.value,
        },
        metadata={
            "categories": list(event.safety.categories),
            "latency_ms": event.latency_ms,
            "target_url": event.target_url,
        },
        confidence=confidence,
        reasoning="gateway safety and proxy audit event",
        citations=[f"gateway://{event.path}"],
        evidence_ids=[f"gateway-event:{event.id}"],
    )


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
            await _persist_gateway_audit_event(app, event)
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
        except httpx.HTTPStatusError as exc:
            downstream_payload: Any
            try:
                downstream_payload = exc.response.json()
            except Exception:
                downstream_payload = {"message": (exc.response.text or "").strip()}
            status_code = int(exc.response.status_code or 502)
            response_payload = {
                "error": str(exc),
                "trace_id": trace_id,
                "target_url": target_url,
                "downstream": downstream_payload,
                "hint": "Downstream service rejected the request payload.",
            }
            status = "error"
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
        await _persist_gateway_audit_event(app, event)
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


@app.post("/applications")
async def create_application(
    request: Request,
    payload: dict[str, Any] = REQUEST_BODY,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="POST",
        path="/applications",
        target_base=settings.application_onboarding_url,
        payload=payload,
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.get("/applications")
async def list_applications(
    request: Request,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="GET",
        path="/applications",
        target_base=settings.application_onboarding_url,
        payload={},
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.get("/applications/{application_id}")
async def get_application(
    application_id: str,
    request: Request,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="GET",
        path=f"/applications/{application_id}",
        target_base=settings.application_onboarding_url,
        payload={},
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.put("/applications/{application_id}")
async def update_application(
    application_id: str,
    request: Request,
    payload: dict[str, Any] = REQUEST_BODY,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="PUT",
        path=f"/applications/{application_id}",
        target_base=settings.application_onboarding_url,
        payload=payload,
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.delete("/applications/{application_id}")
async def delete_application(
    application_id: str,
    request: Request,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="DELETE",
        path=f"/applications/{application_id}",
        target_base=settings.application_onboarding_url,
        payload={},
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.get("/applications/{application_id}/history")
async def get_application_history(
    application_id: str,
    request: Request,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="GET",
        path=f"/applications/{application_id}/history",
        target_base=settings.application_onboarding_url,
        payload={},
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.get("/applications/{application_id}/validations")
async def get_application_validations(
    application_id: str,
    request: Request,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="GET",
        path=f"/applications/{application_id}/validations",
        target_base=settings.application_onboarding_url,
        payload={},
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.get("/applications/{application_id}/dashboards")
async def get_application_dashboards(
    application_id: str,
    request: Request,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="GET",
        path=f"/applications/{application_id}/dashboards",
        target_base=settings.application_onboarding_url,
        payload={},
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.get("/alerts")
async def alerts_help() -> dict[str, Any]:
    return {
        "message": "Use POST /alerts to ingest alerts. GET /alerts is informational.",
        "example": {
            "method": "POST",
            "path": "/alerts",
            "payload": {
                "source": "monitoring-adapter",
                "name": "DatabaseReplicaLag",
                "service": "orders-db",
                "severity": "high",
                "description": "Replica lag is above threshold.",
                "labels": {"component": "database"},
                "annotations": {"summary": "Database replica lag spike"},
            },
        },
    }


@app.get("/alerts/recent")
async def get_recent_alerts(
    request: Request,
    limit: int = 50,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    path = f"/alerts/recent?{urlencode({'limit': str(limit)})}"
    return await guarded_proxy(
        request=request,
        method="GET",
        path=path,
        target_base=settings.monitoring_adapter_url,
        payload={},
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.get("/alerts/all")
async def get_all_alerts(
    request: Request,
    limit: int = 500,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    path = f"/alerts/all?{urlencode({'limit': str(limit)})}"
    return await guarded_proxy(
        request=request,
        method="GET",
        path=path,
        target_base=settings.monitoring_adapter_url,
        payload={},
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.get("/alerts/severity-overrides")
async def get_alert_severity_overrides(
    request: Request,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="GET",
        path="/alerts/severity-overrides",
        target_base=settings.monitoring_adapter_url,
        payload={},
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.put("/alerts/severity-overrides")
async def put_alert_severity_override(
    request: Request,
    payload: dict[str, Any] = REQUEST_BODY,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="PUT",
        path="/alerts/severity-overrides",
        target_base=settings.monitoring_adapter_url,
        payload=payload,
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.delete("/alerts/severity-overrides")
async def delete_alert_severity_override(
    request: Request,
    name: str,
    service: str = "",
    environment: str = "",
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    path = f"/alerts/severity-overrides?{urlencode({'name': name, 'service': service, 'environment': environment})}"
    return await guarded_proxy(
        request=request,
        method="DELETE",
        path=path,
        target_base=settings.monitoring_adapter_url,
        payload={},
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
    fast_mode: bool = False,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    path = "/sample/payment-latency/workflow"
    if fast_mode:
        path = f"{path}?{urlencode({'fast_mode': 'true'})}"
    return await guarded_proxy(
        request=request,
        method="POST",
        path=path,
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


@app.get("/onboarding/connectivity")
async def get_onboarding_connectivity(
    request: Request,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="GET",
        path="/onboarding/connectivity",
        target_base=settings.monitoring_adapter_url,
        payload={},
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.get("/onboarding/state")
async def get_onboarding_state(
    request: Request,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="GET",
        path="/onboarding/state",
        target_base=settings.monitoring_adapter_url,
        payload={},
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.delete("/onboarding/state/{project_name}")
async def delete_onboarding_state(
    project_name: str,
    request: Request,
    provider_name: str | None = None,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    query_suffix = f"?{urlencode({'provider_name': provider_name})}" if provider_name else ""
    return await guarded_proxy(
        request=request,
        method="DELETE",
        path=f"/onboarding/state/{project_name}{query_suffix}",
        target_base=settings.monitoring_adapter_url,
        payload={},
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.get("/onboarding/rules/capabilities")
async def get_onboarding_rule_capabilities(
    request: Request,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="GET",
        path="/onboarding/rules/capabilities",
        target_base=settings.monitoring_adapter_url,
        payload={},
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.post("/onboarding/rules/pipeline/existing")
async def post_onboarding_rules_pipeline_existing(
    request: Request,
    payload: dict[str, Any] = REQUEST_BODY,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="POST",
        path="/onboarding/rules/pipeline/existing",
        target_base=settings.monitoring_adapter_url,
        payload=payload,
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.post("/onboarding/rules/pipeline/new")
async def post_onboarding_rules_pipeline_new(
    request: Request,
    payload: dict[str, Any] = REQUEST_BODY,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="POST",
        path="/onboarding/rules/pipeline/new",
        target_base=settings.monitoring_adapter_url,
        payload=payload,
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.post("/onboarding/rules/pipeline/create")
async def post_onboarding_rules_pipeline_create_alias(
    request: Request,
    payload: dict[str, Any] = REQUEST_BODY,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    # Backward-compatible alias for clients still using older onboarding route names.
    return await guarded_proxy(
        request=request,
        method="POST",
        path="/onboarding/rules/pipeline/new",
        target_base=settings.monitoring_adapter_url,
        payload=payload,
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.get("/onboarding/rules/pipeline/{workflow_id}")
async def get_onboarding_rules_pipeline(
    workflow_id: str,
    request: Request,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="GET",
        path=f"/onboarding/rules/pipeline/{workflow_id}",
        target_base=settings.monitoring_adapter_url,
        payload={},
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.put("/onboarding/rules/pipeline/{workflow_id}")
async def put_onboarding_rules_pipeline(
    workflow_id: str,
    request: Request,
    payload: dict[str, Any] = REQUEST_BODY,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="PUT",
        path=f"/onboarding/rules/pipeline/{workflow_id}",
        target_base=settings.monitoring_adapter_url,
        payload=payload,
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.delete("/onboarding/rules/pipeline/{workflow_id}")
async def delete_onboarding_rules_pipeline(
    workflow_id: str,
    request: Request,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="DELETE",
        path=f"/onboarding/rules/pipeline/{workflow_id}",
        target_base=settings.monitoring_adapter_url,
        payload={},
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.get("/agent-work/items")
async def get_agent_work_items(
    request: Request,
    limit: int = 100,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    path = f"/agent-work/items?{urlencode({'limit': str(limit)})}"
    return await guarded_proxy(
        request=request,
        method="GET",
        path=path,
        target_base=settings.monitoring_adapter_url,
        payload={},
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.get("/incidents/closed")
async def get_closed_incidents(
    request: Request,
    limit: int = 100,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    path = f"/incidents/closed?{urlencode({'limit': str(limit)})}"
    return await guarded_proxy(
        request=request,
        method="GET",
        path=path,
        target_base=settings.monitoring_adapter_url,
        payload={},
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.get("/incidents/metadata")
async def get_incident_metadata(
    request: Request,
    limit: int = 100,
    risk_tier: str | None = None,
    execution_mode: str | None = None,
    transport_provider: str | None = None,
    status: str | None = None,
    service: str | None = None,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    params: dict[str, str] = {"limit": str(limit)}
    if risk_tier:
        params["risk_tier"] = str(risk_tier)
    if execution_mode:
        params["execution_mode"] = str(execution_mode)
    if transport_provider:
        params["transport_provider"] = str(transport_provider)
    if status:
        params["status"] = str(status)
    if service:
        params["service"] = str(service)
    path = f"/incidents/metadata?{urlencode(params)}"
    return await guarded_proxy(
        request=request,
        method="GET",
        path=path,
        target_base=settings.monitoring_adapter_url,
        payload={},
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.get("/incidents/{incident_id}/stage-completeness")
async def get_incident_stage_completeness(
    incident_id: str,
    request: Request,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    path = f"/incidents/{incident_id}/stage-completeness"
    return await guarded_proxy(
        request=request,
        method="GET",
        path=path,
        target_base=settings.monitoring_adapter_url,
        payload={},
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.get("/landing-pad/recent")
async def get_landing_pad_recent(
    request: Request,
    limit: int = 20,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    path = f"/landing-pad/recent?{urlencode({'limit': str(limit)})}"
    return await guarded_proxy(
        request=request,
        method="GET",
        path=path,
        target_base=settings.monitoring_adapter_url,
        payload={},
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.post("/onboarding/connectivity")
async def post_onboarding_connectivity(
    request: Request,
    payload: dict[str, Any] = REQUEST_BODY,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="POST",
        path="/onboarding/connectivity",
        target_base=settings.monitoring_adapter_url,
        payload=payload,
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.post("/onboarding/complete")
async def post_onboarding_complete(
    request: Request,
    payload: dict[str, Any] = REQUEST_BODY,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="POST",
        path="/onboarding/complete",
        target_base=settings.monitoring_adapter_url,
        payload=payload,
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.get("/monitoring/providers")
async def get_monitoring_providers(
    request: Request,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="GET",
        path="/monitoring/providers",
        target_base=settings.monitoring_adapter_url,
        payload={},
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.get("/monitoring/integrations")
async def get_monitoring_integrations(
    request: Request,
    tenant_id: str = "default",
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    path = f"/monitoring/integrations?{urlencode({'tenant_id': tenant_id})}"
    return await guarded_proxy(
        request=request,
        method="GET",
        path=path,
        target_base=settings.monitoring_adapter_url,
        payload={},
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.post("/monitoring/integrations")
async def post_monitoring_integrations(
    request: Request,
    payload: dict[str, Any] = REQUEST_BODY,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="POST",
        path="/monitoring/integrations",
        target_base=settings.monitoring_adapter_url,
        payload=payload,
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.get("/monitoring/integrations/{integration_id}")
async def get_monitoring_integration(
    integration_id: str,
    request: Request,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="GET",
        path=f"/monitoring/integrations/{integration_id}",
        target_base=settings.monitoring_adapter_url,
        payload={},
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.put("/monitoring/integrations/{integration_id}")
async def put_monitoring_integration(
    integration_id: str,
    request: Request,
    payload: dict[str, Any] = REQUEST_BODY,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="PUT",
        path=f"/monitoring/integrations/{integration_id}",
        target_base=settings.monitoring_adapter_url,
        payload=payload,
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.delete("/monitoring/integrations/{integration_id}")
async def delete_monitoring_integration(
    integration_id: str,
    request: Request,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="DELETE",
        path=f"/monitoring/integrations/{integration_id}",
        target_base=settings.monitoring_adapter_url,
        payload={},
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.post("/monitoring/integrations/{integration_id}/validate")
async def post_monitoring_integration_validate(
    integration_id: str,
    request: Request,
    payload: dict[str, Any] = REQUEST_BODY,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="POST",
        path=f"/monitoring/integrations/{integration_id}/validate",
        target_base=settings.monitoring_adapter_url,
        payload=payload,
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.post("/monitoring/integrations/{integration_id}/discover")
async def post_monitoring_integration_discover(
    integration_id: str,
    request: Request,
    payload: dict[str, Any] = REQUEST_BODY,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="POST",
        path=f"/monitoring/integrations/{integration_id}/discover",
        target_base=settings.monitoring_adapter_url,
        payload=payload,
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.post("/monitoring/integrations/{integration_id}/register-webhook")
async def post_monitoring_integration_register_webhook(
    integration_id: str,
    request: Request,
    payload: dict[str, Any] = REQUEST_BODY,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="POST",
        path=f"/monitoring/integrations/{integration_id}/register-webhook",
        target_base=settings.monitoring_adapter_url,
        payload=payload,
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.get("/monitoring/integrations/{integration_id}/mapping")
async def get_monitoring_integration_mapping(
    integration_id: str,
    request: Request,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="GET",
        path=f"/monitoring/integrations/{integration_id}/mapping",
        target_base=settings.monitoring_adapter_url,
        payload={},
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.put("/monitoring/integrations/{integration_id}/mapping")
async def put_monitoring_integration_mapping(
    integration_id: str,
    request: Request,
    payload: dict[str, Any] = REQUEST_BODY,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="PUT",
        path=f"/monitoring/integrations/{integration_id}/mapping",
        target_base=settings.monitoring_adapter_url,
        payload=payload,
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.post("/monitoring/integrations/{integration_id}/test-alert")
async def post_monitoring_integration_test_alert(
    integration_id: str,
    request: Request,
    payload: dict[str, Any] = REQUEST_BODY,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="POST",
        path=f"/monitoring/integrations/{integration_id}/test-alert",
        target_base=settings.monitoring_adapter_url,
        payload=payload,
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.post("/monitoring/integrations/{integration_id}/activate")
async def post_monitoring_integration_activate(
    integration_id: str,
    request: Request,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="POST",
        path=f"/monitoring/integrations/{integration_id}/activate",
        target_base=settings.monitoring_adapter_url,
        payload={},
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.post("/monitoring/integrations/{integration_id}/deactivate")
async def post_monitoring_integration_deactivate(
    integration_id: str,
    request: Request,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="POST",
        path=f"/monitoring/integrations/{integration_id}/deactivate",
        target_base=settings.monitoring_adapter_url,
        payload={},
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.get("/monitoring/health")
async def get_monitoring_health(
    request: Request,
    tenant_id: str = "default",
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    path = f"/monitoring/health?{urlencode({'tenant_id': tenant_id})}"
    return await guarded_proxy(
        request=request,
        method="GET",
        path=path,
        target_base=settings.monitoring_adapter_url,
        payload={},
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.get("/monitoring/audit")
async def get_monitoring_audit(
    request: Request,
    tenant_id: str = "default",
    limit: int = 100,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    path = f"/monitoring/audit?{urlencode({'tenant_id': tenant_id, 'limit': str(limit)})}"
    return await guarded_proxy(
        request=request,
        method="GET",
        path=path,
        target_base=settings.monitoring_adapter_url,
        payload={},
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.post("/api/v1/alerts/prometheus")
async def post_provider_prometheus_alert(
    request: Request,
    payload: dict[str, Any] = REQUEST_BODY,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="POST",
        path="/api/v1/alerts/prometheus",
        target_base=settings.monitoring_adapter_url,
        payload=payload,
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.post("/api/v1/alerts/datadog")
async def post_provider_datadog_alert(
    request: Request,
    payload: dict[str, Any] = REQUEST_BODY,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="POST",
        path="/api/v1/alerts/datadog",
        target_base=settings.monitoring_adapter_url,
        payload=payload,
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.post("/api/v1/alerts/newrelic")
async def post_provider_newrelic_alert(
    request: Request,
    payload: dict[str, Any] = REQUEST_BODY,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="POST",
        path="/api/v1/alerts/newrelic",
        target_base=settings.monitoring_adapter_url,
        payload=payload,
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.post("/api/v1/alerts/dynatrace")
async def post_provider_dynatrace_alert(
    request: Request,
    payload: dict[str, Any] = REQUEST_BODY,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="POST",
        path="/api/v1/alerts/dynatrace",
        target_base=settings.monitoring_adapter_url,
        payload=payload,
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.post("/api/v1/alerts/azure-monitor")
async def post_provider_azure_monitor_alert(
    request: Request,
    payload: dict[str, Any] = REQUEST_BODY,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="POST",
        path="/api/v1/alerts/azure-monitor",
        target_base=settings.monitoring_adapter_url,
        payload=payload,
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.post("/api/v1/alerts/splunk")
async def post_provider_splunk_alert(
    request: Request,
    payload: dict[str, Any] = REQUEST_BODY,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="POST",
        path="/api/v1/alerts/splunk",
        target_base=settings.monitoring_adapter_url,
        payload=payload,
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.post("/api/v1/alerts/generic")
async def post_provider_generic_alert(
    request: Request,
    provider: str = "prometheus",
    payload: dict[str, Any] = REQUEST_BODY,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    path = f"/api/v1/alerts/generic?{urlencode({'provider': provider})}"
    return await guarded_proxy(
        request=request,
        method="POST",
        path=path,
        target_base=settings.monitoring_adapter_url,
        payload=payload,
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.post("/sample/{flow_id}/workflow")
async def sample_flow_workflow(
    flow_id: str,
    request: Request,
    fast_mode: bool = False,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    path = f"/sample/{flow_id}/workflow"
    if fast_mode:
        path = f"{path}?{urlencode({'fast_mode': 'true'})}"
    return await guarded_proxy(
        request=request,
        method="POST",
        path=path,
        target_base=settings.monitoring_adapter_url,
        payload={},
        trace_id=trace_id_from_header(x_trace_id),
    )


@app.post("/sample/{flow_id}/workflow/continue")
async def continue_sample_flow_workflow(
    flow_id: str,
    request: Request,
    payload: dict[str, Any] = REQUEST_BODY,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="POST",
        path=f"/sample/{flow_id}/workflow/continue",
        target_base=settings.monitoring_adapter_url,
        payload=payload,
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


@app.put("/rag/documents")
async def update_rag_document(
    request: Request,
    payload: dict[str, Any] = REQUEST_BODY,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="PUT",
        path="/rag/documents",
        target_base=settings.context_agent_url,
        payload=payload,
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


@app.get("/rag/flow-catalog")
async def flow_catalog(
    request: Request,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await guarded_proxy(
        request=request,
        method="GET",
        path="/rag/flow-catalog",
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
    events = await _load_recent_gateway_audit_events(app, limit)
    response_rows: list[dict[str, Any]] = []
    for event in events:
        row = event.model_dump(mode="json")
        row["event_contract"] = _build_gateway_audit_contract(event)
        response_rows.append(row)
    return {"events": response_rows}


@app.get("/observability/summary")
async def observability_summary() -> dict[str, Any]:
    return await _load_gateway_audit_summary(app)
