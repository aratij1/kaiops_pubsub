from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import quote, urlencode

import httpx
from fastapi import APIRouter, Body, Header, HTTPException, Query, Request

from api_gateway.copilot import (
    classify_intent,
    compose_approval_status_answer,
    compose_assignment_answer,
    compose_capacity_answer,
    compose_forbidden_onboarding_answer,
    compose_incident_summary_answer,
    compose_onboarding_answer,
    compose_rca_answer,
    compose_unsupported_answer,
    extract_incident_id,
)
from api_gateway.modules.users.models import SystemRole

GuardedProxy = Callable[..., Awaitable[dict[str, Any]]]
RawProxy = Callable[..., Awaitable[tuple[int, dict[str, Any]]]]
REQUEST_BODY = Body(default={})


def build_control_router(
    *,
    settings: Any,
    guarded_proxy: GuardedProxy,
    raw_proxy: RawProxy,
    trace_id_from_header: Callable[[str | None], str],
    analyzer: Any,
    load_recent_events: Callable[[int], Awaitable[list[Any]]],
    build_audit_contract: Callable[[Any], dict[str, Any]],
    load_audit_summary: Callable[[], Awaitable[dict[str, Any]]],
) -> APIRouter:
    """Gateway control routes with dependencies injected by the composition root."""
    router = APIRouter()

    async def forward(
        request: Request,
        method: str,
        path: str,
        target: str,
        payload: dict[str, Any],
        trace: str | None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return await guarded_proxy(
            request=request,
            method=method,
            path=path,
            target_base=target,
            payload=payload,
            trace_id=trace_id_from_header(trace),
            **kwargs,
        )

    async def fetch_rows(path: str, target: str, trace_id: str) -> list[dict[str, Any]]:
        _, response = await raw_proxy(
            method="GET",
            path=path,
            target_base=target,
            payload={},
            trace_id=trace_id,
        )
        rows = response.get("rows", []) if isinstance(response, dict) else []
        return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []

    async def fetch_object(path: str, target: str, trace_id: str) -> dict[str, Any] | None:
        _, response = await raw_proxy(
            method="GET",
            path=path,
            target_base=target,
            payload={},
            trace_id=trace_id,
        )
        return response if isinstance(response, dict) else None

    @router.post("/model/route")
    async def model_route(
        request: Request, payload: dict[str, Any] = REQUEST_BODY, x_trace_id: str | None = Header(default=None)
    ) -> dict[str, Any]:
        return await forward(request, "POST", "/route", settings.model_router_url, payload, x_trace_id)

    @router.post("/model/route/provider/{provider_name}")
    async def model_route_provider(
        provider_name: str,
        request: Request,
        payload: dict[str, Any] = REQUEST_BODY,
        x_trace_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        return await forward(
            request, "POST", f"/route/provider/{provider_name}", settings.model_router_url, payload, x_trace_id
        )

    @router.get("/model/providers/status")
    async def model_providers_status(request: Request, x_trace_id: str | None = Header(default=None)) -> dict[str, Any]:
        return await forward(request, "GET", "/providers/status", settings.model_router_url, {}, x_trace_id)

    @router.get("/approval/incident/{incident_id}")
    async def get_incident(
        incident_id: str, request: Request, x_trace_id: str | None = Header(default=None)
    ) -> dict[str, Any]:
        return await forward(request, "GET", f"/incident/{incident_id}", settings.approval_service_url, {}, x_trace_id)

    @router.get("/knowledge-graph")
    async def get_knowledge_graph(request: Request, x_trace_id: str | None = Header(default=None)) -> dict[str, Any]:
        return await forward(request, "GET", "/knowledge-graph", settings.context_agent_url, {}, x_trace_id)

    @router.get("/knowledge-graph/context")
    async def get_knowledge_graph_context(
        request: Request,
        service: str,
        depth: int = Query(default=2, ge=1, le=5),
        limit: int = Query(default=80, ge=1, le=250),
        x_trace_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        return await forward(
            request,
            "GET",
            "/knowledge-graph/context",
            settings.context_agent_url,
            {},
            x_trace_id,
            params={"service": service, "depth": depth, "limit": limit},
        )

    @router.get("/context/strategy")
    async def get_context_strategy(
        request: Request,
        x_trace_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        return await forward(request, "GET", "/context/strategy", settings.context_agent_url, {}, x_trace_id)

    @router.get("/context/snapshots/{incident_id}")
    async def get_context_snapshot(
        incident_id: str,
        request: Request,
        tenant_id: str = Query(default="default", min_length=1, max_length=128),
        x_trace_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        return await forward(
            request,
            "GET",
            f"/context/snapshots/{quote(incident_id, safe='')}",
            settings.context_agent_url,
            {},
            x_trace_id,
            params={"tenant_id": tenant_id},
        )

    @router.get("/approval/capacity")
    async def get_approval_capacity(request: Request, x_trace_id: str | None = Header(default=None)) -> dict[str, Any]:
        return await forward(
            request, "GET", "/capacity", settings.approval_service_url, {}, x_trace_id, timeout_seconds=8.0
        )

    @router.post("/incidents/{incident_id}/manual-close")
    async def manual_close_incident(
        incident_id: str,
        request: Request,
        payload: dict[str, Any] = REQUEST_BODY,
        x_trace_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        return await forward(
            request, "POST", f"/incidents/{incident_id}/manual-close", settings.closure_service_url,
            payload, x_trace_id, timeout_seconds=25.0,
        )

    @router.post("/remediation/execute")
    async def remediation_execute(
        request: Request,
        payload: dict[str, Any] = REQUEST_BODY,
        x_trace_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        return await forward(
            request, "POST", "/execute", settings.remediation_engine_url,
            payload, x_trace_id, timeout_seconds=1000.0,
        )

    @router.post("/remediation/dry-run")
    async def remediation_dry_run(
        request: Request,
        payload: dict[str, Any] = REQUEST_BODY,
        x_trace_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        return await forward(request, "POST", "/dry-run", settings.remediation_engine_url, payload, x_trace_id)

    @router.post("/remediation/diagnostic/complete")
    async def remediation_diagnostic_complete(
        request: Request,
        payload: dict[str, Any] = REQUEST_BODY,
        x_trace_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        return await forward(
            request, "POST", "/diagnostic/complete", settings.remediation_engine_url,
            payload, x_trace_id, timeout_seconds=60.0,
        )

    @router.get("/remediation/actions/by-incident/{incident_id}/latest")
    async def remediation_latest_action(
        incident_id: str,
        request: Request,
        x_trace_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        return await forward(
            request, "GET", f"/actions/by-incident/{quote(incident_id, safe='')}/latest",
            settings.remediation_engine_url, {}, x_trace_id, timeout_seconds=30.0,
        )

    @router.get("/remediation/reconciliation/terminal-actions")
    async def remediation_reconciliation_preview(
        request: Request,
        limit: int = Query(default=100, ge=1, le=1000),
        x_trace_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        return await forward(
            request,
            "GET",
            f"/reconciliation/terminal-actions?{urlencode({'limit': str(limit)})}",
            settings.closure_service_url,
            {},
            x_trace_id,
            timeout_seconds=30.0,
        )

    @router.put("/approval/capacity/{username}")
    async def put_approval_capacity(
        username: str,
        request: Request,
        payload: dict[str, Any] = REQUEST_BODY,
        x_trace_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        return await forward(
            request,
            "PUT",
            f"/capacity/{username}",
            settings.approval_service_url,
            payload,
            x_trace_id,
            timeout_seconds=8.0,
        )

    @router.get("/approval/assignments")
    async def get_approval_assignments(
        request: Request, x_trace_id: str | None = Header(default=None)
    ) -> dict[str, Any]:
        return await forward(
            request, "GET", "/assignments", settings.approval_service_url, {}, x_trace_id, timeout_seconds=8.0
        )

    @router.post("/approval/auto-assign")
    async def post_approval_auto_assign(
        request: Request, payload: dict[str, Any] = REQUEST_BODY, x_trace_id: str | None = Header(default=None)
    ) -> dict[str, Any]:
        return await forward(
            request, "POST", "/auto-assign", settings.approval_service_url, payload, x_trace_id, timeout_seconds=12.0
        )

    @router.post("/copilot/query")
    async def post_copilot_query(
        request: Request, payload: dict[str, Any] = REQUEST_BODY, x_trace_id: str | None = Header(default=None)
    ) -> dict[str, Any]:
        query = str(payload.get("query") or "").strip()
        trace_id = trace_id_from_header(x_trace_id)
        if not query:
            raise HTTPException(status_code=422, detail="query is required")
        intent = classify_intent(query)
        auth = getattr(request.state, "auth", None)
        try:
            if intent == "onboarding":
                if auth is not None and auth.role != SystemRole.ADMINISTRATOR.value:
                    result = compose_forbidden_onboarding_answer()
                else:
                    result = compose_onboarding_answer(
                        await fetch_rows("/onboarding/state", settings.monitoring_adapter_url, trace_id)
                    )
            elif intent == "capacity":
                result = compose_capacity_answer(await fetch_rows("/capacity", settings.approval_service_url, trace_id))
            elif intent == "assignment":
                result = compose_assignment_answer(
                    await fetch_rows("/assignments", settings.approval_service_url, trace_id),
                    extract_incident_id(query),
                )
            elif intent == "rca":
                incident_id = extract_incident_id(query)
                was_auto_selected = False
                if not incident_id:
                    candidates = await fetch_rows(
                        "/incidents/lowest-confidence-recommendations",
                        settings.monitoring_adapter_url,
                        trace_id,
                    )
                    if candidates:
                        incident_id = str(candidates[0].get("incident_id") or "") or None
                        was_auto_selected = True
                incident = (
                    await fetch_object(f"/incident/{incident_id}", settings.approval_service_url, trace_id)
                    if incident_id
                    else None
                )
                result = compose_rca_answer(incident, incident_id, was_auto_selected=was_auto_selected)
            elif intent == "approval_status":
                incident_id = extract_incident_id(query)
                incident = (
                    await fetch_object(f"/incident/{incident_id}", settings.approval_service_url, trace_id)
                    if incident_id
                    else None
                )
                result = compose_approval_status_answer(incident, incident_id)
            elif intent == "incident_summary":
                result = compose_incident_summary_answer(
                    await fetch_rows("/incidents/metadata", settings.monitoring_adapter_url, trace_id)
                )
            else:
                result = compose_unsupported_answer(query)
        except httpx.HTTPError:
            result = {
                "intent": intent,
                "answer": "I couldn't reach the service that has this data right now. Please try again shortly.",
                "data": {},
                "links": [],
            }
        return {"trace_id": trace_id, **result}

    @router.post("/security/check")
    async def security_check(payload: dict[str, Any] = REQUEST_BODY) -> dict[str, Any]:
        return {"safety": analyzer.analyze(payload).model_dump(mode="json")}

    @router.get("/observability/recent")
    async def recent_events(limit: int = Query(default=25, ge=1, le=250)) -> dict[str, Any]:
        rows = []
        for event in await load_recent_events(limit):
            row = event.model_dump(mode="json")
            row["event_contract"] = build_audit_contract(event)
            rows.append(row)
        return {"events": rows}

    @router.get("/observability/summary")
    async def observability_summary() -> dict[str, Any]:
        return await load_audit_summary()

    return router
