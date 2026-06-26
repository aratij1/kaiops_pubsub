from __future__ import annotations

import html
import os
from typing import Any

import httpx
import streamlit as st

GATEWAY_BASE = os.getenv("API_GATEWAY_URL", "http://localhost:8010")


@st.cache_data(ttl=10, show_spinner=False)
def _fetch_agent_work_items_cached(limit: int = 100) -> list[dict[str, Any]]:
    try:
        with httpx.Client(timeout=8.0) as client:
            response = client.get(f"{GATEWAY_BASE}/agent-work/items", params={"limit": max(1, int(limit))})
            response.raise_for_status()
            payload = response.json()
        data = payload.get("data", payload) if isinstance(payload, dict) else {}
        rows = data.get("rows", []) if isinstance(data, dict) else []
        return [row for row in rows if isinstance(row, dict)]
    except Exception:
        return []


def render_agent_role_overview(
    events: list[dict[str, Any]],
    *,
    agent_profiles: dict[str, dict[str, str]],
    fallback_icon_data_uri: str,
) -> None:
    events_by_agent = {str(event.get("agent", "")): event for event in events}
    st.markdown("#### Agent Command Roles")
    agent_items = list(agent_profiles.items())
    for start in range(0, len(agent_items), 3):
        columns = st.columns(3)
        for offset, column in enumerate(columns):
            index = start + offset
            if index >= len(agent_items):
                continue

            agent_name, profile = agent_items[index]
            event = events_by_agent.get(agent_name, {})
            status = "COMPLETED" if event else "STANDBY"
            decision = str(event.get("decision", "Awaiting workflow execution"))
            decision_text = decision.strip()
            if len(decision_text) > 88:
                decision_text = f"{decision_text[:85].rstrip()}..."

            mission_text = str(profile.get("mission", "Coordinates incident-resolution logic.")).strip()
            icon_image = str(profile.get("icon_image", "")).strip() or fallback_icon_data_uri
            decision_class = "kaiops-role-decision-complete" if event else "kaiops-role-decision-standby"

            with column:
                st.markdown(
                    f"""
                    <div class="kaiops-role-card">
                      <p class="kaiops-role-step">Step {index + 1} · {html.escape(status)}</p>
                      <div class="kaiops-role-title-row" title="{html.escape(mission_text, quote=True)}">
                        <img class="kaiops-role-icon" src="{html.escape(icon_image, quote=True)}" alt="{html.escape(agent_name)} icon" />
                        <p class="kaiops-role-title">{html.escape(agent_name)}</p>
                        <span class="kaiops-role-help" title="{html.escape(mission_text, quote=True)}">&#9432;</span>
                      </div>
                      <div class="kaiops-role-decision {decision_class}">{html.escape(decision_text)}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )


def render_agent_work_tracker(limit: int = 56) -> None:
    rows = _fetch_agent_work_items_cached(limit=limit)
    st.markdown("#### Agent Work Status")
    if not rows:
        st.caption("No agent work items tracked yet. Run a workflow to populate status records.")
        return

    st.dataframe(
        [
            {
                "Incident": row.get("incident_id", ""),
                "Agent": row.get("agent_name", ""),
                "Work": row.get("work_item", ""),
                "Status": str(row.get("status", "")).upper(),
                "Trace": row.get("trace_id", ""),
                "Updated": row.get("updated_at", ""),
            }
            for row in rows
        ],
        hide_index=True,
        use_container_width=True,
    )


def _normalize_status_label(value: str) -> str:
    token = str(value or "").strip().upper()
    if token in {"COMPLETED", "SUCCEEDED", "SUCCESS", "CLOSED"}:
        return "COMPLETED"
    if token in {"PENDING", "QUEUED", "STANDBY"}:
        return "PENDING"
    if token in {"FAILED", "ERROR", "BLOCKED", "REJECTED"}:
        return "FAILED"
    return token or "STANDBY"


def _status_style(status: str) -> tuple[str, str]:
    normalized = _normalize_status_label(status)
    if normalized == "COMPLETED":
        return "#16a34a", "Completed"
    if normalized == "PENDING":
        return "#d97706", "Pending"
    if normalized == "FAILED":
        return "#dc2626", "Failed"
    return "#64748b", normalized.title()


def _latest_status_by_agent(
    *,
    events: list[dict[str, Any]],
    work_rows: list[dict[str, Any]],
    agent_profiles: dict[str, dict[str, str]],
) -> list[tuple[str, str]]:
    status_by_agent: dict[str, str] = {name: "STANDBY" for name in agent_profiles.keys()}

    for event in events:
        agent_name = str(event.get("agent") or "").strip()
        if agent_name:
            status_by_agent[agent_name] = "COMPLETED"

    for row in work_rows:
        agent_name = str(row.get("agent_name") or "").strip()
        if not agent_name:
            continue
        row_status = str(row.get("status") or "").strip().upper()
        if row_status:
            status_by_agent[agent_name] = row_status

    return [(agent_name, status_by_agent.get(agent_name, "STANDBY")) for agent_name in agent_profiles.keys()]


def render_agent_status_graph(
    *,
    events: list[dict[str, Any]],
    work_rows: list[dict[str, Any]],
    agent_profiles: dict[str, dict[str, str]],
) -> None:
    st.markdown("#### Agent Status Pipeline")
    statuses = _latest_status_by_agent(events=events, work_rows=work_rows, agent_profiles=agent_profiles)
    nodes: list[str] = []
    for index, (agent_name, status) in enumerate(statuses):
        color, label = _status_style(status)
        nodes.append(
            (
                '<div class="kaiops-agent-pipeline-node">'
                f'<div class="kaiops-agent-pipeline-step">{index + 1}</div>'
                f'<div class="kaiops-agent-pipeline-name">{html.escape(agent_name)}</div>'
                f'<div class="kaiops-agent-pipeline-status" style="color:{color};">'
                f'<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:{color};margin-right:6px;"></span>'
                f"{html.escape(label)}</div></div>"
            )
        )
    st.markdown(
        '<div class="kaiops-agent-pipeline-wrap">'
        + '<div class="kaiops-agent-pipeline-track">'
        + '<span class="kaiops-agent-pipeline-line"></span>'.join(nodes)
        + "</div></div>",
        unsafe_allow_html=True,
    )


def render_agent_command_center(
    *,
    workflow: dict[str, Any],
    agent_profiles: dict[str, dict[str, str]],
    fallback_icon_data_uri: str,
) -> None:
    alert_payload = workflow.get("alert", {}) if isinstance(workflow, dict) else {}
    alert_name = str(alert_payload.get("name") or alert_payload.get("alert_name") or "").strip()
    if alert_name:
        st.markdown(f"#### Alert: {html.escape(alert_name)}")
    st.markdown("### Agent Command Center")
    events = sorted(workflow.get("events", []), key=lambda item: item.get("sequence", 0))
    work_rows = _fetch_agent_work_items_cached(limit=56)

    render_agent_status_graph(
        events=events,
        work_rows=work_rows,
        agent_profiles=agent_profiles,
    )

    render_agent_role_overview(
        events,
        agent_profiles=agent_profiles,
        fallback_icon_data_uri=fallback_icon_data_uri,
    )
