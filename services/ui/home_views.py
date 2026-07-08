from __future__ import annotations

import time
from typing import Any, Callable

import streamlit as st

from components import metric_row, render_copyable_id, render_gateway_events, table_from_dict
import message_bus_backend


def render_gateway_safety_view(
    *,
    gateway_response: dict[str, Any],
    gateway: dict[str, Any],
    fetch_observability_summary: Callable[[], dict[str, Any]],
    fetch_observability_recent: Callable[[], dict[str, Any]],
) -> None:
    st.markdown("### Gateway Safety")
    st.caption("Review gateway decision, policy reasons, and safety metrics before closure.")

    if st.session_state.get("auto_refresh_enabled"):
        last_gw = st.session_state.get("last_gateway_refresh_ts")
        last_flow = st.session_state.get("last_flow_refresh_ts")
        status_parts = []
        if last_gw:
            status_parts.append(f"Gateway: {time.strftime('%H:%M:%S', time.localtime(last_gw))}")
        if st.session_state.get("flow_rerun_enabled") and last_flow:
            status_parts.append(f"Flow: {time.strftime('%H:%M:%S', time.localtime(last_flow))}")
        if status_parts:
            st.caption(f"Live mode ON. Last updates: {' | '.join(status_parts)}")
        gateway_interval = int(st.session_state.get("gateway_refresh_interval", 12))
        st.markdown(
            f"<meta http-equiv=\"refresh\" content=\"{gateway_interval}\">",
            unsafe_allow_html=True,
        )

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

    summary = st.session_state.get("gateway_summary") or fetch_observability_summary()
    recent = st.session_state.get("gateway_recent") or fetch_observability_recent()
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


def render_message_bus_view(*, workflow: dict[str, Any] | None = None) -> None:
    st.markdown("### Message Bus")
    st.caption("Configured routing plus latest observed published versus consumed topics.")

    bus_runtime = message_bus_backend.get_message_bus_runtime_config()

    metric_row(
        [
            ("EVENT_BUS_PROVIDER", bus_runtime.get("event_bus_provider", "")),
            ("MESSAGE_BUS_DYNAMIC_ROUTING", str(bus_runtime.get("message_bus_dynamic_routing", "")).upper()),
            ("MESSAGE_BUS_STREAM_THRESHOLD", bus_runtime.get("message_bus_stream_threshold", "")),
            ("MESSAGE_BUS_DEFAULT_PROVIDER", bus_runtime.get("message_bus_default_provider", "")),
            ("MESSAGE_BUS_WORKER_COUNT", bus_runtime.get("message_bus_worker_count", "")),
            ("KAFKA_ENABLED", str(bus_runtime.get("kafka_enabled", "")).upper()),
        ]
    )

    topic_rows = message_bus_backend.get_message_bus_topic_rows()
    actual_activity = message_bus_backend.get_actual_topic_activity(workflow)

    st.markdown("#### Latest Workflow Topic Activity")
    metric_row(
        [
            ("Published Topics", len(actual_activity.get("published", []))),
            ("Consumed Topics", len(actual_activity.get("consumed", []))),
            (
                "Observed Provider",
                str(observed_metrics.get("message_bus_provider", "N/A")).upper()
                if isinstance(observed_metrics := message_bus_backend.extract_observed_routing_metrics(workflow or {}), dict)
                else "N/A",
            ),
        ]
    )

    actual_rows = actual_activity.get("rows", []) if isinstance(actual_activity.get("rows", []), list) else []
    if actual_rows:
        st.dataframe(actual_rows, hide_index=True, width="stretch")
    else:
        st.caption("Run a workflow to capture actual topic activity.")

    actual_topic_col_left, actual_topic_col_right = st.columns(2)
    with actual_topic_col_left:
        st.markdown("#### Actual Topics Published")
        if actual_activity.get("published"):
            st.write("- " + "\n- ".join(str(topic) for topic in actual_activity["published"]))
        else:
            st.caption("No published topics observed yet.")
    with actual_topic_col_right:
        st.markdown("#### Actual Topics Consumed")
        if actual_activity.get("consumed"):
            st.write("- " + "\n- ".join(str(topic) for topic in actual_activity["consumed"]))
        else:
            st.caption("No consumed topics observed yet.")

    st.markdown("#### Configured Topic Topology")
    st.dataframe(topic_rows, hide_index=True, width="stretch")

    st.markdown("#### Observed Routing (Latest Workflow)")
    latest_workflow = workflow or st.session_state.get("workflow") or st.session_state.get("last_workflow") or {}
    observed_metrics = message_bus_backend.extract_observed_routing_metrics(latest_workflow)
    observed_provider = observed_metrics.get("message_bus_provider")
    observed_stream_count = observed_metrics.get("stream_count")
    observed_threshold = observed_metrics.get("stream_threshold")

    if observed_provider is None:
        st.caption("No workflow observation yet. Run a workflow to capture real routing decisions.")
    else:
        metric_row(
            [
                ("Observed Provider", str(observed_provider).upper()),
                ("Observed Stream Count", observed_stream_count),
                ("Observed Threshold", observed_threshold),
            ]
        )

    st.markdown("#### Routing Rule")
    st.write("- When MESSAGE_BUS_DYNAMIC_ROUTING=true: stream_count > MESSAGE_BUS_STREAM_THRESHOLD -> kafka, else rabbitmq.")
    st.write("- When MESSAGE_BUS_DYNAMIC_ROUTING=false: always use MESSAGE_BUS_DEFAULT_PROVIDER.")


def render_finops_view(*, finops: dict[str, Any]) -> None:
    st.markdown("### LLM FinOps")
    if not finops:
        st.info("Run a flow to see token usage and model costs.")
        return

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


def render_closed_incidents_view(
    *,
    closure: dict[str, Any],
    remediation: dict[str, Any],
    fetch_closed_incidents,
) -> None:
    st.markdown("### Closed Incidents")
    col_closed_refresh, _ = st.columns([1, 3])
    with col_closed_refresh:
        if st.button("Refresh Closed Incidents", key="closed_incidents_refresh", width="stretch"):
            fetch_closed_incidents.clear()
            st.rerun()

    closed_rows = fetch_closed_incidents(limit=120)
    if closed_rows:
        risk_values = sorted(
            {
                str(row.get("risk_tier") or row.get("risk") or "unknown").strip().lower()
                for row in closed_rows
                if isinstance(row, dict)
            }
        )
        mode_values = sorted(
            {
                str(row.get("execution_mode") or "unknown").strip().lower()
                for row in closed_rows
                if isinstance(row, dict)
            }
        )
        filter_col_left, filter_col_right = st.columns(2)
        with filter_col_left:
            selected_risks = st.multiselect(
                "Filter by Risk Tier",
                options=risk_values,
                default=risk_values,
                key="closed_incidents_risk_filter",
            )
        with filter_col_right:
            selected_modes = st.multiselect(
                "Filter by Execution Mode",
                options=mode_values,
                default=mode_values,
                key="closed_incidents_mode_filter",
            )

        filtered_rows = [
            row
            for row in closed_rows
            if isinstance(row, dict)
            and str(row.get("risk_tier") or row.get("risk") or "unknown").strip().lower() in set(selected_risks)
            and str(row.get("execution_mode") or "unknown").strip().lower() in set(selected_modes)
        ]

        st.metric("Closed Incidents", len(closed_rows))
        st.caption(f"Showing {len(filtered_rows)} filtered records")
        st.dataframe(
            [
                {
                    "Closed At": row.get("closed_at", ""),
                    "Incident": row.get("incident_id", ""),
                    "Title": row.get("title", ""),
                    "Service": row.get("service", ""),
                    "Severity": row.get("severity", ""),
                    "Risk": row.get("risk_tier", row.get("risk", "")),
                    "Execution Mode": row.get("execution_mode", ""),
                    "Policy Reason": row.get("policy_reason", ""),
                    "Action": row.get("action_type", ""),
                    "Status": row.get("action_status", ""),
                    "Health Restored": "YES" if bool(row.get("health_restored")) else "NO",
                    "Alerts Cleared": "YES" if bool(row.get("alerts_cleared")) else "NO",
                    "Trace": row.get("trace_id", ""),
                }
                for row in filtered_rows
            ],
            hide_index=True,
            width="stretch",
        )

    st.markdown("### Current Closure Report")
    if not closure:
        st.info("Run a flow to generate a closed incident report.")
        return

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


def render_alerts_quick_docs_view(
    *,
    guidance_query: str,
    guidance_open: bool,
    guidance_matches: list[dict[str, Any]],
    recent_alerts: list[dict[str, Any]],
    apply_guidance_selection: Callable[[Any, str], None],
) -> None:
    st.markdown("### Alerts & Quick Docs")
    alerts_rows = [row for row in recent_alerts if isinstance(row, dict)]
    if alerts_rows:
        st.dataframe(
            [
                {
                    "Incident": row.get("id") or row.get("incident_id") or row.get("name"),
                    "Title": row.get("name") or row.get("title") or row.get("description"),
                    "Service": row.get("service"),
                    "Severity": str(row.get("severity", "")).upper(),
                    "Status": row.get("status") or row.get("state") or "open",
                }
                for row in alerts_rows[:40]
            ],
            hide_index=True,
            width="stretch",
        )
    else:
        st.info("No recent alerts available. Use the demo flow from the sidebar to generate one.")

    st.markdown("#### Search Guidance Docs")
    guidance_input_value = st.text_input(
        "Search Guidance",
        value=guidance_query,
        placeholder="payments timeout rollback",
        key="workspace_guidance_query_input",
    )
    guidance_left, guidance_right = st.columns([1, 1])
    with guidance_left:
        if st.button("Search Guidance", key="workspace_guidance_search_btn", use_container_width=True):
            apply_guidance_selection(st.session_state, guidance_input_value)
            st.rerun()
    with guidance_right:
        if st.button("Clear Guidance", key="workspace_guidance_clear_btn", use_container_width=True):
            st.session_state["alerts_guidance_open"] = False
            st.session_state["alerts_guidance_query"] = ""
            st.rerun()

    if guidance_open and guidance_query:
        if guidance_matches:
            for index, match in enumerate(guidance_matches, start=1):
                match_title = str(match.get("title") or match.get("id") or f"Document {index}")
                match_kind = str(match.get("kind") or "reference").replace("_", " ").title()
                match_score = match.get("score")
                score_label = f" | score={float(match_score):.3f}" if isinstance(match_score, (int, float)) else ""
                st.markdown(f"**{index}. {match_title}**")
                st.caption(f"{match_kind}{score_label}")
                snippet = str(match.get("snippet") or match.get("content") or "").strip()
                if snippet:
                    st.write(snippet[:320] + ("..." if len(snippet) > 320 else ""))
        else:
            st.info("No guidance matches found for this query.")


def render_agent_flow_view(
    *,
    workflow: dict[str, Any],
    render_agent_command_center: Callable[..., None],
    agent_profiles: dict[str, dict[str, str]],
    fallback_icon_data_uri: str,
) -> None:
    st.markdown("### Agent Flow")
    if workflow:
        render_agent_command_center(
            workflow=workflow,
            agent_profiles=agent_profiles,
            fallback_icon_data_uri=fallback_icon_data_uri,
        )
    else:
        st.info("Run a flow to visualize the agent handoff sequence.")
