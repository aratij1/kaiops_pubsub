from __future__ import annotations

import os

import httpx
import streamlit as st

API_BASE = os.getenv("APPROVAL_SERVICE_URL", "http://localhost:8007")
MONITORING_BASE = os.getenv("MONITORING_ADAPTER_URL", "http://localhost:8001")


def request_json(method: str, url: str, **kwargs) -> dict:
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.request(method, url, **kwargs)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as exc:
        st.error(f"Unable to reach {url}. Is the target FastAPI service running? {exc}")
        return {}


st.set_page_config(page_title="KaiOps Incident Resolution", layout="wide")
st.title("KaiOps Agentic Incident Resolution Platform")

with st.sidebar:
    st.header("Sample Flow")
    st.caption("Local mode runs the workflow in-process when Kafka is disabled.")
    if st.button("Run payment latency workflow"):
        workflow = request_json("POST", f"{MONITORING_BASE}/sample/payment-latency/workflow")
        if workflow:
            st.session_state["workflow"] = workflow
            st.success("Workflow completed through recommendation generation.")

workflow = st.session_state.get("workflow", {})

tab_alerts, tab_incidents, tab_rca, tab_approval, tab_remediation, tab_closed = st.tabs(
    [
        "Live Alerts",
        "Incident Queue",
        "RCA",
        "Recommendations",
        "Remediation Status",
        "Closed Incidents",
    ]
)

with tab_alerts:
    st.info("Live alert stream is available from Kafka topic raw-alerts and service metrics.")
    if workflow.get("alert"):
        st.subheader("Latest Alert")
        st.json(workflow["alert"])

with tab_incidents:
    if workflow.get("incident"):
        st.subheader("Latest Incident")
        st.json(workflow["incident"])
        st.caption("Copy this incident ID if you want to query it from a running approval service.")
    incident_id = st.text_input("Incident ID")
    if incident_id:
        st.json(request_json("GET", f"{API_BASE}/incident/{incident_id}"))

with tab_rca:
    st.write("Resolution reports include root cause, impact, recommended action, and confidence score.")
    if workflow.get("context"):
        st.subheader("Collected Context")
        st.json(workflow["context"])
    if workflow.get("recommendation"):
        st.subheader("RCA Recommendation")
        st.json(workflow["recommendation"])

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
        st.json(request_json("POST", f"{API_BASE}/approve", json=payload))
    if col2.button("Reject", disabled=not approval_incident_id or not recommendation_id):
        st.json(request_json("POST", f"{API_BASE}/reject", json=payload))
    if col3.button("Modify", disabled=not approval_incident_id or not recommendation_id):
        payload["modified_action"] = action
        st.json(request_json("POST", f"{API_BASE}/modify", json=payload))

with tab_remediation:
    st.write("Remediation events are published to remediation-events and persisted in the actions table.")
    if workflow.get("decision"):
        st.subheader("Orchestrator Decision")
        st.json(workflow["decision"])

with tab_closed:
    st.write("Closed incident RCA reports are persisted in rca_reports and knowledge_base.")
