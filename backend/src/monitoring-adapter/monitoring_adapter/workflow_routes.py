from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Body, Header

RunWorkflow = Callable[..., Awaitable[dict[str, Any]]]
ContinueWorkflow = Callable[..., Awaitable[dict[str, Any]]]
REQUEST_BODY = Body(default={})


def build_workflow_router(
    *,
    run_workflow: RunWorkflow,
    continue_workflow: ContinueWorkflow,
) -> APIRouter:
    """Compose demo workflow transport routes around the workflow application API."""
    router = APIRouter(prefix="/sample", tags=["workflow-simulation"])

    @router.post("/payment-latency/workflow")
    async def payment_latency(
        fast_mode: bool = False,
        x_trace_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        return await run_workflow(
            trace_id=x_trace_id,
            run_comparison=not fast_mode,
            auto_approve=False,
        )

    @router.post("/{flow_id}/workflow")
    async def start(
        flow_id: str,
        fast_mode: bool = False,
        x_trace_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        return await run_workflow(
            trace_id=x_trace_id,
            flow_id=flow_id,
            run_comparison=not fast_mode,
            auto_approve=False,
        )

    @router.post("/{flow_id}/workflow/continue")
    async def resume(
        flow_id: str,
        payload: dict[str, Any] = REQUEST_BODY,
        x_trace_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        return await continue_workflow(
            flow_id=flow_id,
            incident_id=str(payload.get("incident_id") or ""),
            recommendation_id=str(payload.get("recommendation_id") or ""),
            decision_token=str(payload.get("decision") or ""),
            approver=str(payload.get("approver") or "").strip() or None,
            channel=str(payload.get("channel") or "").strip() or None,
            comment=str(payload.get("comment") or "").strip() or None,
            modified_action=str(payload.get("modified_action") or "").strip() or None,
            trace_id=x_trace_id,
        )

    return router
