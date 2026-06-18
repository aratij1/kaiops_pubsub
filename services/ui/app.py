from __future__ import annotations

import os
from typing import Any

import httpx
import streamlit as st

GATEWAY_BASE = os.getenv("API_GATEWAY_URL", "http://localhost:8010")


def request_json(method: str, url: str, **kwargs) -> dict:
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.request(method, url, **kwargs)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as exc:
        st.error(f"Unable to reach {url}. Is the target FastAPI service running? {exc}")
        return {}


def nested(data: dict[str, Any], *keys: str, default: Any = "") -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key, default)
    return current


def render_kv(title: str, values: dict[str, Any]) -> None:
    st.subheader(title)
    for key, value in values.items():
        label = key.replace("_", " ").title()
        st.markdown(f"**{label}:** {value if value not in (None, '') else 'N/A'}")


def render_list(title: str, values: list[Any]) -> None:
    st.markdown(f"**{title}**")
    if not values:
        st.caption("None found.")
        return
    for item in values:
        if isinstance(item, dict):
            text = ", ".join(f"{key}: {value}" for key, value in item.items())
        else:
            text = str(item)
        st.markdown(f"- {text}")


def render_workflow_metrics(metrics: dict[str, Any], gateway: dict[str, Any]) -> None:
    safety = gateway.get("safety", {})
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Severity", str(metrics.get("severity", "unknown")).upper())
    col2.metric("RCA Confidence", f"{float(metrics.get('recommendation_confidence', 0.0)):.0%}")
    col3.metric("Gateway Safety", str(safety.get("decision", "unknown")).upper())
    col4.metric("Gateway Latency", f"{gateway.get('latency_ms', 0)} ms")

    col5, col6, col7, col8 = st.columns(4)
    col5.metric("Agent Handoffs", metrics.get("agent_handoffs", 0))
    col6.metric("Dependencies", metrics.get("dependency_services", 0))
    col7.metric("Recent Changes", metrics.get("recent_changes", 0))
    col8.metric("Deduplicated Alerts", metrics.get("deduplicated_count", 0))


def render_event_timeline(events: list[dict[str, Any]]) -> None:
    if not events:
        st.info("No agent events captured yet.")
        return

    for event in sorted(events, key=lambda item: item.get("sequence", 0)):
        title = f"{event.get('sequence')}. {event.get('agent')} - {event.get('action')}"
        with st.expander(title, expanded=True):
            st.markdown(f"**Input:** {event.get('input', 'N/A')}")
            st.markdown(f"**Decision:** {event.get('decision', 'N/A')}")
            st.markdown(f"**Output:** {event.get('output', 'N/A')}")
            st.markdown(f"**Communicates To:** {event.get('communicates_to', 'N/A')}")
            metrics = event.get("metrics", {})
            if metrics:
                st.table([{"Metric": key.replace("_", " ").title(), "Value": value} for key, value in metrics.items()])


def render_gateway_event_table(events: list[dict[str, Any]]) -> None:
    rows = []
    for event in events:
        safety = event.get("safety", {})
        rows.append(
            {
                "Trace ID": event.get("trace_id", ""),
                "Path": event.get("path", ""),
                "Status": event.get("status_code", ""),
                "Decision": safety.get("decision", ""),
                "Score": safety.get("score", ""),
                "Latency ms": round(float(event.get("latency_ms", 0.0)), 2),
                "Reasons": "; ".join(safety.get("reasons", [])),
            }
        )
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.caption("No gateway events recorded yet.")


st.set_page_config(page_title="KaiOps Incident Resolution", layout="wide")
st.title("KaiOps Agentic Incident Resolution Platform")

with st.sidebar:
    st.header("Sample Flow")
    st.caption("Requests go through the API Gateway for safety checks and trace IDs.")
    if st.button("Run payment latency workflow"):
        gateway_response = request_json("POST", f"{GATEWAY_BASE}/sample/payment-latency/workflow")
        workflow = gateway_response.get("data", {})
        if gateway_response:
            st.session_state["gateway_response"] = gateway_response
            st.session_state["workflow"] = workflow
            st.success("Workflow completed through recommendation generation.")

workflow = st.session_state.get("workflow", {})
gateway_response = st.session_state.get("gateway_response", {})
gateway = gateway_response.get("gateway", {})
metrics = workflow.get("metrics", {})

tab_overview, tab_alerts, tab_incidents, tab_rca, tab_approval, tab_trace, tab_gateway, tab_closed = st.tabs(
    [
        "Overview",
        "Live Alerts",
        "Incident Queue",
        "RCA",
        "Recommendations",
        "Agent Trace",
        "Gateway Trace & Safety",
        "Closed Incidents",
    ]
)

with tab_overview:
    st.subheader("Workflow Health & Test Metrics")
    if workflow:
        render_workflow_metrics(metrics, gateway)
        recommendation = workflow.get("recommendation", {})
        st.markdown("### Current Recommendation")
        st.success(
            f"{recommendation.get('recommended_action', 'No action generated')} "
            f"for {recommendation.get('impact', 'unknown impact')}."
        )
        st.markdown(f"**Rationale:** {recommendation.get('rationale', 'N/A')}")
        st.markdown(f"**Next Step:** {workflow.get('next_step', 'N/A')}")
    else:
        st.info("Run the sample workflow from the sidebar to populate metrics and traceability.")

with tab_alerts:
    st.info("Live alert stream is available from Kafka topic raw-alerts and service metrics.")
    alert = workflow.get("alert", {})
    if alert:
        render_kv(
            "Latest Alert",
            {
                "name": alert.get("name"),
                "source": alert.get("source"),
                "service": alert.get("service"),
                "environment": alert.get("environment"),
                "severity": str(alert.get("severity", "")).upper(),
                "description": alert.get("description"),
                "trace_id": alert.get("trace_id"),
                "correlation_id": alert.get("correlation_id"),
                "deduplicated_count": alert.get("deduplicated_count"),
            },
        )
        st.markdown("**Labels**")
        st.table([{"Key": key, "Value": value} for key, value in alert.get("labels", {}).items()])

with tab_incidents:
    incident = workflow.get("incident", {})
    if incident:
        render_kv(
            "Latest Incident",
            {
                "id": incident.get("id"),
                "title": incident.get("title"),
                "service": incident.get("service"),
                "environment": incident.get("environment"),
                "severity": str(incident.get("severity", "")).upper(),
                "status": incident.get("status"),
                "owner_team": incident.get("owner_team"),
                "trace_id": incident.get("trace_id"),
            },
        )
        st.caption("Copy this incident ID if you want to query it from a running approval service.")
    incident_id = st.text_input("Incident ID")
    if incident_id:
        incident_response = request_json("GET", f"{GATEWAY_BASE}/approval/incident/{incident_id}")
        st.session_state["incident_lookup"] = incident_response
    if st.session_state.get("incident_lookup"):
        data = st.session_state["incident_lookup"].get("data", st.session_state["incident_lookup"])
        render_kv("Incident Lookup Result", data if isinstance(data, dict) else {"result": data})

with tab_rca:
    st.write("Resolution reports include root cause, impact, recommended action, and confidence score.")
    context = workflow.get("context", {})
    recommendation = workflow.get("recommendation", {})
    if recommendation:
        render_kv(
            "RCA Recommendation",
            {
                "root_cause": recommendation.get("root_cause"),
                "confidence": f"{float(recommendation.get('confidence', 0.0)):.0%}",
                "impact": recommendation.get("impact"),
                "recommended_action": recommendation.get("recommended_action"),
                "risk": recommendation.get("risk"),
                "trace_id": recommendation.get("trace_id"),
            },
        )
        st.markdown(f"**Rationale:** {recommendation.get('rationale', 'N/A')}")
        render_list("Commands", recommendation.get("commands", []))
    if context:
        render_kv(
            "Collected Context",
            {
                "deployment": context.get("deployment"),
                "runbook": context.get("runbook"),
                "trace_id": context.get("trace_id"),
            },
        )
        render_list("Related Incidents", context.get("related_incidents", []))
        render_list("Dependency Services", context.get("dependency_services", []))
        render_list("Recent Changes", context.get("recent_changes", []))
        if context.get("observability"):
            st.markdown("**Observability Signals**")
            st.table(
                [
                    {"Signal": key.replace("_", " ").title(), "Value": value}
                    for key, value in context.get("observability", {}).items()
                ]
            )

with tab_approval:
    st.subheader("Human Approval Workflow")
    approval_incident_id = st.text_input(
        "Approval incident ID",
        value=workflow.get("incident", {}).get("id", ""),
    )
    recommendation_id = st.text_input(
        "Recommendation ID",
        value=workflow.get("recommendation", {}).get("id", ""),
    )
    approver = st.text_input("Approver", value="sre@example.com")
    channel = st.selectbox("Channel", ["web", "slack", "teams", "email"])
    action = st.text_input("Modified action", value="Rollback deployment")
    col1, col2, col3 = st.columns(3)
    payload = {
        "incident_id": approval_incident_id,
        "recommendation_id": recommendation_id,
        "approver": approver,
        "channel": channel,
        "comment": action,
    }
    if col1.button("Approve", disabled=not approval_incident_id or not recommendation_id):
        st.session_state["approval_response"] = request_json("POST", f"{GATEWAY_BASE}/approval/approve", json=payload)
    if col2.button("Reject", disabled=not approval_incident_id or not recommendation_id):
        st.session_state["approval_response"] = request_json("POST", f"{GATEWAY_BASE}/approval/reject", json=payload)
    if col3.button("Modify", disabled=not approval_incident_id or not recommendation_id):
        payload["modified_action"] = action
        st.session_state["approval_response"] = request_json("POST", f"{GATEWAY_BASE}/approval/modify", json=payload)

    approval_response = st.session_state.get("approval_response", {})
    if approval_response:
        st.subheader("Latest Approval Gateway Result")
        approval_data = approval_response.get("data", {})
        gateway_data = approval_response.get("gateway", {})
        render_kv(
            "Approval Decision",
            {
                "decision": approval_data.get("decision"),
                "approver": approval_data.get("approver"),
                "channel": approval_data.get("channel"),
                "comment": approval_data.get("comment"),
                "trace_id": approval_response.get("trace_id"),
            },
        )
        render_kv(
            "Gateway Result",
            {
                "safety_decision": nested(gateway_data, "safety", "decision"),
                "safety_score": nested(gateway_data, "safety", "score"),
                "latency_ms": gateway_data.get("latency_ms"),
            },
        )

with tab_trace:
    st.subheader("Full Agent Trace")
    render_event_timeline(workflow.get("events", []))
    if workflow.get("decision"):
        decision = workflow["decision"]
        render_kv(
            "Orchestrator Decision",
            {
                "workflow": decision.get("workflow"),
                "next_action": decision.get("next_action"),
                "downstream_agents": ", ".join(decision.get("downstream_agents", [])),
                "requires_approval": decision.get("requires_approval"),
            },
        )

with tab_gateway:
    st.subheader("Latest Gateway Decision")
    if gateway_response:
        safety = nested(gateway_response, "gateway", "safety", default={})
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Trace ID", gateway_response.get("trace_id", ""))
        col2.metric("Decision", str(safety.get("decision", "unknown")).upper())
        col3.metric("Safety Score", safety.get("score", 0))
        col4.metric("Latency", f"{nested(gateway_response, 'gateway', 'latency_ms', default=0)} ms")
        render_list("Safety Reasons", safety.get("reasons", []))
        render_list("Safety Categories", safety.get("categories", []))
        render_kv(
            "Gateway Routing",
            {
                "path": nested(gateway_response, "gateway", "path"),
                "target_url": nested(gateway_response, "gateway", "target_url"),
            },
        )
    else:
        st.info("Run a workflow to see gateway safety and trace metadata.")

    col_summary, col_recent = st.columns(2)
    if col_summary.button("Refresh Gateway Summary"):
        st.session_state["gateway_summary"] = request_json("GET", f"{GATEWAY_BASE}/observability/summary")
    if col_recent.button("Refresh Recent Gateway Events"):
        st.session_state["gateway_recent"] = request_json("GET", f"{GATEWAY_BASE}/observability/recent")

    if st.session_state.get("gateway_summary"):
        st.subheader("Gateway Summary")
        summary = st.session_state["gateway_summary"]
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Events", summary.get("total_events", 0))
        col2.metric("Allowed", summary.get("allowed", 0))
        col3.metric("Review", summary.get("review", 0))
        col4.metric("Blocked", summary.get("blocked", 0))
        st.markdown(f"**Latest Trace ID:** {summary.get('latest_trace_id', 'N/A')}")
    if st.session_state.get("gateway_recent"):
        st.subheader("Recent Gateway Events")
        render_gateway_event_table(st.session_state["gateway_recent"].get("events", []))

with tab_closed:
    st.write("Closed incident RCA reports are persisted in rca_reports and knowledge_base.")
