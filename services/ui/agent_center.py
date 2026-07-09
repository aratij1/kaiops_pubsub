from __future__ import annotations

import os
import json
from typing import Any

import httpx
import streamlit as st

from components import format_event_decision

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
    agents_with_event_state: set[str] = set()

    for event in events:
        agent_name = str(event.get("agent") or "").strip()
        if agent_name:
            decision_token = str(event.get("decision") or "").strip().upper()
            if decision_token in {"PENDING", "QUEUED", "AWAITING_APPROVAL", "AWAITING USER APPROVAL"}:
                status_by_agent[agent_name] = "PENDING"
            else:
                status_by_agent[agent_name] = "COMPLETED"
            agents_with_event_state.add(agent_name)

    for row in work_rows:
        agent_name = str(row.get("agent_name") or "").strip()
        if not agent_name:
            continue
        # Current workflow events are authoritative; use work rows only as fallback.
        if agent_name in agents_with_event_state:
            continue
        row_status = str(row.get("status") or "").strip().upper()
        if row_status:
            status_by_agent[agent_name] = row_status

    return [(agent_name, status_by_agent.get(agent_name, "STANDBY")) for agent_name in agent_profiles.keys()]


def _response_source(event: dict[str, Any]) -> tuple[str, list[str]]:
    notes: list[str] = []
    has_llm = bool(event.get("llm_calls")) or bool(event.get("llm_errors"))

    lowered_parts: list[str] = []
    for key in ("action", "decision", "output"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            lowered_parts.append(value.lower())

    for key in ("input", "metrics"):
        value = event.get(key)
        if isinstance(value, (dict, list)):
            lowered_parts.append(json.dumps(value, default=str).lower())

    decision_value = event.get("decision")
    if isinstance(decision_value, dict):
        lowered_parts.append(json.dumps(decision_value, default=str).lower())

    evidence_text = " ".join(lowered_parts)
    doc_terms = (
        "rag",
        "runbook",
        "related incident",
        "dependency",
        "recent change",
        "scenario evidence",
        "knowledge base",
        "document",
    )
    has_docs = any(term in evidence_text for term in doc_terms)

    if has_llm:
        notes.append("LLM calls present")
    if has_docs:
        notes.append("RAG/runbook/context evidence present")

    if has_llm and has_docs:
        return "MIXED (LLM + DOCS)", notes
    if has_llm:
        return "LLM", notes
    if has_docs:
        return "DOCS", notes
    return "SYSTEM", ["No LLM or document-evidence markers found"]


def _render_flow_graph(events: list[dict[str, Any]], statuses_by_agent: dict[str, str]) -> None:
    if not events:
        return

    color_by_status = {
        "COMPLETED": "#16a34a",
        "PENDING": "#d97706",
        "FAILED": "#dc2626",
    }
    graph_lines = [
        "digraph AgentFlow {",
        '  rankdir=LR;',
        '  node [shape=box, style="rounded,filled", fontname="Segoe UI", fillcolor="#f8fafc", color="#cbd5e1"];',
    ]
    node_ids: list[str] = []
    for idx, event in enumerate(events):
        node_id = f"n{idx}"
        node_ids.append(node_id)
        agent_name = str(event.get("agent") or "Unknown")
        status = _normalize_status_label(statuses_by_agent.get(agent_name, "STANDBY"))
        status_color = color_by_status.get(status, "#64748b")
        seq = str(event.get("sequence") or idx + 1)
        label = f"{seq}. {agent_name}\\n{status.title()}"
        graph_lines.append(f'  {node_id} [label="{label}", color="{status_color}"];')

    for idx in range(len(node_ids) - 1):
        graph_lines.append(f"  {node_ids[idx]} -> {node_ids[idx + 1]};")

    graph_lines.append("}")
    st.graphviz_chart("\n".join(graph_lines), use_container_width=True)


def render_agent_command_center(
    *,
    workflow: dict[str, Any],
    agent_profiles: dict[str, dict[str, str]],
    fallback_icon_data_uri: str,
) -> None:
    events = sorted(workflow.get("events", []), key=lambda item: item.get("sequence", 0))
    work_rows = _fetch_agent_work_items_cached(limit=56)
    status_rows = _latest_status_by_agent(
        events=events,
        work_rows=work_rows,
        agent_profiles=agent_profiles,
    )
    statuses_by_agent = {agent_name: status for agent_name, status in status_rows}
    normalized_statuses = [_normalize_status_label(status) for _, status in status_rows]
    total_agents = len(status_rows)
    completed_count = sum(1 for status in normalized_statuses if status == "COMPLETED")
    pending_count = sum(1 for status in normalized_statuses if status == "PENDING")
    failed_count = sum(1 for status in normalized_statuses if status == "FAILED")
    completion_ratio = float(completed_count / total_agents) if total_agents else 0.0

    metric_columns = st.columns(4)
    metric_columns[0].metric("Agents", total_agents)
    metric_columns[1].metric("Completed", completed_count)
    metric_columns[2].metric("Pending", pending_count)
    metric_columns[3].metric("Failed", failed_count)
    st.progress(completion_ratio, text=f"Flow completion: {int(completion_ratio * 100)}%")

    st.markdown("#### Agent Flow Map")
    _render_flow_graph(events, statuses_by_agent)

    event_by_agent = {str(event.get("agent", "")).strip(): event for event in events}
    step_rows: list[dict[str, Any]] = []
    for index, (agent_name, profile) in enumerate(agent_profiles.items(), start=1):
        event = event_by_agent.get(agent_name, {})
        _, status_label = _status_style(statuses_by_agent.get(agent_name, "STANDBY"))
        decision = format_event_decision(event.get("decision"))
        action = str(event.get("action") or profile.get("mission") or "")
        if len(decision) > 86:
            decision = f"{decision[:83].rstrip()}..."
        if len(action) > 86:
            action = f"{action[:83].rstrip()}..."
        step_rows.append(
            {
                "Step": index,
                "Agent": agent_name,
                "Status": status_label,
                "Decision": decision,
                "Action": action,
            }
        )

    st.markdown("#### Agent Timeline")
    st.dataframe(step_rows, hide_index=True, use_container_width=True)

    selected_agent = ""
    if events:
        selected_agent = st.selectbox(
            "Selected agent",
            options=[str(event.get("agent", "Unknown")) for event in events],
            key="agent_center_selected_agent",
            help="Used for payload inspection and background queue synchronization.",
        )

    if events:
        with st.expander("Inspect Agent Payloads", expanded=False):
            selected_event = next(
                (event for event in events if str(event.get("agent", "Unknown")) == selected_agent),
                {},
            )
            source_label, source_notes = _response_source(selected_event)
            source_cols = st.columns(3)
            source_cols[0].metric("Response Source", source_label)
            source_cols[1].metric("LLM Calls", len(selected_event.get("llm_calls", []) or []))
            source_cols[2].metric("LLM Errors", len(selected_event.get("llm_errors", []) or []))
            if source_notes:
                for note in source_notes:
                    st.caption(f"- {note}")

            st.markdown("**Decision**")
            decision_payload = selected_event.get("decision", "N/A")
            if isinstance(decision_payload, (dict, list)):
                st.json(decision_payload)
            else:
                st.code(format_event_decision(decision_payload), language="text")

            left_col, right_col = st.columns(2)
            with left_col:
                st.markdown("**Input**")
                input_payload = selected_event.get("input", "N/A")
                if isinstance(input_payload, (dict, list)):
                    st.json(input_payload)
                else:
                    st.code(str(input_payload), language="text")
            with right_col:
                st.markdown("**Output**")
                output_payload = selected_event.get("output", "N/A")
                if isinstance(output_payload, (dict, list)):
                    st.json(output_payload)
                else:
                    st.code(str(output_payload), language="text")

            llm_calls = selected_event.get("llm_calls", []) if isinstance(selected_event.get("llm_calls"), list) else []
            if llm_calls:
                st.markdown("**LLM Response Details**")
                st.dataframe(
                    [
                        {
                            "Task": call.get("task", ""),
                            "Provider": call.get("provider", ""),
                            "Model": call.get("model", ""),
                            "Prompt Preview": str(call.get("prompt", ""))[:120],
                        }
                        for call in llm_calls
                        if isinstance(call, dict)
                    ],
                    hide_index=True,
                    use_container_width=True,
                )

    if work_rows:
        with st.expander("Background Work Queue", expanded=False):
            decision = workflow.get("decision", {}) if isinstance(workflow.get("decision"), dict) else {}
            incident = workflow.get("incident", {}) if isinstance(workflow.get("incident"), dict) else {}
            step_sources = [
                "current workflow decision (approval requirement, risk tier, execution mode)",
                "current workflow incident id for incident-specific matching",
                "current workflow events for the live agent handoff sequence",
                "/agent-work/items from the gateway, backed by the MySQL agent_work_items table",
            ]
            st.caption(
                "Queue scope is derived from the live workflow state and agent-work records. "
                "All Work shows every queue item for the current workflow context, while Approval Queue narrows to approval-related agent rows and the current incident."
            )
            st.caption(
                "Inputs considered: " + " | ".join(step_sources) + "."
            )
            queue_cols = st.columns(4)
            with queue_cols[0]:
                queue_scope = st.selectbox(
                    "Queue Scope",
                    options=["All Work", "Approval Queue"],
                    key="agent_center_queue_scope",
                )
            with queue_cols[1]:
                status_filter = st.selectbox(
                    "Status",
                    options=["ALL", "PENDING", "COMPLETED", "FAILED"],
                    key="agent_center_queue_status",
                )
            with queue_cols[2]:
                incident_filter = st.text_input(
                    "Incident Contains",
                    value="",
                    key="agent_center_queue_incident_filter",
                    placeholder="incident id fragment",
                ).strip()
            with queue_cols[3]:
                sync_selected_agent = st.toggle(
                    "Sync selected agent",
                    value=True,
                    key="agent_center_queue_sync_agent",
                    help="When enabled, queue rows are filtered to the selected agent in Agent Flow.",
                )

            selected_incident = str(incident.get("id") or "").strip()
            st.caption(
                "Policy context: "
                f"Risk={str(decision.get('risk_tier') or 'unknown').upper()} | "
                f"Mode={str(decision.get('execution_mode') or 'unknown').upper()} | "
                f"Approval Required={'YES' if bool(decision.get('requires_approval', False)) else 'NO'}"
            )

            filtered_work_rows = [row for row in work_rows if isinstance(row, dict)]
            if incident_filter:
                needle = incident_filter.lower()
                filtered_work_rows = [
                    row
                    for row in filtered_work_rows
                    if needle in str(row.get("incident_id") or "").strip().lower()
                ]
            if queue_scope == "Approval Queue":
                filtered_work_rows = [
                    row
                    for row in filtered_work_rows
                    if "approval" in str(row.get("agent_name") or "").strip().lower()
                ]
                if selected_incident:
                    filtered_work_rows = [
                        row for row in filtered_work_rows if str(row.get("incident_id") or "").strip() == selected_incident
                    ]
            if status_filter != "ALL":
                filtered_work_rows = [
                    row
                    for row in filtered_work_rows
                    if _normalize_status_label(str(row.get("status") or "")) == status_filter
                ]

            if sync_selected_agent and selected_agent:
                selected_lower = selected_agent.strip().lower()
                filtered_work_rows = [
                    row
                    for row in filtered_work_rows
                    if str(row.get("agent_name") or "").strip().lower() == selected_lower
                ]

            if filtered_work_rows:
                status_counts: dict[str, int] = {"PENDING": 0, "COMPLETED": 0, "FAILED": 0}
                for row in filtered_work_rows:
                    normalized = _normalize_status_label(str(row.get("status") or ""))
                    if normalized in status_counts:
                        status_counts[normalized] += 1
                st.markdown("**Queue Status Distribution**")
                st.bar_chart(status_counts)

            st.dataframe(
                [
                    {
                        "Incident": row.get("incident_id", ""),
                        "Agent": row.get("agent_name", ""),
                        "Work": row.get("work_item", ""),
                        "Status": str(row.get("status", "")).upper(),
                        "Updated": row.get("updated_at", ""),
                    }
                    for row in filtered_work_rows[:30]
                ],
                hide_index=True,
                use_container_width=True,
            )

    _ = fallback_icon_data_uri
