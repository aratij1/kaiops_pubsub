from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import quote, urlencode

import httpx
from fastapi import APIRouter, Body, Header, HTTPException, Query, Request

from api_gateway.copilot import (
    classify_intent,
    compose_assignment_answer,
    compose_capacity_answer,
    compose_forbidden_onboarding_answer,
    compose_onboarding_answer,
    compose_unsupported_answer,
    extract_incident_id,
)
from api_gateway.modules.users.models import SystemRole
from common.authorization import OperationalRole, role_is_allowed

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
    auth_context_from_request: Callable[[Request], Awaitable[Any]] | None = None,
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
        auth = getattr(request.state, "auth", None)
        if auth is None:
            if auth_context_from_request is None:
                raise HTTPException(status_code=500, detail="Gateway authentication resolver is not configured")
            auth = await auth_context_from_request(request)
        return await forward(
            request, "GET", f"/incident/{quote(incident_id, safe='')}", settings.approval_service_url,
            {}, x_trace_id, params={"tenant_id": auth.tenant_id},
        )

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
        auth = getattr(request.state, "auth", None)
        if auth is None:
            # Local/demo middleware intentionally skips global auth state, but
            # tenant-scoped reads still require and can validate the bearer
            # token here just like approval incident reads and mutations do.
            if auth_context_from_request is None:
                raise HTTPException(status_code=500, detail="Gateway authentication resolver is not configured")
            auth = await auth_context_from_request(request)
        return await forward(
            request, "GET", f"/capacity?{urlencode({'tenant_id': auth.tenant_id})}", settings.approval_service_url, {}, x_trace_id, timeout_seconds=8.0
        )

    @router.post("/incidents/{incident_id}/manual-close")
    async def manual_close_incident(
        incident_id: str,
        request: Request,
        payload: dict[str, Any] = REQUEST_BODY,
        x_trace_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        auth = getattr(request.state, "auth", None)
        if auth is None:
            if auth_context_from_request is None:
                raise HTTPException(status_code=500, detail="Gateway authentication resolver is not configured")
            auth = await auth_context_from_request(request)
        allowed_roles = {OperationalRole.ADMIN.value, OperationalRole.HITL_APPROVER.value}
        if not role_is_allowed(auth.role, allowed_roles):
            raise HTTPException(status_code=403, detail="Manual closure requires ADMIN or HITL_APPROVER")
        forbidden_identity_fields = {"closed_by", "actor_id", "actor_role", "tenant_id"}.intersection(payload)
        if forbidden_identity_fields:
            raise HTTPException(
                status_code=422,
                detail=f"Operator identity fields are server-derived: {', '.join(sorted(forbidden_identity_fields))}",
            )
        comment = str(payload.get("comment") or "").strip()
        if len(comment) < 10 or len(comment) > 4000:
            raise HTTPException(status_code=422, detail="Manual closure comment must contain 10 to 4000 characters")
        actor_id = str(auth.email or auth.username or auth.user_id).strip()
        return await forward(
            request, "POST", f"/incidents/{quote(incident_id, safe='')}/manual-close", settings.closure_service_url,
            {
                "comment": comment,
                "actor_id": actor_id,
                "actor_role": auth.role,
                "tenant_id": auth.tenant_id,
                "auth_jti": auth.jwt_id,
            },
            x_trace_id, timeout_seconds=25.0,
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

    @router.post("/remediation/actions/{action_id}/emergency-stop")
    async def remediation_emergency_stop(
        action_id: str,
        request: Request,
        payload: dict[str, Any] = REQUEST_BODY,
        x_trace_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        auth = getattr(request.state, "auth", None)
        if auth is None:
            raise HTTPException(status_code=401, detail="Authenticated operator identity is required")
        stop_payload = {
            "tenant_id": auth.tenant_id,
            "actor": auth.username or auth.email,
            "reason": str(payload.get("reason") or "").strip(),
        }
        return await forward(
            request, "POST", f"/actions/{quote(action_id, safe='')}/emergency-stop",
            settings.remediation_engine_url, stop_payload, x_trace_id, timeout_seconds=30.0,
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
        auth = getattr(request.state, "auth", None)
        if auth is None:
            if auth_context_from_request is None:
                raise HTTPException(status_code=500, detail="Gateway authentication resolver is not configured")
            auth = await auth_context_from_request(request)
        return await forward(
            request,
            "PUT",
            f"/capacity/{username}",
            settings.approval_service_url,
            {**payload, "tenant_id": auth.tenant_id},
            x_trace_id,
            timeout_seconds=8.0,
        )

    @router.get("/approval/assignments")
    async def get_approval_assignments(
        request: Request, x_trace_id: str | None = Header(default=None)
    ) -> dict[str, Any]:
        auth = getattr(request.state, "auth", None)
        if auth is None:
            raise HTTPException(status_code=401, detail="Authenticated tenant identity is required")
        return await forward(
            request, "GET", f"/assignments?{urlencode({'tenant_id': auth.tenant_id})}", settings.approval_service_url, {}, x_trace_id, timeout_seconds=8.0
        )

    @router.post("/approval/auto-assign")
    async def post_approval_auto_assign(
        request: Request, payload: dict[str, Any] = REQUEST_BODY, x_trace_id: str | None = Header(default=None)
    ) -> dict[str, Any]:
        auth = getattr(request.state, "auth", None)
        if auth is None:
            raise HTTPException(status_code=401, detail="Authenticated tenant identity is required")
        return await forward(
            request, "POST", "/auto-assign", settings.approval_service_url, {**payload, "tenant_id": auth.tenant_id}, x_trace_id, timeout_seconds=12.0
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
