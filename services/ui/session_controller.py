from __future__ import annotations

from typing import Any

SELECTED_FLOW_KEY = "selected_flow"
WORKFLOW_KEY = "workflow"
GATEWAY_RESPONSE_KEY = "gateway_response"
LAST_WORKFLOW_KEY = "last_workflow"
LAST_GATEWAY_RESPONSE_KEY = "last_gateway_response"
GUIDANCE_OPEN_KEY = "alerts_guidance_open"
GUIDANCE_QUERY_KEY = "alerts_guidance_query"
GUIDANCE_QUERY_INPUT_KEY = "alerts_guidance_query_input"
GUIDANCE_KIND_KEY = "alerts_guidance_kind"
GUIDANCE_ACTION_KEY = "alerts_guidance_action"
PANEL_MODE_KEY = "active_panel_mode"


def ensure_ui_defaults(state: Any) -> None:
    state.setdefault(SELECTED_FLOW_KEY, "payment-latency")
    state.setdefault(WORKFLOW_KEY, {})
    state.setdefault(GATEWAY_RESPONSE_KEY, {})
    state.setdefault(LAST_WORKFLOW_KEY, {})
    state.setdefault(LAST_GATEWAY_RESPONSE_KEY, {})
    state.setdefault(GUIDANCE_OPEN_KEY, False)
    state.setdefault(GUIDANCE_QUERY_KEY, "")
    state.setdefault(GUIDANCE_KIND_KEY, "")
    state.setdefault(GUIDANCE_ACTION_KEY, "")
    state.setdefault(PANEL_MODE_KEY, "workflow")


def apply_guidance_selection(
    state: Any,
    guidance_query: str,
    preferred_kind: str = "",
    action_label: str = "",
) -> None:
    normalized_query = guidance_query.strip()
    state[GUIDANCE_QUERY_KEY] = normalized_query
    # Seed the input key only before the widget is instantiated in the run.
    # Writing to a widget-bound key after instantiation raises StreamlitAPIException.
    if GUIDANCE_QUERY_INPUT_KEY not in state:
        state[GUIDANCE_QUERY_INPUT_KEY] = normalized_query
    state[GUIDANCE_KIND_KEY] = preferred_kind.strip().lower()
    state[GUIDANCE_ACTION_KEY] = action_label.strip()
    state[GUIDANCE_OPEN_KEY] = True
    state[PANEL_MODE_KEY] = "guidance"


def apply_workflow_payload(
    state: Any,
    selected_flow: str,
    gateway_response: dict[str, Any],
) -> bool:
    workflow_payload: dict[str, Any] = {}
    if isinstance(gateway_response, dict):
        wrapped = gateway_response.get("data")
        if isinstance(wrapped, dict) and wrapped:
            workflow_payload = wrapped
        elif gateway_response:
            # Support direct service responses that are not nested under "data".
            workflow_payload = gateway_response
    if not isinstance(workflow_payload, dict) or not workflow_payload:
        return False

    state[SELECTED_FLOW_KEY] = selected_flow.strip()
    state[GATEWAY_RESPONSE_KEY] = gateway_response
    state[WORKFLOW_KEY] = workflow_payload
    state[LAST_GATEWAY_RESPONSE_KEY] = gateway_response
    state[LAST_WORKFLOW_KEY] = workflow_payload
    state[GUIDANCE_OPEN_KEY] = False
    state[PANEL_MODE_KEY] = "workflow"
    return True
