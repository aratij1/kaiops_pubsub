from __future__ import annotations

import html
import os
import time
from typing import Any

import httpx
import streamlit as st

GATEWAY_BASE = os.getenv("API_GATEWAY_URL", "http://localhost:8010")
UI_REQUEST_TIMEOUT_SECONDS = float(os.getenv("UI_REQUEST_TIMEOUT_SECONDS", "240"))

AGENT_PROFILES: dict[str, dict[str, str]] = {
    "Alert Intelligence Agent": {
        "icon": "[ALERT]",
        "mission": "Detects and enriches incoming alert signals.",
        "tone": "signal",
    },
    "Orchestrator Agent": {
        "icon": "[ORCH]",
        "mission": "Selects workflow path and delegates downstream tasks.",
        "tone": "orchestrator",
    },
    "Context Intelligence Agent": {
        "icon": "[CTX]",
        "mission": "Collects dependencies, runbooks, and change evidence.",
        "tone": "context",
    },
    "Resolution Intelligence Agent": {
        "icon": "[RCA]",
        "mission": "Produces root cause analysis and remediation recommendation.",
        "tone": "resolution",
    },
    "Human Approval Layer": {
        "icon": "[APPROVAL]",
        "mission": "Applies policy-aware human gate decisions.",
        "tone": "approval",
    },
    "Remediation Automation Engine": {
        "icon": "[AUTO]",
        "mission": "Executes remediation strategy with auditable output.",
        "tone": "automation",
    },
    "Closure & Validation": {
        "icon": "[CLOSE]",
        "mission": "Validates recovery and records lessons learned.",
        "tone": "closure",
    },
}


def request_json(method: str, url: str, **kwargs) -> dict[str, Any]:
    try:
        with httpx.Client(timeout=UI_REQUEST_TIMEOUT_SECONDS) as client:
            response = client.request(method, url, **kwargs)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as exc:
        st.error(f"Unable to reach {url}. Is the target service running? {exc}")
        return {}


def uploaded_file_to_text(uploaded_file: Any) -> str | None:
    if uploaded_file is None:
        return None
    raw = uploaded_file.getvalue()
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


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


def build_incident_html_report(
        scenario: dict[str, Any],
        incident: dict[str, Any],
        alert: dict[str, Any],
        recommendation: dict[str, Any],
        closure: dict[str, Any],
        remediation: dict[str, Any],
        metrics: dict[str, Any],
        events: list[dict[str, Any]],
        trace_id: str | None,
) -> str:
        title = html.escape(str(scenario.get("title", "KaiOps Incident Report")))
        incident_id = html.escape(str(incident.get("id", "N/A")))
        trace = html.escape(str(trace_id or incident.get("trace_id") or "N/A"))
        alert_name = html.escape(str(alert.get("name", "N/A")))
        alert_service = html.escape(str(alert.get("service", "N/A")))
        alert_severity = html.escape(str(metrics.get("severity", alert.get("severity", "N/A"))).upper())
        recommendation_action = html.escape(str(recommendation.get("recommended_action", "N/A")))
        recommendation_rationale = html.escape(str(recommendation.get("rationale", "N/A")))
        root_cause = html.escape(str(closure.get("root_cause", "N/A")))
        impact = html.escape(str(closure.get("impact", "N/A")))
        action_taken = html.escape(str(closure.get("action_taken", remediation.get("action_type", "N/A"))))

        event_rows = "".join(
                f"<tr><td>{html.escape(str(event.get('sequence', '')))}</td>"
                f"<td>{html.escape(str(event.get('agent', '')))}</td>"
                f"<td>{html.escape(str(event.get('decision', '')))}</td></tr>"
                for event in events
        )

        return f"""
<!doctype html>
<html lang=\"en\">
<head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>{title}</title>
    <style>
        body {{ font-family: Segoe UI, Arial, sans-serif; margin: 24px; color: #0f172a; }}
        h1 {{ margin-bottom: 4px; }}
        .meta {{ color: #475569; margin-bottom: 18px; }}
        .card {{ border: 1px solid #dbe4ef; border-radius: 10px; padding: 12px 14px; margin-bottom: 12px; }}
        .label {{ color: #475569; font-size: 0.9rem; }}
        table {{ border-collapse: collapse; width: 100%; }}
        th, td {{ border: 1px solid #dbe4ef; text-align: left; padding: 8px; font-size: 0.9rem; }}
        th {{ background: #f8fafc; }}
    </style>
</head>
<body>
    <h1>{title}</h1>
    <div class=\"meta\">Incident ID: {incident_id} | Trace ID: {trace}</div>

    <div class=\"card\">
        <div class=\"label\">Alert</div>
        <div><strong>{alert_name}</strong> | Service: {alert_service} | Severity: {alert_severity}</div>
    </div>

    <div class=\"card\">
        <div class=\"label\">Recommendation</div>
        <div><strong>{recommendation_action}</strong></div>
        <div>{recommendation_rationale}</div>
    </div>

    <div class=\"card\">
        <div class=\"label\">Closure Summary</div>
        <div>Root Cause: {root_cause}</div>
        <div>Impact: {impact}</div>
        <div>Action Taken: {action_taken}</div>
        <div>Health Restored: {html.escape(str(closure.get('health_restored', False)))}</div>
        <div>Alerts Cleared: {html.escape(str(closure.get('alerts_cleared', False)))}</div>
    </div>

    <div class=\"card\">
        <div class=\"label\">Agent Trace</div>
        <table>
            <thead><tr><th>Step</th><th>Agent</th><th>Decision</th></tr></thead>
            <tbody>{event_rows}</tbody>
        </table>
    </div>
</body>
</html>
""".strip()


def build_rag_grounding_query(
        scenario: dict[str, Any],
        alert: dict[str, Any],
        context: dict[str, Any],
        recommendation: dict[str, Any],
        closure: dict[str, Any],
) -> str:
        terms: list[str] = []
        for value in [
            alert.get("name"),
            alert.get("service"),
            alert.get("environment"),
            scenario.get("title"),
            recommendation.get("recommended_action"),
            closure.get("root_cause"),
            context.get("deployment"),
        ]:
            text = str(value or "").strip()
            if text:
                terms.append(text)

        dependencies = context.get("dependency_services", [])
        if isinstance(dependencies, list):
            for item in dependencies[:4]:
                dependency = str(item or "").strip()
                if dependency:
                    terms.append(dependency)

        deduped_terms: list[str] = []
        for item in terms:
            if item not in deduped_terms:
                deduped_terms.append(item)

        return " ".join(deduped_terms[:12])


def get_grounded_rag_search(
        scenario: dict[str, Any],
        alert: dict[str, Any],
        context: dict[str, Any],
        recommendation: dict[str, Any],
        closure: dict[str, Any],
) -> dict[str, Any]:
        query = build_rag_grounding_query(
            scenario=scenario,
            alert=alert,
            context=context,
            recommendation=recommendation,
            closure=closure,
        )
        if not query:
            return st.session_state.get("rag_search", {})

        cached_query = st.session_state.get("rag_grounding_query")
        cached_result = st.session_state.get("rag_grounding", {})
        if cached_query == query and cached_result:
            return cached_result

        grounded = request_json(
            "GET",
            f"{GATEWAY_BASE}/rag/search",
            params={"query": query, "limit": 8},
        )
        if grounded:
            st.session_state["rag_grounding_query"] = query
            st.session_state["rag_grounding"] = grounded
            return grounded

        return st.session_state.get("rag_search", {})


def build_complete_webpage_html(
                scenario: dict[str, Any],
                incident: dict[str, Any],
                alert: dict[str, Any],
                context: dict[str, Any],
                recommendation: dict[str, Any],
                remediation: dict[str, Any],
                closure: dict[str, Any],
                metrics: dict[str, Any],
                finops: dict[str, Any],
                events: list[dict[str, Any]],
                gateway_response: dict[str, Any],
                gateway_summary: dict[str, Any],
                gateway_recent: dict[str, Any],
                catalog_entries: list[dict[str, Any]],
                rag_search_response: dict[str, Any],
) -> str:
                title = html.escape(str(scenario.get("title", "KaiOps Homepage Export")))
                incident_id = html.escape(str(incident.get("id", "N/A")))
                trace_id = html.escape(str(gateway_response.get("trace_id") or incident.get("trace_id") or "N/A"))
                alert_name = html.escape(str(alert.get("name", "N/A")))
                alert_service = html.escape(str(alert.get("service", "N/A")))
                alert_environment = html.escape(str(alert.get("environment", "N/A")))
                generated_at = html.escape(time.strftime("%Y-%m-%d %H:%M:%S"))

                def kv_rows(values: dict[str, Any]) -> str:
                        if not values:
                                return "<tr><td colspan='2'>No data</td></tr>"
                        return "".join(
                                f"<tr><th>{html.escape(str(key).replace('_', ' ').title())}</th><td>{html.escape(str(value))}</td></tr>"
                                for key, value in values.items()
                        )

                event_rows = "".join(
                        "<tr>"
                        f"<td>{html.escape(str(event.get('sequence', '')))}</td>"
                        f"<td>{html.escape(str(event.get('agent', '')))}</td>"
                        f"<td>{html.escape(str(event.get('decision', '')))}</td>"
                        f"<td>{html.escape(str(event.get('communicates_to', '')))}</td>"
                        "</tr>"
                        for event in sorted(events, key=lambda item: item.get("sequence", 0))
                ) or "<tr><td colspan='4'>No events</td></tr>"

                finops_totals = finops.get("totals", {}) if isinstance(finops, dict) else {}
                finops_provider_rows = "".join(
                        "<tr>"
                        f"<td>{html.escape(str(row.get('provider', '')))}</td>"
                        f"<td>{html.escape(str(row.get('calls', '')))}</td>"
                        f"<td>{html.escape(str(row.get('total_tokens', '')))}</td>"
                        f"<td>${float(row.get('total_cost_usd', 0.0)):.6f}</td>"
                        "</tr>"
                        for row in finops.get("by_provider", [])
                ) if isinstance(finops, dict) else ""
                if not finops_provider_rows:
                        finops_provider_rows = "<tr><td colspan='4'>No provider cost records</td></tr>"

                recent_events = gateway_recent.get("events", []) if isinstance(gateway_recent, dict) else []
                gateway_recent_rows = "".join(
                        "<tr>"
                        f"<td>{html.escape(str(row.get('trace_id', '')))}</td>"
                        f"<td>{html.escape(str(row.get('path', '')))}</td>"
                        f"<td>{html.escape(str(row.get('status_code', '')))}</td>"
                        f"<td>{html.escape(str(row.get('safety', {}).get('decision', '')))}</td>"
                        f"<td>{html.escape(str(round(float(row.get('latency_ms', 0)), 2)))}</td>"
                        "</tr>"
                        for row in recent_events
                ) or "<tr><td colspan='5'>No gateway events</td></tr>"

                catalog_rows = "".join(
                        "<tr>"
                        f"<td>{html.escape(str(item.get('id', '')))}</td>"
                        f"<td>{html.escape(str(item.get('title', '')))}</td>"
                        f"<td>{html.escape(str(item.get('service', '')))}</td>"
                        f"<td>{html.escape(str(item.get('severity', '')))}</td>"
                        "</tr>"
                        for item in catalog_entries[:60]
                ) or "<tr><td colspan='4'>No flow catalog entries</td></tr>"

                search_matches = data_from_gateway(rag_search_response).get("matches", []) if rag_search_response else []
                search_rows = "".join(
                        "<tr>"
                        f"<td>{html.escape(str(item.get('kind', '')))}</td>"
                        f"<td>{html.escape(str(item.get('title', '')))}</td>"
                        f"<td>{html.escape(str(item.get('deployment', '')))}</td>"
                        f"<td>{html.escape(str(item.get('preview', '')))}</td>"
                        "</tr>"
                        for item in search_matches[:50]
                ) or "<tr><td colspan='4'>No grounded RAG matches available</td></tr>"

                return f"""
<!doctype html>
<html lang=\"en\">
<head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>KaiOps Homepage Export</title>
    <style>
        body {{ font-family: Segoe UI, Arial, sans-serif; margin: 22px; color: #0f172a; background: #f8fafc; }}
        h1 {{ margin-bottom: 0.2rem; }}
        .meta {{ color: #475569; margin-bottom: 14px; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }}
        .card {{ background: #fff; border: 1px solid #dbe4ef; border-radius: 12px; padding: 12px; margin-bottom: 12px; }}
        .card h2 {{ margin: 0 0 8px; font-size: 1.02rem; }}
        table {{ border-collapse: collapse; width: 100%; }}
        th, td {{ border: 1px solid #dbe4ef; padding: 7px; text-align: left; font-size: 0.88rem; vertical-align: top; }}
        th {{ background: #f1f5f9; }}
        code {{ background: #e2e8f0; padding: 1px 6px; border-radius: 6px; }}
    </style>
</head>
<body>
    <h1>KaiOps Autonomous Operations</h1>
    <div class=\"meta\">Generated: {generated_at} | Incident ID: {incident_id} | Trace ID: {trace_id}</div>

    <div class=\"grid\">
        <div class=\"card\">
            <h2>Incident Snapshot</h2>
            <p><b>Flow:</b> {title}</p>
            <p><b>Alert:</b> {alert_name}</p>
            <p><b>Service:</b> {alert_service}</p>
            <p><b>Environment:</b> {alert_environment}</p>
        </div>
        <div class=\"card\">
            <h2>Recommendation</h2>
            <p><b>Action:</b> {html.escape(str(recommendation.get('recommended_action', 'N/A')))}</p>
            <p>{html.escape(str(recommendation.get('rationale', 'N/A')))}</p>
            <p><b>Remediation:</b> {html.escape(str(remediation.get('action_type', remediation.get('status', 'N/A'))))}</p>
        </div>
        <div class=\"card\">
            <h2>Closure</h2>
            <p><b>Root Cause:</b> {html.escape(str(closure.get('root_cause', 'N/A')))}</p>
            <p><b>Impact:</b> {html.escape(str(closure.get('impact', 'N/A')))}</p>
            <p><b>Action Taken:</b> {html.escape(str(closure.get('action_taken', 'N/A')))}</p>
        </div>
    </div>

    <div class=\"card\">
        <h2>Metrics</h2>
        <table>{kv_rows(metrics)}</table>
    </div>

    <div class=\"card\">
        <h2>Context</h2>
        <table>{kv_rows(context)}</table>
    </div>

    <div class=\"card\">
        <h2>Agent Trace</h2>
        <table>
            <thead><tr><th>Step</th><th>Agent</th><th>Decision</th><th>Communicates To</th></tr></thead>
            <tbody>{event_rows}</tbody>
        </table>
    </div>

    <div class=\"card\">
        <h2>Gateway Summary</h2>
        <table>{kv_rows(gateway_summary if isinstance(gateway_summary, dict) else {})}</table>
    </div>

    <div class=\"card\">
        <h2>Recent Gateway Events</h2>
        <table>
            <thead><tr><th>Trace ID</th><th>Path</th><th>Status</th><th>Decision</th><th>Latency ms</th></tr></thead>
            <tbody>{gateway_recent_rows}</tbody>
        </table>
    </div>

    <div class=\"card\">
        <h2>FinOps Totals</h2>
        <table>{kv_rows(finops_totals if isinstance(finops_totals, dict) else {})}</table>
        <h2 style=\"margin-top: 12px;\">FinOps by Provider</h2>
        <table>
            <thead><tr><th>Provider</th><th>Calls</th><th>Tokens</th><th>Cost USD</th></tr></thead>
            <tbody>{finops_provider_rows}</tbody>
        </table>
    </div>

    <div class=\"card\">
        <h2>Flow Catalog (sidebar)</h2>
        <table>
            <thead><tr><th>ID</th><th>Title</th><th>Service</th><th>Severity</th></tr></thead>
            <tbody>{catalog_rows}</tbody>
        </table>
    </div>

    <div class=\"card\">
        <h2>RAG Search Results (sidebar)</h2>
        <table>
            <thead><tr><th>Kind</th><th>Title</th><th>Deployment</th><th>Preview</th></tr></thead>
            <tbody>{search_rows}</tbody>
        </table>
    </div>
</body>
</html>
""".strip()


def render_alert_stream(entries: list[dict[str, Any]]) -> str | None:
    if not entries:
        st.caption("No alert stream entries available yet.")
        return None
    selected_flow_id: str | None = None
    for item in entries[:12]:
        alert_id = str(item.get("alert_id") or item.get("id") or "N/A")
        alert_name = str(item.get("alert_name") or item.get("title") or "Alert")
        service = str(item.get("service") or "unknown")
        severity = str(item.get("severity") or "unknown").upper()
        alert_type = str(item.get("alert_type") or "").strip()
        flow_id = str(item.get("id") or "").strip()
        button_label = f"{alert_id} | {alert_name}"
        if flow_id and st.button(
            button_label,
            key=f"kaiops_alert_stream_{flow_id}",
            width="stretch",
        ):
            selected_flow_id = flow_id
        st.caption(f"{service} · {severity}{(' · ' + alert_type) if alert_type else ''}")
    return selected_flow_id


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
            llm_calls = event.get("llm_calls", [])
            if llm_calls:
                st.markdown("#### LLM prompt and response details")
                for index, call in enumerate(llm_calls, start=1):
                    title = (
                        f"LLM Call {index}: {call.get('task')} "
                        f"via {call.get('provider')} / {call.get('model')}"
                    )
                    with st.expander(title):
                        st.markdown("**Input prompt**")
                        st.code(str(call.get("prompt", "")), language="text")
                        st.markdown("**Input payload sent to LLM**")
                        st.json(call.get("payload", {}))
                        st.markdown("**Response received from LLM**")
                        st.code(str(call.get("response", "")), language="text")
                        st.markdown("**Token and cost metadata**")
                        table_from_dict(call.get("usage", {}))
            llm_errors = event.get("llm_errors", [])
            if llm_errors:
                st.markdown("#### LLM errors")
                for error in llm_errors:
                    with st.expander(f"{error.get('provider')} / {error.get('task')} error"):
                        st.markdown("**Input prompt**")
                        st.code(str(error.get("prompt", "")), language="text")
                        st.markdown("**Input payload**")
                        st.code(str(error.get("payload", "")), language="text")
                        st.markdown("**Error**")
                        st.error(str(error.get("error", "")))


def get_agent_profile(agent_name: str) -> dict[str, str]:
    return AGENT_PROFILES.get(
        agent_name,
        {"icon": "[AGENT]", "mission": "Coordinates incident-resolution logic.", "tone": "default"},
    )


def agent_kpis(event: dict[str, Any]) -> dict[str, int]:
    return {
        "calls": len(event.get("llm_calls", [])),
        "errors": len(event.get("llm_errors", [])),
        "signals": len(event.get("metrics", {})),
    }


def render_agent_event_details(event: dict[str, Any]) -> None:
    profile = get_agent_profile(str(event.get("agent", "")))
    st.markdown(f"### {profile.get('icon', '[AGENT]')} {event.get('agent', 'Agent')} | Deep Dive")
    st.caption(profile.get("mission", "Coordinates incident-resolution logic."))
    left, right = st.columns([1.5, 1])
    with left:
        st.markdown("#### Action")
        st.write(event.get("action", "N/A"))
        st.markdown("#### Input")
        event_input = event.get("input", "N/A")
        if isinstance(event_input, (dict, list)):
            st.json(event_input)
        else:
            st.code(str(event_input), language="text")
        st.markdown("#### Decision")
        st.info(str(event.get("decision", "N/A")))
        st.markdown("#### Output")
        event_output = event.get("output", "N/A")
        if isinstance(event_output, (dict, list)):
            st.json(event_output)
        else:
            st.code(str(event_output), language="text")
        st.markdown("#### Communicates To")
        st.write(event.get("communicates_to", "N/A"))
    with right:
        st.markdown("#### Agent Metrics")
        table_from_dict(event.get("metrics", {}), "Metric", "Value")

    llm_calls = event.get("llm_calls", [])
    if llm_calls:
        st.markdown("#### LLM Calls")
        for index, call in enumerate(llm_calls, start=1):
            with st.expander(f"Call {index}: {call.get('task')} via {call.get('provider')} / {call.get('model')}"):
                st.markdown("**Prompt**")
                st.code(str(call.get("prompt", "")), language="text")
                st.markdown("**Payload**")
                st.json(call.get("payload", {}))
                st.markdown("**Response**")
                st.code(str(call.get("response", "")), language="text")
                st.markdown("**Usage**")
                table_from_dict(call.get("usage", {}), "Metric", "Value")

    llm_errors = event.get("llm_errors", [])
    if llm_errors:
        st.markdown("#### LLM Errors")
        for error in llm_errors:
            with st.expander(f"{error.get('provider')} / {error.get('task')} error"):
                st.markdown("**Prompt**")
                st.code(str(error.get("prompt", "")), language="text")
                st.markdown("**Payload**")
                st.code(str(error.get("payload", "")), language="text")
                st.error(str(error.get("error", "")))


def render_handoff_path(events: list[dict[str, Any]]) -> None:
    ordered = sorted(events, key=lambda item: item.get("sequence", 0))
    if not ordered:
        return

    nodes = []
    for index, event in enumerate(ordered):
        profile = get_agent_profile(str(event.get("agent", "")))
        nodes.append(
            """
            <div class=\"kaiops-flow-node kaiops-tone-{tone}\">
              <div class=\"kaiops-flow-node-step\">{step}</div>
              <div class=\"kaiops-flow-node-label\">{icon} {label}</div>
            </div>
            """.format(
                                tone=html.escape(str(profile.get("tone", "default"))),
                                step=html.escape(str(event.get("sequence", "-"))),
                                icon=html.escape(str(profile.get("icon", "[AGENT]"))),
                                label=html.escape(str(event.get("agent", "Agent"))),
            )
        )
        if index < len(ordered) - 1:
            nodes.append('<div class="kaiops-flow-link"></div>')

    st.markdown("<div class=\"kaiops-flow-wrap\">" + "".join(nodes) + "</div>", unsafe_allow_html=True)


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


st.set_page_config(page_title="KaiOps", page_icon="K", layout="wide")

st.markdown(
    """
    <style>
      .stApp {
        background:
          radial-gradient(1100px 450px at 8% -10%, rgba(251, 191, 36, 0.16), transparent 60%),
          radial-gradient(900px 550px at 100% 0%, rgba(14, 165, 233, 0.14), transparent 60%),
          linear-gradient(180deg, #f7fafc 0%, #f1f5f9 100%);
      }
      .block-container {padding-top: 1.2rem; max-width: 1280px;}
      div[data-testid="stMetric"] {
        background: linear-gradient(145deg, #0f172a, #1e293b);
        border: 1px solid #334155;
        border-radius: 16px;
        padding: 14px;
        box-shadow: 0 14px 28px rgba(15, 23, 42, 0.14);
      }
      div[data-testid="stMetric"] label, div[data-testid="stMetric"] div {
        color: #f8fafc !important;
      }
      .kaiops-card {
        background: linear-gradient(180deg, #ffffff, #f8fafc);
        border: 1px solid #dbe4ef;
        border-radius: 16px;
        padding: 18px;
        margin-bottom: 12px;
        box-shadow: 0 14px 30px rgba(15, 23, 42, 0.08);
      }
      .kaiops-hero {
        background: linear-gradient(120deg, #0f172a 0%, #1d4ed8 42%, #0ea5e9 100%);
        border-radius: 20px;
        padding: 22px;
        color: #e2e8f0;
        margin-bottom: 16px;
        box-shadow: 0 20px 36px rgba(15, 23, 42, 0.22);
      }
      .kaiops-hero h2 {
        margin: 0;
        color: #ffffff;
        font-size: 1.55rem;
        letter-spacing: 0.01em;
      }
      .kaiops-hero p {
        margin-top: 0.35rem;
        margin-bottom: 0;
        color: #dbeafe;
        font-size: 0.98rem;
      }
      .kaiops-agent-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        gap: 12px;
        margin: 0.4rem 0 0.9rem 0;
      }
      .kaiops-agent-card {
        border-radius: 16px;
        padding: 14px 14px 12px;
        border: 1px solid #dbe4ef;
        background: #ffffff;
        box-shadow: 0 10px 18px rgba(15, 23, 42, 0.06);
      }
      .kaiops-agent-top {
        display: flex;
        align-items: center;
        justify-content: space-between;
      }
      .kaiops-agent-icon { font-size: 0.75rem; font-weight: 700; }
      .kaiops-agent-step {
        font-size: 0.73rem;
        background: rgba(15, 23, 42, 0.08);
        padding: 3px 8px;
        border-radius: 999px;
      }
      .kaiops-agent-name {
        font-size: 0.95rem;
        font-weight: 700;
        margin-top: 8px;
        color: #0f172a;
      }
      .kaiops-agent-mission {
        font-size: 0.8rem;
        color: #334155;
        margin-top: 4px;
        min-height: 2.2rem;
      }
      .kaiops-agent-kpis {
        margin-top: 8px;
        display: flex;
        gap: 6px;
        flex-wrap: wrap;
      }
      .kaiops-kpi-pill {
        font-size: 0.67rem;
        font-weight: 600;
        background: #e2e8f0;
        color: #0f172a;
        border-radius: 999px;
        padding: 3px 8px;
      }
      .kaiops-agent-decision {
        margin-top: 8px;
        font-size: 0.76rem;
        color: #1e293b;
        background: #f8fafc;
        border-radius: 10px;
        padding: 8px;
      }
      .kaiops-flow-wrap {
        display: flex;
        align-items: center;
        overflow-x: auto;
        gap: 8px;
        padding: 8px 4px 12px;
        margin-bottom: 8px;
      }
      .kaiops-flow-node {
        min-width: 170px;
        border: 1px solid #dbe4ef;
        border-radius: 12px;
        background: #ffffff;
        padding: 10px;
        box-shadow: 0 6px 12px rgba(15, 23, 42, 0.06);
      }
      .kaiops-flow-node-step {
        font-size: 0.7rem;
        color: #475569;
        font-weight: 600;
      }
      .kaiops-flow-node-label {
        font-size: 0.8rem;
        color: #0f172a;
        margin-top: 4px;
        font-weight: 700;
      }
      .kaiops-flow-link {
        position: relative;
        width: 52px;
        height: 2px;
        background: #94a3b8;
        overflow: hidden;
      }
      .kaiops-flow-link::after {
        content: "";
        position: absolute;
        left: -20px;
        top: 0;
        width: 20px;
        height: 2px;
        background: #0ea5e9;
        animation: kaiops-flow-move 1.3s linear infinite;
      }
      @keyframes kaiops-flow-move {
        from { transform: translateX(0); }
        to { transform: translateX(72px); }
      }
      .kaiops-tone-orchestrator { border-top: 4px solid #1d4ed8; }
      .kaiops-tone-context { border-top: 4px solid #0ea5e9; }
      .kaiops-tone-resolution { border-top: 4px solid #f97316; }
      .kaiops-tone-approval { border-top: 4px solid #14b8a6; }
      .kaiops-tone-automation { border-top: 4px solid #16a34a; }
      .kaiops-tone-closure { border-top: 4px solid #7c3aed; }
      .kaiops-tone-signal { border-top: 4px solid #eab308; }
      .kaiops-tone-default { border-top: 4px solid #64748b; }
            section[data-testid="stSidebar"] {
                background: linear-gradient(180deg, #f8fafc 0%, #eef2ff 100%);
            }
            section[data-testid="stSidebar"] .block-container {
                padding-top: 0.8rem;
            }
            .kaiops-sidebar-hero {
                background: linear-gradient(135deg, #0f172a 0%, #1d4ed8 60%, #0ea5e9 100%);
                border-radius: 14px;
                padding: 12px 12px 10px;
                color: #e2e8f0;
                margin-bottom: 10px;
                box-shadow: 0 10px 18px rgba(15, 23, 42, 0.18);
            }
            .kaiops-sidebar-hero h3 {
                margin: 0;
                font-size: 0.98rem;
                color: #ffffff;
            }
            .kaiops-sidebar-hero p {
                margin: 4px 0 0;
                font-size: 0.76rem;
                color: #dbeafe;
            }
            .kaiops-sidebar-section {
                margin: 0.35rem 0 0.5rem;
                font-size: 0.75rem;
                letter-spacing: 0.04em;
                text-transform: uppercase;
                color: #334155;
                font-weight: 700;
            }

      @media (max-width: 920px) {
        .kaiops-hero h2 { font-size: 1.25rem; }
        .kaiops-agent-grid { grid-template-columns: 1fr; }
      }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="kaiops-hero">
      <h2>KaiOps Autonomous Operations</h2>
      <p>Interactive operations cockpit for agent handoffs, approvals, remediation, and FinOps visibility.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

flows = get_flows()
severity_levels = sorted({str(flow.get("severity", "unknown")).upper() for flow in flows})
workflow = st.session_state.get("workflow", {})
if "kaiops_selected_severities" not in st.session_state:
    st.session_state["kaiops_selected_severities"] = severity_levels
if "flow_catalog_preview" not in st.session_state:
    st.session_state["flow_catalog_preview"] = {
        "data": {"entries": flows, "count": len(flows), "path": "rag/flows.json"}
    }
catalog_preview = st.session_state.get("flow_catalog_preview")
catalog_entries = data_from_gateway(catalog_preview).get("entries", []) if catalog_preview else flows

with st.sidebar:
    st.markdown(
        """
        <div class="kaiops-sidebar-hero">
          <h3>Mission Control</h3>
          <p>Operate flow execution, monitoring, and RAG intelligence from one panel.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="kaiops-sidebar-section">Alert Stream</div>', unsafe_allow_html=True)
    with st.container(border=True):
        if catalog_entries:
            selected_from_stream = render_alert_stream(catalog_entries)
            if selected_from_stream:
                st.session_state["selected_flow_from_stream"] = selected_from_stream
                st.session_state["run_flow_from_stream_click"] = True
        else:
            st.caption("Load the catalog or ingest incident documents to populate the live alert stream.")

    st.markdown('<div class="kaiops-sidebar-section">Flow Control</div>', unsafe_allow_html=True)
    with st.container(border=True):
        pending_flow = st.session_state.pop("selected_flow_from_stream", None)
        run_from_stream = bool(st.session_state.pop("run_flow_from_stream_click", False))
        if pending_flow:
            st.session_state["selected_flow"] = pending_flow
            matched = next((flow for flow in flows if str(flow.get("id")) == pending_flow), None)
            if matched:
                st.session_state["kaiops_selected_severities"] = [str(matched.get("severity", "")).upper()]

        selected_severities = st.multiselect(
            "Severity",
            options=severity_levels,
            key="kaiops_selected_severities",
        )

        filtered_flows = [
            flow
            for flow in flows
            if (not selected_severities or str(flow.get("severity", "")).upper() in selected_severities)
        ]

        if not filtered_flows:
            filtered_flows = flows

        flow_options = {
            f"{flow.get('alert_id', flow['id']).upper()} | {flow.get('alert_name', flow['title'])} | {flow['service']} | {str(flow['severity']).upper()}": flow["id"]
            for flow in filtered_flows
        }

        selected_flow_id = st.session_state.get("selected_flow", "payment-latency")
        flow_labels = list(flow_options)
        default_label = next(
            (label for label, flow_id in flow_options.items() if flow_id == selected_flow_id), flow_labels[0]
        )
        if (
            "kaiops_selected_flow_label" not in st.session_state
            or st.session_state["kaiops_selected_flow_label"] not in flow_labels
            or pending_flow
        ):
            st.session_state["kaiops_selected_flow_label"] = default_label

        selected_label = st.selectbox("Search flow", flow_labels, key="kaiops_selected_flow_label")
        selected_flow = flow_options.get(selected_label, "payment-latency")
        st.session_state["selected_flow"] = selected_flow

        if pending_flow:
            st.success(f"Selected {selected_flow} from alert stream")

        if run_from_stream and pending_flow:
            gateway_response = request_json("POST", f"{GATEWAY_BASE}/sample/{selected_flow}/workflow")
            if gateway_response:
                st.session_state["gateway_response"] = gateway_response
                st.session_state["workflow"] = gateway_response.get("data", {})
                st.session_state["last_flow_refresh_ts"] = time.time()
                st.success("Flow executed from alert stream click.")

        if st.button("Run Selected Flow", type="primary", width="stretch"):
            gateway_response = request_json("POST", f"{GATEWAY_BASE}/sample/{selected_flow}/workflow")
            if gateway_response:
                st.session_state["gateway_response"] = gateway_response
                st.session_state["workflow"] = gateway_response.get("data", {})
                st.session_state["last_flow_refresh_ts"] = time.time()
                st.success("Flow completed.")

    st.markdown('<div class="kaiops-sidebar-section">Agent Trace</div>', unsafe_allow_html=True)
    with st.container(border=True):
        events_for_sidebar = sorted(workflow.get("events", []), key=lambda item: item.get("sequence", 0))
        if events_for_sidebar:
            trace_step_options = [
                f"Step {event.get('sequence', '-')}: {event.get('agent', 'Agent')}" for event in events_for_sidebar
            ]
            default_trace_step = st.session_state.get("selected_trace_step", trace_step_options[-1])
            if default_trace_step not in trace_step_options:
                default_trace_step = trace_step_options[-1]
            selected_trace_step = st.selectbox(
                "Flow step",
                options=trace_step_options,
                index=trace_step_options.index(default_trace_step),
            )
            st.session_state["selected_trace_step"] = selected_trace_step
        else:
            st.caption("Run Flow to enable step drill-down.")
            st.session_state.pop("selected_trace_step", None)

    st.markdown('<div class="kaiops-sidebar-section">Live Monitoring</div>', unsafe_allow_html=True)
    with st.container(border=True):
        auto_refresh_enabled = st.toggle(
            "Auto-refresh observability",
            value=st.session_state.get("auto_refresh_enabled", False),
            help="Keep gateway and incident data continuously updated.",
        )
        st.session_state["auto_refresh_enabled"] = auto_refresh_enabled

        if auto_refresh_enabled:
            gateway_interval = st.slider(
                "Gateway refresh (seconds)",
                min_value=5,
                max_value=60,
                value=int(st.session_state.get("gateway_refresh_interval", 12)),
                step=1,
            )
            st.session_state["gateway_refresh_interval"] = gateway_interval

            flow_rerun_enabled = st.toggle(
                "Demo: Auto-rerun flow",
                value=st.session_state.get("flow_rerun_enabled", False),
                help="Run the selected flow periodically to generate new incidents for demo.",
            )
            st.session_state["flow_rerun_enabled"] = flow_rerun_enabled

            if flow_rerun_enabled:
                flow_interval = st.slider(
                    "Flow rerun interval (seconds)",
                    min_value=15,
                    max_value=300,
                    value=int(st.session_state.get("flow_rerun_interval", 60)),
                    step=5,
                )
                st.session_state["flow_rerun_interval"] = flow_interval
                st.caption(f"Gateway: {gateway_interval}s | Flow: {flow_interval}s")

        if st.button("Refresh Gateway Events", width="stretch"):
            st.session_state["gateway_summary"] = request_json("GET", f"{GATEWAY_BASE}/observability/summary")
            st.session_state["gateway_recent"] = request_json("GET", f"{GATEWAY_BASE}/observability/recent")
            st.session_state["last_gateway_refresh_ts"] = time.time()

    st.markdown('<div class="kaiops-sidebar-section">RAG Workspace</div>', unsafe_allow_html=True)
    with st.container(border=True):
        col_reload, col_list = st.columns(2)
        if col_reload.button("Reload Index", width="stretch"):
            st.session_state["rag_reload"] = request_json("POST", f"{GATEWAY_BASE}/rag/reload")
        if col_list.button("List Docs", width="stretch"):
            st.session_state["rag_documents"] = request_json("GET", f"{GATEWAY_BASE}/rag/documents")

        if st.session_state.get("rag_reload"):
            reloaded_count = data_from_gateway(st.session_state["rag_reload"]).get("document_count")
            st.success(f"RAG reloaded: {reloaded_count} docs")

        search_query = st.text_input("Search RAG", placeholder="payments latency rollback", key="sidebar_rag_search")
        if st.button("Search", width="stretch", disabled=not search_query):
            st.session_state["rag_search"] = request_json(
                "GET", f"{GATEWAY_BASE}/rag/search", params={"query": search_query, "limit": 8}
            )

    with st.expander("Ingest document"):
        with st.form("rag_ingest_form"):
            kind = st.selectbox("Type", ["runbook", "incident", "deployment", "change", "dependency"])
            title = st.text_input("Title", placeholder="Payments rollback")
            uploaded_docs = st.file_uploader(
                "Upload document files",
                accept_multiple_files=True,
                help="Select one or more document files to ingest.",
            )
            services_text = st.text_input("Services", placeholder="payments, checkout")
            deployment = st.text_input("Deployment", placeholder="2.5")
            dependencies_text = st.text_input("Dependencies", placeholder="checkout, ledger")
            change_id = st.text_input("Change ID", placeholder="CHG-1234")
            issue_severity = st.selectbox("Issue severity", ["CRITICAL", "HIGH", "WARNING"], index=1)
            suggested_action = st.text_input("Suggested action", placeholder="Rollback deployment")
            content = st.text_area(
                "Content",
                height=100,
                placeholder="Paste runbook, incident, deployment, dependency graph, or change-record...",
            )
            submitted = st.form_submit_button("Ingest", type="primary")

        if submitted:
            docs_to_ingest: list[dict[str, Any]] = []
            upload_failures: list[str] = []
            base_title = (title or "").strip()

            for uploaded_doc in uploaded_docs or []:
                uploaded_text = uploaded_file_to_text(uploaded_doc)
                if uploaded_text is None:
                    upload_failures.append(str(getattr(uploaded_doc, "name", "unknown-file")))
                    continue
                file_name = str(getattr(uploaded_doc, "name", "uploaded-document"))
                file_title = file_name.rsplit(".", 1)[0]
                docs_to_ingest.append(
                    {
                        "title": file_title,
                        "content": uploaded_text.strip(),
                        "metadata": {
                            "source": "ui-upload",
                            "uploaded_filename": file_name,
                        },
                    }
                )

            typed_content = (content or "").strip()
            if typed_content:
                docs_to_ingest.append(
                    {
                        "title": base_title or "manual-entry",
                        "content": typed_content,
                        "metadata": {
                            "source": "ui",
                            "uploaded_filename": None,
                        },
                    }
                )

            if not docs_to_ingest:
                st.warning("Provide document content or upload one or more files before ingesting.")
            else:
                successes = 0
                last_result: dict[str, Any] = {}
                for doc in docs_to_ingest:
                    doc_title = str(doc["title"]).strip() or "uploaded-document"
                    doc_content = str(doc["content"]).strip()
                    if len(doc_title) < 3:
                        doc_title = f"{doc_title}-doc"
                    if len(doc_content) < 20:
                        upload_failures.append(f"{doc_title} (content too short; minimum 20 characters)")
                        continue
                    raw_metadata = doc.get("metadata", {}) if isinstance(doc.get("metadata", {}), dict) else {}
                    metadata = {
                        str(key): str(value)
                        for key, value in raw_metadata.items()
                        if value is not None and str(value).strip()
                    }
                    payload = {
                        "kind": kind,
                        "title": doc_title,
                        "content": doc_content,
                        "services": [item.strip() for item in services_text.split(",") if item.strip()],
                        "deployment": deployment or None,
                        "dependencies": [item.strip() for item in dependencies_text.split(",") if item.strip()],
                        "change_id": change_id or None,
                        "metadata": metadata,
                    }
                    payload["metadata"]["severity"] = issue_severity
                    if suggested_action.strip():
                        payload["metadata"]["recommended_action"] = suggested_action.strip()
                    result = request_json("POST", f"{GATEWAY_BASE}/rag/documents", json=payload)
                    if result:
                        last_result = result
                        successes += 1

                if last_result:
                    st.session_state["rag_ingest_result"] = last_result
                    st.session_state.pop("flows", None)
                    refreshed_flows = request_json("GET", f"{GATEWAY_BASE}/sample/flows")
                    st.session_state["flows"] = data_from_gateway(refreshed_flows).get("flows", [])
                    st.session_state["flow_catalog_preview"] = request_json("GET", f"{GATEWAY_BASE}/rag/flow-catalog")
                if successes:
                    st.success(f"Ingested {successes} document(s).")
                if upload_failures:
                    st.warning(
                        "Skipped non-text or unreadable files: " + ", ".join(upload_failures)
                    )

        if st.session_state.get("rag_ingest_result"):
            data = data_from_gateway(st.session_state["rag_ingest_result"])
            st.caption(f"✓ {data.get('document_count', '?')} docs in index")

    with st.expander("Flow Catalog Preview"):
        if st.button("Refresh Catalog", width="stretch"):
            st.session_state["flow_catalog_preview"] = request_json("GET", f"{GATEWAY_BASE}/rag/flow-catalog")

        catalog_response = st.session_state.get("flow_catalog_preview")
        if catalog_response:
            catalog_data = data_from_gateway(catalog_response)
            st.caption(
                f"{catalog_data.get('count', 0)} entries from {catalog_data.get('path', 'rag/flows.json')}"
            )
            entries = catalog_data.get("entries", [])
            if entries:
                st.dataframe(
                    [
                        {
                            "ID": item.get("id"),
                            "Title": item.get("title"),
                            "Service": item.get("service"),
                            "Severity": item.get("severity"),
                            "Action": item.get("recommended_action"),
                        }
                        for item in entries
                    ],
                    hide_index=True,
                    width="stretch",
                )
            else:
                st.caption("No catalog entries found yet.")
        else:
            st.caption("Click Refresh Catalog to load current rag/flows.json entries.")

if st.session_state.get("auto_refresh_enabled"):
    now = time.time()
    last_gateway_refresh = st.session_state.get("last_gateway_refresh_ts", 0)
    last_flow_refresh = st.session_state.get("last_flow_refresh_ts", 0)
    gateway_interval = int(st.session_state.get("gateway_refresh_interval", 12))
    flow_interval = int(st.session_state.get("flow_rerun_interval", 60))

    if now - last_gateway_refresh >= gateway_interval:
        st.session_state["gateway_summary"] = request_json("GET", f"{GATEWAY_BASE}/observability/summary")
        st.session_state["gateway_recent"] = request_json("GET", f"{GATEWAY_BASE}/observability/recent")
        st.session_state["last_gateway_refresh_ts"] = now

    if st.session_state.get("flow_rerun_enabled") and st.session_state.get("selected_flow"):
        if now - last_flow_refresh >= flow_interval:
            auto_flow_response = request_json(
                "POST", f"{GATEWAY_BASE}/sample/{st.session_state['selected_flow']}/workflow"
            )
            if auto_flow_response:
                st.session_state["gateway_response"] = auto_flow_response
                st.session_state["workflow"] = auto_flow_response.get("data", {})
            st.session_state["last_flow_refresh_ts"] = now

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
grounded_rag_response = get_grounded_rag_search(
    scenario=scenario,
    alert=alert,
    context=context,
    recommendation=recommendation,
    closure=closure,
)

homepage_html = build_complete_webpage_html(
    scenario=scenario,
    incident=incident,
    alert=alert,
    context=context,
    recommendation=recommendation,
    remediation=remediation,
    closure=closure,
    metrics=metrics,
    finops=finops,
    events=workflow.get("events", []),
    gateway_response=gateway_response,
    gateway_summary=st.session_state.get("gateway_summary", {}),
    gateway_recent=st.session_state.get("gateway_recent", {}),
    catalog_entries=catalog_entries,
    rag_search_response=grounded_rag_response,
)

homepage_export_name = f"kaiops-homepage-{time.strftime('%Y%m%d-%H%M%S')}.html"
st.download_button(
    "Save complete webpage as HTML",
    data=homepage_html,
    file_name=homepage_export_name,
    mime="text/html",
    width="stretch",
    key="kaiops_homepage_save_html",
)

if not workflow:
    st.info("Choose an incident flow in Mission Control and click Run Flow.")
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

tab_summary, tab_approval, tab_trace, tab_finops, tab_closed = st.tabs(
    ["Incident Summary", "Approval", "Agent Trace", "FinOps", "Closed Incidents"]
)

with tab_summary:
    if workflow:
        left, right = st.columns([1.2, 1])
        with left:
            st.markdown("### What happened")
            render_copyable_id("Incident ID", incident.get("id"))
            st.markdown(
                f"""
                <div class=\"kaiops-card\">
                <b>{alert.get('name')}</b> from <b>{alert.get('source')}</b><br/>
                Service <b>{alert.get('service')}</b> in <b>{alert.get('environment')}</b><br/>
                {alert.get('description')}
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
            st.session_state["approval_response"] = request_json("POST", f"{GATEWAY_BASE}/approval/approve", json=payload)
        if col_reject.button("Reject", width="stretch"):
            st.session_state["approval_response"] = request_json("POST", f"{GATEWAY_BASE}/approval/reject", json=payload)
        if col_modify.button("Modify", width="stretch"):
            payload["modified_action"] = comment
            st.session_state["approval_response"] = request_json("POST", f"{GATEWAY_BASE}/approval/modify", json=payload)

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
    st.markdown("### Agent Operations Board")
    st.caption("Track each agent role, handoff, and decision from detection to closure.")
    if workflow:
        html_report = build_incident_html_report(
            scenario=scenario,
            incident=incident,
            alert=alert,
            recommendation=recommendation,
            closure=closure,
            remediation=remediation,
            metrics=metrics,
            events=workflow.get("events", []),
            trace_id=gateway_response.get("trace_id"),
        )
        export_file_name = f"kaiops-incident-{incident.get('id', 'report')}.html"
        st.download_button(
            "Save as HTML",
            data=html_report,
            file_name=export_file_name,
            mime="text/html",
            width="stretch",
            key="kaiops_trace_save_html",
        )

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

    trace_tab1, trace_tab2, trace_tab3 = st.tabs(["Handoff Flow", "Raw Trace", "Gateway & Safety"])

    with trace_tab1:
        if workflow.get("events"):
            ordered_events = sorted(workflow.get("events", []), key=lambda item: item.get("sequence", 0))
            render_handoff_path(ordered_events)
            handoff_options = [f"Step {event.get('sequence', '-')}: {event.get('agent', 'Agent')}" for event in ordered_events]
            selected_handoff = st.session_state.get("selected_trace_step", handoff_options[-1])
            if selected_handoff not in handoff_options:
                selected_handoff = handoff_options[-1]
            selected_handoff_index = handoff_options.index(selected_handoff)
            st.caption(f"Drill-down selection: {selected_handoff}")
            render_agent_event_details(ordered_events[selected_handoff_index])
        else:
            st.info("Run a flow to view the handoff path.")

    with trace_tab2:
        if workflow.get("events"):
            render_event_trace(workflow.get("events", []))
        else:
            st.info("Run a flow to view the raw trace.")

    with trace_tab3:
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

with tab_closed:
    st.markdown("### Closure report")
    if not closure:
        st.info("Run a flow to generate a closed incident report.")
    else:
        html_report = build_incident_html_report(
            scenario=scenario,
            incident=incident,
            alert=alert,
            recommendation=recommendation,
            closure=closure,
            remediation=remediation,
            metrics=metrics,
            events=workflow.get("events", []),
            trace_id=gateway_response.get("trace_id"),
        )
        export_file_name = f"kaiops-incident-{incident.get('id', 'report')}.html"
        st.download_button(
            "Save as HTML",
            data=html_report,
            file_name=export_file_name,
            mime="text/html",
            width="stretch",
        )
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
