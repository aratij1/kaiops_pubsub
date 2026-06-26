from __future__ import annotations

from typing import Any, Callable

from session_controller import apply_workflow_payload


RequestJsonFn = Callable[..., dict[str, Any]]
DataFromGatewayFn = Callable[[dict[str, Any]], dict[str, Any]]


def fetch_guidance_matches(
    query: str,
    *,
    gateway_base: str,
    request_json: RequestJsonFn,
    data_from_gateway: DataFromGatewayFn,
    limit: int = 5,
) -> list[dict[str, Any]]:
    guidance_query = (query or "").strip()
    if not guidance_query:
        return []

    response = request_json(
        "GET",
        f"{gateway_base}/rag/search",
        params={"query": guidance_query, "limit": max(1, int(limit))},
        show_error=False,
    )
    matches = data_from_gateway(response).get("matches", []) if response else []
    return [item for item in matches if isinstance(item, dict)]


def run_selected_flow(
    flow_id: str,
    *,
    gateway_base: str,
    request_json: RequestJsonFn,
    state: Any,
    fast_mode_enabled: bool,
) -> bool:
    selected = str(flow_id or "").strip()
    if not selected:
        return False

    gateway_response = request_json(
        "POST",
        f"{gateway_base}/sample/{selected}/workflow",
        params={"fast_mode": str(fast_mode_enabled).lower()},
    )
    return apply_workflow_payload(state, selected, gateway_response)
