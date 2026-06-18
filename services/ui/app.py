from __future__ import annotations

import os
from typing import Any

import httpx
import streamlit as st

GATEWAY_BASE = os.getenv("API_GATEWAY_URL", "http://localhost:8010")


def request_json(method: str, url: str, **kwargs) -> dict[str, Any]:
    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.request(method, url, **kwargs)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as exc:
        st.error(f"Unable to reach {url}. Is the target service running? {exc}")
        return {}


def data_from_gateway(response: dict[str, Any]) -> dict[str, Any]:
    return response.get("data", response)


def get_flows() -> list[dict[str, Any]]:
    if "flows" not in st.session_state:
        response = request_json("GET", f"{GATEWAY_BASE}/sample/flows")
        st.session_state["flows"] = data_from_gateway(response).get("flows", [])
    return st.session_state.get("flows", [])


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
        [{key_label: key.replace("_", " ").title(), value_label: value} for key, value in values.items()],
        hide_index=True,
        use_container_width=True,
    )


def render_event_trace(events: list[dict[str, Any]]) -> None:
    rows = [
        {
            "Step": event.get("sequence"),
            "Agent": event.get("agent"),
            "Decision": event.get("decision"),
            "Communicates To": event.get("communicates_to"),
        }
        for event in sorted(events, key=lambda item: item.get("sequence", 0))
    ]
    st.dataframe(rows, hide_index=True, use_container_width=True)

    for event in sorted(events, key=lambda item: item.get("sequence", 0)):
        with st.expander(f"{event.get('sequence')}. {event.get('agent')}"):
            st.write(event.get("action"))
            status_badge("Input", event.get("input", "N/A"))
            status_badge("Output", event.get("output", "N/A"))
            table_from_dict(event.get("metrics", {}))


def render_gateway_events(events: list[dict[str, Any]]) -> None:
    rows = []
    for event in events:
        safety = event.get("safety", {})
        rows.append(
            {
                "Trace ID": event.get("trace_id"),
                "Path": event.get("path"),
                "Status": event.get("status_code"),
                "Decision": safety.get("decision"),
                "Score": safety.get("score"),
                "Latency ms": round(float(event.get("latency_ms", 0)), 2),
                "Reasons": "; ".join(safety.get("reasons", [])),
            }
        )
    if rows:
        st.dataframe(rows, hide_index=True, use_container_width=True)
        for event in events:
            with st.expander(f"Full trace for {event.get('path')} · {event.get('status_code')}"):
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


st.set_page_config(page_title="KaiOps", page_icon="⚡", layout="wide")

st.markdown(
    """
    <style>
      .block-container {padding-top: 1.5rem; max-width: 1280px;}
      div[data-testid="stMetric"] {
        background: #0f172a;
        border: 1px solid #1e293b;
        border-radius: 14px;
        padding: 14px;
      }
      div[data-testid="stMetric"] label, div[data-testid="stMetric"] div {
        color: #f8fafc !important;
      }
      .kaiops-card {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 16px;
        padding: 18px;
        margin-bottom: 12px;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("⚡ KaiOps Incident Command")
st.caption("Simple incident simulation, gateway safety, agent trace, remediation, and closure validation.")

flows = get_flows()
flow_options = {f"{flow['title']} · {flow['service']} · {flow['severity']}": flow["id"] for flow in flows}

with st.sidebar:
    st.header("Run a Scenario")
    selected_label = st.selectbox("Incident flow", list(flow_options) or ["payment-latency"])
    selected_flow = flow_options.get(selected_label, "payment-latency")
    st.caption("All requests route through the API Gateway for safety checks and traceability.")
    if st.button("Run Flow", type="primary", use_container_width=True):
        gateway_response = request_json("POST", f"{GATEWAY_BASE}/sample/{selected_flow}/workflow")
        if gateway_response:
            st.session_state["gateway_response"] = gateway_response
            st.session_state["workflow"] = gateway_response.get("data", {})
            st.success("Flow completed.")

    st.divider()
    if st.button("Refresh Gateway Events", use_container_width=True):
        st.session_state["gateway_summary"] = request_json("GET", f"{GATEWAY_BASE}/observability/summary")
        st.session_state["gateway_recent"] = request_json("GET", f"{GATEWAY_BASE}/observability/recent")

workflow = st.session_state.get("workflow", {})
gateway_response = st.session_state.get("gateway_response", {})
gateway = gateway_response.get("gateway", {})
metrics = workflow.get("metrics", {})
scenario = workflow.get("scenario", {})
alert = workflow.get("alert", {})
incident = workflow.get("incident", {})
context = workflow.get("context", {})
recommendation = workflow.get("recommendation", {})
remediation = workflow.get("remediation_action", {})
closure = workflow.get("closure_report", {})

if not workflow:
    st.info("Choose one of the 10 incident flows in the sidebar and click Run Flow.")
else:
    st.subheader(scenario.get("title", "Incident Flow"))
    render_copyable_id("Incident ID", incident.get("id"))
    render_copyable_id("Trace ID", gateway_response.get("trace_id"))
    metric_row(
        [
            ("Severity", str(metrics.get("severity", "unknown")).upper()),
            ("Confidence", f"{float(metrics.get('recommendation_confidence', 0)):.0%}"),
            ("Gateway", str(gateway.get("safety", {}).get("decision", "unknown")).upper()),
            ("Health Restored", "YES" if metrics.get("health_restored") else "NO"),
        ]
    )

tab_summary, tab_trace, tab_gateway, tab_closed = st.tabs(
    ["Incident Summary", "Agent Trace", "Gateway & Safety", "Closed Incidents"]
)

with tab_summary:
    if workflow:
        left, right = st.columns([1.2, 1])
        with left:
            st.markdown("### What happened")
            render_copyable_id("Incident ID", incident.get("id"))
            st.markdown(
                f"""
                <div class="kaiops-card">
                <b>{alert.get("name")}</b> from <b>{alert.get("source")}</b><br/>
                Service <b>{alert.get("service")}</b> in <b>{alert.get("environment")}</b><br/>
                {alert.get("description")}
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.markdown("### Agent recommendation")
            st.success(f"{recommendation.get('recommended_action')} - {recommendation.get('impact')}")
            st.write(recommendation.get("rationale"))
        with right:
            st.markdown("### Key metrics")
            table_from_dict(
                {
                    "deduplicated_count": metrics.get("deduplicated_count"),
                    "agent_handoffs": metrics.get("agent_handoffs"),
                    "dependencies": metrics.get("dependency_services"),
                    "recent_changes": metrics.get("recent_changes"),
                    "remediation_status": metrics.get("remediation_status"),
                    "alerts_cleared": metrics.get("alerts_cleared"),
                }
            )
            st.markdown("### Context")
            render_copyable_id("Trace ID", gateway_response.get("trace_id"))
            table_from_dict(
                {
                    "deployment": context.get("deployment"),
                    "runbook_found": bool(context.get("runbook")),
                    "dependencies": ", ".join(context.get("dependency_services", [])),
                }
            )

with tab_trace:
    st.markdown("### How agents decided and communicated")
    render_event_trace(workflow.get("events", []))

with tab_gateway:
    st.markdown("### Gateway safety and observability")
    if gateway_response:
        safety = gateway.get("safety", {})
        render_copyable_id("Full Trace ID", gateway_response.get("trace_id"))
        metric_row(
            [
                ("Decision", str(safety.get("decision", "unknown")).upper()),
                ("Safety Score", safety.get("score", 0)),
                ("Latency", f"{gateway.get('latency_ms', 0)} ms"),
            ]
        )
        st.markdown("#### Policy reasons")
        if safety.get("reasons"):
            for reason in safety["reasons"]:
                st.write(f"- {reason}")
        else:
            st.write("- Request allowed; no policy issues detected.")
        table_from_dict({"path": gateway.get("path"), "target_url": gateway.get("target_url")}, "Field", "Value")

    summary = st.session_state.get("gateway_summary") or request_json("GET", f"{GATEWAY_BASE}/observability/summary")
    recent = st.session_state.get("gateway_recent") or request_json("GET", f"{GATEWAY_BASE}/observability/recent")
    st.markdown("#### Gateway totals")
    metric_row(
        [
            ("Events", summary.get("total_events", 0)),
            ("Allowed", summary.get("allowed", 0)),
            ("Review", summary.get("review", 0)),
            ("Blocked", summary.get("blocked", 0)),
        ]
    )
    st.markdown("#### Recent gateway events")
    render_gateway_events(recent.get("events", []))

with tab_closed:
    st.markdown("### Closure report")
    if not closure:
        st.info("Run a flow to generate a closed incident report.")
    else:
        render_copyable_id("Closed Incident ID", closure.get("incident_id"))
        render_copyable_id("Trace ID", closure.get("trace_id"))
        metric_row(
            [
                ("Health Restored", "YES" if closure.get("health_restored") else "NO"),
                ("Alerts Cleared", "YES" if closure.get("alerts_cleared") else "NO"),
                ("Action", remediation.get("action_type", "N/A")),
                ("Status", remediation.get("status", "N/A")),
            ]
        )
        st.markdown("#### Final RCA")
        table_from_dict(
            {
                "root_cause": closure.get("root_cause"),
                "impact": closure.get("impact"),
                "action_taken": closure.get("action_taken"),
            }
        )
        st.markdown("#### Validation checks")
        table_from_dict(closure.get("validation", {}), "Check", "Passed")
        st.markdown("#### Knowledge base update")
        st.write(closure.get("knowledge_base_entry"))
        st.markdown("#### Lessons learned")
        for lesson in closure.get("lessons_learned", []):
            st.write(f"- {lesson}")
