from __future__ import annotations

from typing import Any

SELECTED_FLOW_KEY = "selected_flow"
WORKFLOW_KEY = "workflow"
GATEWAY_RESPONSE_KEY = "gateway_response"
GUIDANCE_OPEN_KEY = "alerts_guidance_open"
GUIDANCE_QUERY_KEY = "alerts_guidance_query"
PANEL_MODE_KEY = "active_panel_mode"


def ensure_ui_defaults(state: Any) -> None:
    state.setdefault(SELECTED_FLOW_KEY, "payment-latency")
    state.setdefault(WORKFLOW_KEY, {})
    state.setdefault(GATEWAY_RESPONSE_KEY, {})
    state.setdefault(GUIDANCE_OPEN_KEY, False)
    state.setdefault(GUIDANCE_QUERY_KEY, "")
    state.setdefault(PANEL_MODE_KEY, "workflow")


def apply_guidance_selection(state: Any, guidance_query: str) -> None:
    state[GUIDANCE_QUERY_KEY] = guidance_query.strip()
    state[GUIDANCE_OPEN_KEY] = True
    state[PANEL_MODE_KEY] = "guidance"
    # Guidance mode should not retain stale incident workflow state.
    state[WORKFLOW_KEY] = {}
    state[GATEWAY_RESPONSE_KEY] = {}


def apply_workflow_payload(
    state: Any,
    selected_flow: str,
    gateway_response: dict[str, Any],
) -> bool:
    workflow_payload = gateway_response.get("data", {}) if isinstance(gateway_response, dict) else {}
    if not isinstance(workflow_payload, dict) or not workflow_payload:
        return False

    state[SELECTED_FLOW_KEY] = selected_flow.strip()
    state[GATEWAY_RESPONSE_KEY] = gateway_response
    state[WORKFLOW_KEY] = workflow_payload
    state[GUIDANCE_OPEN_KEY] = False
    state[PANEL_MODE_KEY] = "workflow"
    return True
