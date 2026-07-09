from __future__ import annotations

import json
from typing import Any

import streamlit as st


def metric_row(items: list[tuple[str, Any]]) -> None:
    columns = st.columns(len(items))
    for column, (label, value) in zip(columns, items, strict=True):
        column.metric(label, value)


def status_badge(label: str, value: str) -> None:
    st.markdown(f"**{label}:** `{value}`")


def render_copyable_id(label: str, value: Any) -> None:
    if value:
        st.markdown(f"**{label}**")
        st.code(str(value), language=None)


def table_from_dict(values: dict[str, Any], key_label: str = "Metric", value_label: str = "Value") -> None:
    if not values:
        st.caption("No data.")
        return
    st.dataframe(
        [{key_label: key.replace("_", " ").title(), value_label: str(value)} for key, value in values.items()],
        hide_index=True,
        width="stretch",
    )


def render_trace_output_with_kv(response_value: Any) -> None:
    response_text = ""
    response_parameters: dict[str, Any] = {}

    if isinstance(response_value, dict):
        response_text = str(response_value.get("text", ""))
        maybe_parameters = response_value.get("parameters", {})
        if isinstance(maybe_parameters, dict):
            response_parameters = maybe_parameters
    else:
        response_text = str(response_value)

    if response_text:
        st.code(response_text, language="text")

    if response_parameters:
        st.markdown("**Response parameters**")
        table_from_dict(response_parameters, "Field", "Value")

    if response_text:
        try:
            parsed = json.loads(response_text)
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            st.markdown("**Response output (key-value)**")
            table_from_dict(parsed, "Field", "Value")


def format_event_decision(value: Any) -> str:
    if isinstance(value, dict):
        parts: list[str] = []
        workflow = str(value.get("workflow") or "").strip()
        next_action = str(value.get("next_action") or "").strip()
        provider = str(value.get("message_bus_provider") or "").strip().lower()
        risk_tier = str(value.get("risk_tier") or "").strip().lower()
        execution_mode = str(value.get("execution_mode") or "").strip().lower()
        requires_approval = value.get("requires_approval")

        if workflow:
            parts.append(workflow)
        if next_action:
            parts.append(f"next={next_action}")
        if provider:
            parts.append(f"bus={provider}")
        if risk_tier:
            parts.append(f"risk={risk_tier}")
        if execution_mode:
            parts.append(f"mode={execution_mode}")
        if requires_approval is not None:
            parts.append(f"approval={'yes' if bool(requires_approval) else 'no'}")

        if parts:
            return "; ".join(parts)

        try:
            return json.dumps(value, default=str)
        except Exception:
            return str(value)

    if isinstance(value, (list, tuple, set)):
        return json.dumps(list(value), default=str)

    text = str(value or "").strip()
    return text or "N/A"


def render_gateway_events(events: list[dict[str, Any]]) -> None:
    rows = []
    for event in events:
        safety = event.get("safety", {})
        rows.append(
            {
                "Trace ID": event.get("trace_id"),
                "Path": event.get("path"),
                "Status": str(event.get("status_code")),
                "Decision": safety.get("decision"),
                "Score": str(safety.get("score")),
                "Latency ms": str(round(float(event.get("latency_ms", 0)), 2)),
                "Reasons": "; ".join(safety.get("reasons", [])),
            }
        )
    if rows:
        st.dataframe(rows, hide_index=True, width="stretch")
        for event in events:
            with st.expander(f"Full trace for {event.get('path')} | {event.get('status_code')}"):
                render_copyable_id("Trace ID", event.get("trace_id"))
                table_from_dict(
                    {
                        "path": event.get("path"),
                        "target_url": event.get("target_url"),
                        "status_code": event.get("status_code"),
                        "latency_ms": round(float(event.get("latency_ms", 0)), 2),
                        "safety_decision": event.get("safety", {}).get("decision"),
                    },
                    "Field",
                    "Value",
                )
    else:
        st.caption("No gateway events yet.")
