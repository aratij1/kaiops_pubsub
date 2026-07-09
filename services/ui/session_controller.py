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

_PLACEHOLDER_TOKENS = {"", "-", "n/a", "na", "none", "null", "unknown"}
_PENDING_DECISIONS = {"PENDING", "QUEUED", "AWAITING_APPROVAL", "AWAITING USER APPROVAL", "STANDBY"}


def _is_meaningful_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() not in _PLACEHOLDER_TOKENS
    if isinstance(value, (list, dict, tuple, set)):
        return len(value) > 0
    return True


def _event_quality_score(event: dict[str, Any]) -> int:
    score = 0
    decision = str(event.get("decision") or "").strip()
    decision_token = decision.upper()
    if _is_meaningful_value(decision):
        score += 2
    if decision_token and decision_token not in _PENDING_DECISIONS:
        score += 8
    if _is_meaningful_value(event.get("output")):
        score += 3
    if _is_meaningful_value(event.get("action")):
        score += 2
    if isinstance(event.get("input"), dict) and event.get("input"):
        score += 1
    if isinstance(event.get("metrics"), dict) and event.get("metrics"):
        score += 1
    return score


def _merged_event(group: list[dict[str, Any]]) -> dict[str, Any]:
    if len(group) == 1:
        return dict(group[0])

    # Prefer the most informative event for the same step/agent pair.
    best = max(group, key=_event_quality_score)
    merged = dict(best)

    for item in group:
        for field in ("action", "decision", "output", "communicates_to"):
            if not _is_meaningful_value(merged.get(field)) and _is_meaningful_value(item.get(field)):
                merged[field] = item.get(field)

        for object_field in ("input", "metrics"):
            existing = merged.get(object_field)
            incoming = item.get(object_field)
            if isinstance(existing, dict) and isinstance(incoming, dict):
                for key, value in incoming.items():
                    if key not in existing and _is_meaningful_value(value):
                        existing[key] = value
            elif (not isinstance(existing, dict) or not existing) and isinstance(incoming, dict) and incoming:
                merged[object_field] = dict(incoming)

    llm_calls: list[Any] = []
    llm_errors: list[Any] = []
    for item in group:
        if isinstance(item.get("llm_calls"), list):
            llm_calls.extend(item.get("llm_calls") or [])
        if isinstance(item.get("llm_errors"), list):
            llm_errors.extend(item.get("llm_errors") or [])
    if llm_calls:
        merged["llm_calls"] = llm_calls
    if llm_errors:
        merged["llm_errors"] = llm_errors

    return merged


def _deduplicate_workflow_events(events: Any) -> list[dict[str, Any]]:
    if not isinstance(events, list):
        return []

    grouped: dict[tuple[int, str], list[dict[str, Any]]] = {}
    first_index: dict[tuple[int, str], int] = {}

    for index, raw in enumerate(events):
        if not isinstance(raw, dict):
            continue
        sequence = int(raw.get("sequence", 0) or 0)
        agent = str(raw.get("agent") or "").strip()
        key = (sequence, agent)
        grouped.setdefault(key, []).append(raw)
        first_index.setdefault(key, index)

    ordered_keys = sorted(grouped.keys(), key=lambda key: (key[0], first_index.get(key, 0)))
    return [_merged_event(grouped[key]) for key in ordered_keys]


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

    if "events" in workflow_payload:
        workflow_payload["events"] = _deduplicate_workflow_events(workflow_payload.get("events"))

    state[SELECTED_FLOW_KEY] = selected_flow.strip()
    state[GATEWAY_RESPONSE_KEY] = gateway_response
    state[WORKFLOW_KEY] = workflow_payload
    state[LAST_GATEWAY_RESPONSE_KEY] = gateway_response
    state[LAST_WORKFLOW_KEY] = workflow_payload
    state[GUIDANCE_OPEN_KEY] = False
    state[PANEL_MODE_KEY] = "workflow"
    return True
