from __future__ import annotations

import os

import httpx
import streamlit as st

API_BASE = os.getenv("APPROVAL_SERVICE_URL", "http://approval-service:8000")
MONITORING_BASE = os.getenv("MONITORING_ADAPTER_URL", "http://monitoring-adapter:8000")

st.set_page_config(page_title="KaiOps Incident Resolution", layout="wide")
st.title("KaiOps Agentic Incident Resolution Platform")

with st.sidebar:
    st.header("Sample Flow")
    if st.button("Inject payment latency alert"):
        with httpx.Client(timeout=10.0) as client:
            response = client.post(f"{MONITORING_BASE}/sample/payment-latency")
            st.json(response.json())

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

with tab_incidents:
    incident_id = st.text_input("Incident ID")
    if incident_id:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(f"{API_BASE}/incident/{incident_id}")
            st.json(response.json())

with tab_rca:
    st.write("Resolution reports include root cause, impact, recommended action, and confidence score.")

with tab_approval:
    st.subheader("Human Approval Workflow")
    approval_incident_id = st.text_input("Approval incident ID")
    recommendation_id = st.text_input("Recommendation ID")
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
        with httpx.Client(timeout=10.0) as client:
            st.json(client.post(f"{API_BASE}/approve", json=payload).json())
    if col2.button("Reject", disabled=not approval_incident_id or not recommendation_id):
        with httpx.Client(timeout=10.0) as client:
            st.json(client.post(f"{API_BASE}/reject", json=payload).json())
    if col3.button("Modify", disabled=not approval_incident_id or not recommendation_id):
        payload["modified_action"] = action
        with httpx.Client(timeout=10.0) as client:
            st.json(client.post(f"{API_BASE}/modify", json=payload).json())

with tab_remediation:
    st.write("Remediation events are published to remediation-events and persisted in the actions table.")

with tab_closed:
    st.write("Closed incident RCA reports are persisted in rca_reports and knowledge_base.")
