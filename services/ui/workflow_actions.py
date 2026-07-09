from __future__ import annotations

import os
from typing import Any, Callable

from session_controller import apply_workflow_payload


RequestJsonFn = Callable[..., dict[str, Any]]
DataFromGatewayFn = Callable[[dict[str, Any]], dict[str, Any]]
CONTEXT_AGENT_BASE = os.getenv("CONTEXT_AGENT_URL", "http://localhost:8004")


def fetch_guidance_matches(
    query: str,
    *,
    gateway_base: str,
    request_json: RequestJsonFn,
    data_from_gateway: DataFromGatewayFn,
    preferred_kind: str = "",
    limit: int = 5,
) -> list[dict[str, Any]]:
    guidance_query = (query or "").strip()
    if not guidance_query:
        return []

    normalized_query = " ".join(guidance_query.split())[:280]

    def _filter_kind(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        kind = preferred_kind.strip().lower()
        if not kind:
            return items
        kind_matches = [item for item in items if str(item.get("kind", "")).strip().lower() == kind]
        return kind_matches or items

    query_candidates = [normalized_query]
    tokens = [token for token in normalized_query.split() if len(token) > 2]
    if len(tokens) > 10:
        query_candidates.append(" ".join(tokens[:10]))
    query_candidates.append(" ".join(tokens[:6]))
    query_candidates = [candidate for candidate in query_candidates if candidate]

    for candidate in query_candidates:
        params: dict[str, Any] = {"query": candidate, "limit": max(1, int(limit))}
        if preferred_kind.strip():
            params["kind"] = preferred_kind.strip().lower()
        response = request_json(
            "GET",
            f"{gateway_base}/rag/search",
            params=params,
            show_error=False,
        )
        matches = data_from_gateway(response).get("matches", []) if response else []
        typed_matches = [item for item in matches if isinstance(item, dict)]
        if typed_matches:
            return _filter_kind(typed_matches)

    # Fallback path: query context-agent directly when gateway route is unavailable.
    for candidate in query_candidates:
        params = {"query": candidate, "limit": max(1, int(limit))}
        if preferred_kind.strip():
            params["kind"] = preferred_kind.strip().lower()
        fallback = request_json(
            "GET",
            f"{CONTEXT_AGENT_BASE}/rag/search",
            params=params,
            show_error=False,
        )
        fallback_matches = data_from_gateway(fallback).get("matches", []) if fallback else []
        typed_fallback = [item for item in fallback_matches if isinstance(item, dict)]
        if typed_fallback:
            return _filter_kind(typed_fallback)

    return []


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
