from __future__ import annotations

import os
from typing import Any

import httpx
import streamlit as st

GATEWAY_BASE = os.getenv("API_GATEWAY_URL", "http://localhost:8010")
UI_REQUEST_TIMEOUT_SECONDS = float(os.getenv("UI_REQUEST_TIMEOUT_SECONDS", "240"))


def request_json(method: str, url: str, **kwargs) -> dict[str, Any]:
    try:
        with httpx.Client(timeout=UI_REQUEST_TIMEOUT_SECONDS) as client:
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
        [{key_label: key.replace("_", " ").title(), value_label: str(value)} for key, value in values.items()],
        hide_index=True,
        width="stretch",
    )


def render_event_trace(events: list[dict[str, Any]]) -> None:
    rows = [
        {
            "Step": event.get("sequence"),
            "Agent": event.get("agent"),
            "Decision": str(event.get("decision")),
            "Communicates To": str(event.get("communicates_to")),
        }
        for event in sorted(events, key=lambda item: item.get("sequence", 0))
    ]
    st.dataframe(rows, hide_index=True, width="stretch")

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
    if st.button("Run Flow", type="primary", width="stretch"):
        gateway_response = request_json("POST", f"{GATEWAY_BASE}/sample/{selected_flow}/workflow")
        if gateway_response:
            st.session_state["gateway_response"] = gateway_response
            st.session_state["workflow"] = gateway_response.get("data", {})
            st.success("Flow completed.")

    st.divider()
    if st.button("Refresh Gateway Events", width="stretch"):
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
finops = workflow.get("finops", {})

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

tab_summary, tab_approval, tab_trace, tab_finops, tab_gateway, tab_closed = st.tabs(
    ["Incident Summary", "Approval", "Agent Trace", "FinOps", "Gateway & Safety", "Closed Incidents"]
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

with tab_approval:
    st.markdown("### Human approval")
    if not workflow:
        st.info("Run a flow first. The approval form will be prefilled with incident and recommendation IDs.")
    else:
        render_copyable_id("Incident ID", incident.get("id"))
        render_copyable_id("Recommendation ID", recommendation.get("id"))
        render_copyable_id("Trace ID", gateway_response.get("trace_id"))

        default_action = recommendation.get("recommended_action", "Rollback deployment")
        approval_incident_id = st.text_input("Incident ID for approval", value=incident.get("id", ""))
        recommendation_id = st.text_input("Recommendation ID for approval", value=recommendation.get("id", ""))
        approver = st.text_input("Approver", value="sre@example.com")
        channel = st.selectbox("Channel", ["web", "slack", "teams", "email"])
        comment = st.text_input("Approval comment / action", value=default_action)

        payload = {
            "incident_id": approval_incident_id,
            "recommendation_id": recommendation_id,
            "approver": approver,
            "channel": channel,
            "comment": comment,
        }

        col_approve, col_reject, col_modify = st.columns(3)
        if col_approve.button("Approve", type="primary", width="stretch"):
            st.session_state["approval_response"] = request_json(
                "POST", f"{GATEWAY_BASE}/approval/approve", json=payload
            )
        if col_reject.button("Reject", width="stretch"):
            st.session_state["approval_response"] = request_json(
                "POST", f"{GATEWAY_BASE}/approval/reject", json=payload
            )
        if col_modify.button("Modify", width="stretch"):
            payload["modified_action"] = comment
            st.session_state["approval_response"] = request_json(
                "POST", f"{GATEWAY_BASE}/approval/modify", json=payload
            )

        approval_response = st.session_state.get("approval_response", {})
        if approval_response:
            approval_data = approval_response.get("data", {})
            approval_gateway = approval_response.get("gateway", {})
            st.markdown("### Latest approval result")
            metric_row(
                [
                    ("Decision", str(approval_data.get("decision", "unknown")).upper()),
                    ("Channel", approval_data.get("channel", "N/A")),
                    ("Gateway", str(approval_gateway.get("safety", {}).get("decision", "unknown")).upper()),
                    ("Latency", f"{approval_gateway.get('latency_ms', 0)} ms"),
                ]
            )
            render_copyable_id("Approval ID", approval_data.get("id"))
            render_copyable_id("Approval Trace ID", approval_response.get("trace_id"))
            table_from_dict(
                {
                    "approver": approval_data.get("approver"),
                    "comment": approval_data.get("comment"),
                    "modified_action": approval_data.get("modified_action"),
                    "safety_score": approval_gateway.get("safety", {}).get("score"),
                }
            )

with tab_trace:
    st.markdown("### How agents decided and communicated")
    render_event_trace(workflow.get("events", []))

with tab_finops:
    st.markdown("### LLM FinOps")
    if not finops:
        st.info("Run a flow to see token usage and model costs.")
    else:
        totals = finops.get("totals", {})
        metric_row(
            [
                ("LLM Calls", totals.get("calls", 0)),
                ("Total Tokens", totals.get("total_tokens", 0)),
                ("Total Cost", f"${float(totals.get('total_cost_usd', 0.0)):.6f}"),
                ("Failed Calls", totals.get("failed_calls", 0)),
            ]
        )
        st.markdown("#### Provider cost breakdown")
        st.caption("Gemini and Groq comparison calls run in parallel for FinOps visibility when configured.")
        provider_rows = [
            {
                "Provider": row.get("provider"),
                "Calls": str(row.get("calls", 0)),
                "Tokens": str(row.get("total_tokens", 0)),
                "Cost USD": f"${float(row.get('total_cost_usd', 0.0)):.6f}",
            }
            for row in finops.get("by_provider", [])
        ]
        if provider_rows:
            st.dataframe(provider_rows, hide_index=True, width="stretch")
        else:
            st.caption("No successful model calls recorded.")

        st.markdown("#### Per-call model usage")
        call_rows = [
            {
                "Task": call.get("task"),
                "Provider": call.get("provider"),
                "Model": call.get("model"),
                "Input Tokens": str(call.get("input_tokens", 0)),
                "Output Tokens": str(call.get("output_tokens", 0)),
                "Total Tokens": str(call.get("total_tokens", 0)),
                "Cost USD": f"${float(call.get('total_cost_usd', 0.0)):.6f}",
                "Estimated": str(call.get("estimated", False)),
            }
            for call in finops.get("calls", [])
        ]
        if call_rows:
            st.dataframe(call_rows, hide_index=True, width="stretch")

        errors = finops.get("errors", [])
        if errors:
            st.markdown("#### Provider failover/errors")
            st.dataframe(
                [{"Task": item.get("task"), "Error": item.get("error")} for item in errors],
                hide_index=True,
                width="stretch",
            )

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
