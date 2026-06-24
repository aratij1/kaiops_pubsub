from __future__ import annotations

import html
import os
import re
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


def infer_rag_kind(file_name: str, content: str) -> str:
    corpus = f"{file_name} {content[:2000]}".lower()
    if any(token in corpus for token in ("runbook", "playbook", "sop", "procedure")):
        return "runbook"
    if any(token in corpus for token in ("deployment", "release", "rollout", "helm")):
        return "deployment"
    if any(token in corpus for token in ("change", "chg-", "cab", "rfc")):
        return "change"
    if any(token in corpus for token in ("dependency", "topology", "upstream", "downstream", "graph")):
        return "dependency"
    return "incident"


def infer_linked_incident_ids(file_name: str, content: str, entries: list[dict[str, Any]]) -> list[str]:
    doc = f"{file_name} {content[:5000]}".lower()
    scored: list[tuple[int, str]] = []

    for item in entries:
        flow_id = str(item.get("id", "")).strip()
        if not flow_id:
            continue

        score = 0
        service = str(item.get("service", "")).strip().lower()
        title = str(item.get("title", "")).strip().lower()
        alert_name = str(item.get("alert_name", "")).strip().lower()
        alert_id = str(item.get("alert_id", "")).strip().lower()
        action = str(item.get("recommended_action", "")).strip().lower()

        if service and service in doc:
            score += 4
        if flow_id.lower() in doc:
            score += 4
        if alert_id and alert_id in doc:
            score += 3

        title_tokens = [token for token in re.split(r"\W+", title) if len(token) > 4]
        alert_tokens = [token for token in re.split(r"\W+", alert_name) if len(token) > 4]
        action_tokens = [token for token in re.split(r"\W+", action) if len(token) > 5]

        score += sum(1 for token in title_tokens[:6] if token in doc)
        score += sum(1 for token in alert_tokens[:6] if token in doc)
        score += sum(1 for token in action_tokens[:4] if token in doc)

        if score > 0:
            scored.append((score, flow_id))

    scored.sort(key=lambda item: item[0], reverse=True)
    linked_ids: list[str] = []
    for _, flow_id in scored:
        if flow_id not in linked_ids:
            linked_ids.append(flow_id)
        if len(linked_ids) >= 3:
            break
    return linked_ids


def infer_services_from_links(content: str, entries: list[dict[str, Any]], linked_ids: list[str]) -> list[str]:
    text = content.lower()
    services: list[str] = []

    for entry in entries:
        service = str(entry.get("service", "")).strip()
        if service and service.lower() in text and service not in services:
            services.append(service)

    if not services:
        by_id = {str(entry.get("id", "")): str(entry.get("service", "")).strip() for entry in entries}
        for flow_id in linked_ids:
            service = by_id.get(flow_id, "")
            if service and service not in services:
                services.append(service)

    return services[:5]


def infer_change_id(content: str) -> str | None:
    match = re.search(r"\bCHG-\d+\b", content, flags=re.IGNORECASE)
    return match.group(0).upper() if match else None


def infer_deployment_tag(content: str) -> str | None:
    match = re.search(r"\b(?:deployment|release)\s*[:#-]?\s*([0-9]+(?:\.[0-9]+){1,2})\b", content, flags=re.IGNORECASE)
    if match:
        return match.group(1)
    fallback = re.search(r"\b[0-9]+\.[0-9]+(?:\.[0-9]+)?\b", content)
    return fallback.group(0) if fallback else None


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


def _alert_stream_status(severity: str, recommended_action: str, alert_name: str) -> tuple[str, str]:
    """Return (badge_class, badge_label) for an alert stream entry."""
    sev = severity.upper()
    action = recommended_action.lower()
    name_lower = alert_name.lower()
    # Duplicate indicators
    if "duplicate" in name_lower or "duplicate" in action:
        return "kaiops-badge-duplicate", "DUPLICATE"
    if any(token in name_lower for token in ("ignore", "ignored", "suppressed", "maintenance", "test alert")):
        return "kaiops-badge-ignore", "IGNORE"
    if any(token in action for token in ("ignore", "ignored", "suppress", "suppressed", "no remediation")):
        return "kaiops-badge-ignore", "IGNORE"
    # No-action-required patterns
    no_action_actions = {"api execution", "no action", "monitor", "auto-resolved", "observe", "informational"}
    if action in no_action_actions or "no action" in action or sev == "INFO":
        return "kaiops-badge-ignore", "NO ACTION"
    # Low-priority warning with generic action
    if sev == "WARNING" and action in {"clear cache", "scale deployment"}:
        return "kaiops-badge-warning", "LOW"
    if sev == "WARNING":
        return "kaiops-badge-warning", "WARN"
    if sev == "HIGH":
        return "kaiops-badge-high", "HIGH"
    if sev == "CRITICAL":
        return "kaiops-badge-critical", "CRITICAL"
    return "kaiops-badge-info", sev or "UNKNOWN"


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
        recommended_action = str(item.get("recommended_action") or "").strip()
        flow_id = str(item.get("id") or "").strip()

        badge_class, badge_label = _alert_stream_status(severity, recommended_action, alert_name)
        is_suppressed = badge_label in ("DUPLICATE", "NO ACTION", "IGNORE")

        # Suppress interactive button for no-action/duplicate/ignored entries; still render as evidence.
        if is_suppressed:
            st.markdown(
                f'<div style="opacity:0.92; padding:6px 8px; border:1px dashed rgba(148,163,184,0.28);'
                f'border-radius:10px; margin-bottom:6px; background:rgba(15,23,42,0.26);">'
                f'<span class="kaiops-alert-badge {badge_class}">{badge_label}</span>'
                f' <span style="font-size:0.78rem; color:#cbd5e1;">{alert_id} | {alert_name}</span>'
                f'<div style="font-size:0.7rem; color:#94a3b8; margin-bottom:4px; padding-left:4px;">'
                f'{service} · {severity} · excluded from auto-run</div></div>',
                unsafe_allow_html=True,
            )
        else:
            button_label = f"{alert_id} | {alert_name}"
            clicked = flow_id and st.button(
                button_label,
                key=f"kaiops_alert_stream_{flow_id}",
                width="stretch",
            )
            if clicked:
                selected_flow_id = flow_id
            st.markdown(
                f'<span class="kaiops-alert-badge {badge_class}">{badge_label}</span>'
                f' <span style="font-size:0.7rem; color:#94a3b8; margin-bottom:4px;">'
                f'{service} · {severity}</span>',
                unsafe_allow_html=True,
            )
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


def render_agent_role_overview(events: list[dict[str, Any]]) -> None:
    events_by_agent = {str(event.get("agent", "")): event for event in events}
    st.markdown("#### Agent Command Roles")
    agent_items = list(AGENT_PROFILES.items())
    for start in range(0, len(agent_items), 4):
        columns = st.columns(4)
        for offset, column in enumerate(columns):
            index = start + offset
            if index >= len(agent_items):
                continue

            agent_name, profile = agent_items[index]
            event = events_by_agent.get(agent_name, {})
            status = "COMPLETED" if event else "STANDBY"
            decision = str(event.get("decision", "Awaiting workflow execution"))
            kpis = agent_kpis(event) if event else {"calls": 0, "errors": 0, "signals": 0}

            with column:
                with st.container(border=True):
                    st.caption(f"Step {index + 1} · {status}")
                    st.markdown(f"**{profile.get('icon', '[AGENT]')} {agent_name}**")
                    st.caption(profile.get("mission", "Coordinates incident-resolution logic."))
                    st.markdown(
                        f"Signals `{kpis['signals']}` · LLM `{kpis['calls']}` · Errors `{kpis['errors']}`"
                    )
                    if event:
                        st.success(decision[:220])
                    else:
                        st.info("Awaiting workflow execution")


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
                background: linear-gradient(180deg, #0c1524 0%, #0f172a 60%, #131d2e 100%) !important;
            }
            section[data-testid="stSidebar"] .block-container {
                padding-top: 0.8rem;
            }
            .kaiops-sidebar-hero {
                background: linear-gradient(135deg, #1d4ed8 0%, #0ea5e9 60%, #06b6d4 100%);
                border-radius: 14px;
                padding: 14px 14px 12px;
                color: #e2e8f0;
                margin-bottom: 12px;
                box-shadow: 0 10px 28px rgba(14, 165, 233, 0.35);
            }
            .kaiops-sidebar-hero h3 {
                margin: 0;
                font-size: 1.08rem;
                font-weight: 800;
                letter-spacing: 0.02em;
                color: #ffffff;
            }
            .kaiops-sidebar-hero p {
                margin: 4px 0 0;
                font-size: 0.78rem;
                color: #dbeafe;
            }
            .kaiops-sidebar-section {
                margin: 0.35rem 0 0.5rem;
                font-size: 0.72rem;
                letter-spacing: 0.04em;
                text-transform: uppercase;
                color: #e2e8f0;
                font-weight: 700;
            }
            section[data-testid="stSidebar"] .stButton > button {
                background: rgba(30, 41, 59, 0.7) !important;
                color: #e2e8f0 !important;
                border: 1px solid rgba(148, 163, 184, 0.2) !important;
                border-radius: 8px !important;
            }
            section[data-testid="stSidebar"] .stButton > button:hover {
                background: rgba(29, 78, 216, 0.5) !important;
                border-color: #60a5fa !important;
                color: #ffffff !important;
            }
            section[data-testid="stSidebar"] label,
            section[data-testid="stSidebar"] p,
            section[data-testid="stSidebar"] .stCaption > *,
            section[data-testid="stSidebar"] small,
            section[data-testid="stSidebar"] span,
            section[data-testid="stSidebar"] div {
                color: #e2e8f0 !important;
            }
            section[data-testid="stSidebar"] div[data-testid="stVerticalBlockBorderWrapper"] {
                background: rgba(15, 23, 42, 0.42) !important;
                border-color: rgba(148, 163, 184, 0.35) !important;
                border-radius: 12px !important;
            }
            section[data-testid="stSidebar"] input,
            section[data-testid="stSidebar"] textarea,
            section[data-testid="stSidebar"] select {
                background: rgba(15, 23, 42, 0.78) !important;
                color: #f8fafc !important;
                border: 1px solid rgba(148, 163, 184, 0.35) !important;
            }
            .kaiops-alert-badge {
                display: inline-block;
                font-size: 0.58rem;
                font-weight: 700;
                letter-spacing: 0.04em;
                padding: 1px 6px;
                border-radius: 999px;
                vertical-align: middle;
                white-space: nowrap;
            }
            .kaiops-badge-critical { background: #dc2626; color: #fff; }
            .kaiops-badge-high { background: #ea580c; color: #fff; }
            .kaiops-badge-warning { background: #d97706; color: #fff; }
            .kaiops-badge-duplicate { background: rgba(100,116,139,0.2); color: #94a3b8; border: 1px solid #475569; }
            .kaiops-badge-ignore { background: rgba(71,85,105,0.25); color: #cbd5e1; border: 1px dashed #94a3b8; }
            .kaiops-badge-info { background: rgba(14,165,233,0.15); color: #38bdf8; border: 1px solid #0ea5e9; }
            .kaiops-hero-wrap {
                background: linear-gradient(118deg, #0f172a 0%, #1e1b4b 30%, #1d4ed8 65%, #0ea5e9 100%);
                border-radius: 22px;
                padding: 28px 32px 24px;
                color: #e2e8f0;
                margin-bottom: 20px;
                box-shadow: 0 28px 56px rgba(15,23,42,0.32), inset 0 1px 0 rgba(255,255,255,0.07);
                position: relative;
                overflow: hidden;
            }
            .kaiops-hero-wrap::before {
                content: "";
                position: absolute;
                top: -80px; right: -80px;
                width: 320px; height: 320px;
                background: radial-gradient(circle, rgba(14,165,233,0.15) 0%, transparent 70%);
                pointer-events: none;
            }
            .kaiops-hero-wrap::after {
                content: "";
                position: absolute;
                bottom: -40px; left: 20%;
                width: 200px; height: 200px;
                background: radial-gradient(circle, rgba(99,102,241,0.12) 0%, transparent 70%);
                pointer-events: none;
            }
            .kaiops-hero-label {
                font-size: 0.72rem;
                font-weight: 700;
                letter-spacing: 0.1em;
                text-transform: uppercase;
                color: #60a5fa;
                margin: 0 0 8px;
            }
            .kaiops-hero-title {
                font-size: 1.9rem;
                font-weight: 800;
                color: #ffffff;
                letter-spacing: -0.02em;
                margin: 0 0 8px;
                line-height: 1.15;
            }
            .kaiops-hero-sub {
                font-size: 0.96rem;
                color: #93c5fd;
                margin: 0 0 18px;
                max-width: 580px;
                line-height: 1.5;
            }
            .kaiops-hero-pills {
                display: flex;
                gap: 8px;
                flex-wrap: wrap;
            }
            .kaiops-hero-pill {
                display: inline-flex;
                align-items: center;
                gap: 5px;
                background: rgba(255,255,255,0.08);
                border: 1px solid rgba(255,255,255,0.14);
                border-radius: 999px;
                padding: 4px 13px;
                font-size: 0.75rem;
                font-weight: 600;
                color: #e0f2fe;
                backdrop-filter: blur(4px);
            }
            .kaiops-hero-pill-dot {
                width: 7px; height: 7px;
                border-radius: 50%;
                background: #4ade80;
                display: inline-block;
                animation: kaiops-pulse 2.2s ease-in-out infinite;
            }
            .kaiops-hero-pill-dot-amber { background: #fbbf24; }
            .kaiops-hero-pill-dot-blue { background: #38bdf8; }
            @keyframes kaiops-pulse {
                0%, 100% { opacity: 1; transform: scale(1); }
                50% { opacity: 0.45; transform: scale(0.8); }
            }
            .kaiops-summary-hero {
                background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
                border-radius: 16px;
                padding: 20px 22px 16px;
                margin-bottom: 16px;
                border: 1px solid rgba(30,58,95,0.8);
                box-shadow: 0 8px 24px rgba(15,23,42,0.18);
            }
            .kaiops-summary-hero-alert {
                font-size: 1.18rem;
                font-weight: 700;
                color: #f1f5f9;
                margin: 0 0 5px;
            }
            .kaiops-summary-hero-meta {
                font-size: 0.83rem;
                color: #94a3b8;
                margin: 0 0 12px;
            }
            .kaiops-summary-badge {
                display: inline-block;
                padding: 3px 10px;
                border-radius: 999px;
                font-size: 0.72rem;
                font-weight: 700;
                letter-spacing: 0.04em;
                margin-right: 6px;
                vertical-align: middle;
            }
            .kaiops-sev-critical { background: #dc2626; color: #fff; }
            .kaiops-sev-high { background: #ea580c; color: #fff; }
            .kaiops-sev-warning { background: #d97706; color: #fff; }
            .kaiops-sev-info { background: #0ea5e9; color: #fff; }
            .kaiops-rc-pill {
                display: inline-block;
                background: rgba(250,204,21,0.1);
                border: 1px solid #ca8a04;
                color: #fde047;
                padding: 3px 10px;
                border-radius: 8px;
                font-size: 0.75rem;
                font-weight: 600;
            }
            .kaiops-info-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
                gap: 10px;
                margin-top: 12px;
            }
            .kaiops-info-cell {
                background: rgba(30,41,59,0.5);
                border: 1px solid rgba(51,65,85,0.6);
                border-radius: 10px;
                padding: 10px 14px;
            }
            .kaiops-info-cell-label {
                font-size: 0.68rem;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.05em;
                color: #64748b;
                margin-bottom: 3px;
            }
            .kaiops-info-cell-value {
                font-size: 0.88rem;
                font-weight: 600;
                color: #e2e8f0;
            }
            .kaiops-recommendation-card {
                background: rgba(22,163,74,0.07);
                border: 1px solid rgba(22,163,74,0.3);
                border-radius: 14px;
                padding: 16px 18px;
                margin-top: 14px;
            }
            .kaiops-recommendation-action {
                font-size: 1.05rem;
                font-weight: 700;
                color: #4ade80;
                margin: 0 0 5px;
            }
            .kaiops-recommendation-rationale {
                font-size: 0.84rem;
                color: #94a3b8;
                margin: 0;
                line-height: 1.5;
            }
            .kaiops-approval-card {
                background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
                border-radius: 18px;
                padding: 22px 24px 20px;
                border: 1px solid rgba(30,58,95,0.8);
                box-shadow: 0 10px 32px rgba(15,23,42,0.22);
                margin-bottom: 16px;
            }
            .kaiops-approval-title {
                font-size: 1.08rem;
                font-weight: 700;
                color: #e2e8f0;
                margin: 0 0 14px;
                padding-bottom: 12px;
                border-bottom: 1px solid rgba(30,58,95,0.8);
                display: flex;
                align-items: center;
                gap: 8px;
            }
            .kaiops-approval-kv-row {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
                gap: 8px;
                margin-bottom: 14px;
            }
            .kaiops-approval-kv {
                background: rgba(15,23,42,0.6);
                border: 1px solid rgba(51,65,85,0.5);
                border-radius: 10px;
                padding: 10px 14px;
            }
            .kaiops-approval-kv-label {
                font-size: 0.68rem;
                color: #475569;
                text-transform: uppercase;
                letter-spacing: 0.05em;
                font-weight: 700;
            }
            .kaiops-approval-kv-value {
                font-size: 0.85rem;
                font-weight: 600;
                color: #cbd5e1;
                margin-top: 3px;
                word-break: break-all;
            }
            .kaiops-approval-result {
                border-radius: 12px;
                padding: 14px 18px;
                margin-top: 14px;
            }
            .kaiops-approval-result-approved {
                background: rgba(22,163,74,0.1);
                border: 1px solid rgba(22,163,74,0.35);
                color: #4ade80;
            }
            .kaiops-approval-result-rejected {
                background: rgba(220,38,38,0.08);
                border: 1px solid rgba(220,38,38,0.35);
                color: #f87171;
            }
            .kaiops-approval-result-modified {
                background: rgba(234,179,8,0.08);
                border: 1px solid rgba(234,179,8,0.35);
                color: #fde047;
            }

      @media (max-width: 920px) {
        .kaiops-hero-title { font-size: 1.4rem; }
      }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="kaiops-hero-wrap">
      <div class="kaiops-hero-label">&#9679; AI-Powered SRE Platform</div>
      <div class="kaiops-hero-title">KaiOps Autonomous Operations</div>
      <div class="kaiops-hero-sub">
        A mission-ready operations cockpit for agent handoffs, human approvals,
        remediation decisions, RAG-grounded evidence, and FinOps visibility.
      </div>
      <div class="kaiops-hero-pills">
        <span class="kaiops-hero-pill"><span class="kaiops-hero-pill-dot"></span> Agents Online</span>
        <span class="kaiops-hero-pill"><span class="kaiops-hero-pill-dot kaiops-hero-pill-dot-blue"></span> RAG Grounded</span>
        <span class="kaiops-hero-pill"><span class="kaiops-hero-pill-dot kaiops-hero-pill-dot-amber"></span> Gateway Active</span>
        <span class="kaiops-hero-pill">7-Step Workflow</span>
        <span class="kaiops-hero-pill">GPT-Powered RCA</span>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

flows = get_flows()
severity_levels = sorted({str(flow.get("severity", "unknown")).upper() for flow in flows})
workflow = st.session_state.get("workflow", {})
render_agent_role_overview(sorted(workflow.get("events", []), key=lambda item: item.get("sequence", 0)))
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
        <div class="kaiops-sidebar-hero" style="position:relative;overflow:hidden;">
          <div style="position:absolute;right:-35px;top:-35px;width:110px;height:110px;border-radius:999px;
                      background:rgba(56,189,248,0.16);filter:blur(2px);"></div>
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;position:relative;">
            <span style="font-size:1.28rem;">&#128640;</span>
            <h3 style="margin:0;font-size:1.12rem;letter-spacing:-0.01em;">Mission Control</h3>
            <span style="margin-left:auto;display:inline-flex;align-items:center;gap:4px;
                         background:rgba(255,255,255,0.15);border-radius:999px;padding:2px 8px;
                         font-size:0.62rem;font-weight:700;letter-spacing:0.05em;color:#e0f2fe;">
              <span style="width:6px;height:6px;border-radius:50%;background:#4ade80;
                           display:inline-block;animation:kaiops-pulse 2.2s ease-in-out infinite;"></span>
              LIVE
            </span>
          </div>
          <p style="margin:0 0 10px;color:#bfdbfe;font-size:0.78rem;line-height:1.35;position:relative;">
            Launch, triage, approve, remediate, and validate incidents from one command surface.
          </p>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:8px;position:relative;">
            <span style="background:rgba(255,255,255,0.12);border-radius:6px;padding:2px 8px;
                         font-size:0.65rem;font-weight:600;color:#bfdbfe;">&#9632; Alert Stream</span>
            <span style="background:rgba(255,255,255,0.12);border-radius:6px;padding:2px 8px;
                         font-size:0.65rem;font-weight:600;color:#bfdbfe;">&#9654; Flow Control</span>
            <span style="background:rgba(255,255,255,0.12);border-radius:6px;padding:2px 8px;
                         font-size:0.65rem;font-weight:600;color:#bfdbfe;">&#9679; RAG Knowledge Base</span>
            <span style="background:rgba(255,255,255,0.12);border-radius:6px;padding:2px 8px;
                         font-size:0.65rem;font-weight:600;color:#bfdbfe;">&#10003; Human Approval</span>
          </div>
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

    # ── RAG Workspace — placed after Live Monitoring as a knowledge-base admin section ──
    st.markdown(
        """
        <div style="margin: 12px 0 2px;">
          <div style="height:1px;background:rgba(148,163,184,0.12);margin-bottom:10px;"></div>
          <div style="display:flex;align-items:center;gap:6px;margin-bottom:6px;">
            <span style="font-size:0.72rem;letter-spacing:0.04em;text-transform:uppercase;
                                                 color:#e2e8f0;font-weight:700;">&#128209; RAG Knowledge Base</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.container(border=True):
        st.markdown(
                        '<p style="font-size:0.72rem;color:#cbd5e1;margin:0 0 8px;">'
            "Index operational docs that ground agent recommendations."
            "</p>",
            unsafe_allow_html=True,
        )
        col_reload, col_list = st.columns(2)
        if col_reload.button("Reload Index", width="stretch"):
            st.session_state["rag_reload"] = request_json("POST", f"{GATEWAY_BASE}/rag/reload")
            if st.session_state.get("rag_reload"):
                st.session_state["rag_last_indexed_at"] = time.time()
        if col_list.button("List Docs", width="stretch"):
            st.session_state["rag_documents"] = request_json("GET", f"{GATEWAY_BASE}/rag/documents")
            if st.session_state.get("rag_documents"):
                st.session_state["rag_last_indexed_at"] = time.time()

        last_indexed_at = st.session_state.get("rag_last_indexed_at")
        if last_indexed_at:
            st.caption(f"Last indexed at {time.strftime('%H:%M:%S', time.localtime(last_indexed_at))}")

        if st.session_state.get("rag_reload"):
            reloaded_count = data_from_gateway(st.session_state["rag_reload"]).get("document_count")
            st.success(f"RAG reloaded — {reloaded_count} docs in index")

        if st.session_state.get("rag_documents"):
            docs_payload = data_from_gateway(st.session_state["rag_documents"])
            docs_count = int(docs_payload.get("document_count", 0) or 0)
            documents = docs_payload.get("documents", []) if isinstance(docs_payload.get("documents", []), list) else []
            st.caption(f"Indexed docs: {docs_count}")
            if documents:
                st.dataframe(
                    [
                        {
                            "Kind": doc.get("kind"),
                            "Title": doc.get("title"),
                            "Services": ", ".join(doc.get("services", []))
                            if isinstance(doc.get("services"), list)
                            else str(doc.get("services", "")),
                        }
                        for doc in documents[:20]
                    ],
                    hide_index=True,
                    width="stretch",
                )
            else:
                st.info("RAG index is reachable but currently has no documents.")

        search_query = st.text_input("Search RAG", placeholder="payments latency rollback", key="sidebar_rag_search")
        if st.button("Search", width="stretch", disabled=not search_query):
            st.session_state["rag_search"] = request_json(
                "GET", f"{GATEWAY_BASE}/rag/search", params={"query": search_query, "limit": 8}
            )

    with st.expander("&#8593; Ingest document"):
        st.caption("Upload docs only. KaiOps auto-detects type, extracts metadata, and links to likely incidents.")
        uploaded_docs = st.file_uploader(
            "Upload one or more documents",
            accept_multiple_files=True,
            help="Supported text formats include .md, .txt, .log, .yaml, and similar text files.",
            key="rag_upload_auto_files",
        )
        submitted = st.button("Upload & Auto-Link", type="primary", width="stretch")

        if submitted:
            if not uploaded_docs:
                st.warning("Upload at least one document to continue.")
            else:
                upload_failures: list[str] = []
                linked_summary: list[dict[str, Any]] = []
                successes = 0
                last_result: dict[str, Any] = {}

                for uploaded_doc in uploaded_docs:
                    file_name = str(getattr(uploaded_doc, "name", "uploaded-document"))
                    uploaded_text = uploaded_file_to_text(uploaded_doc)
                    if uploaded_text is None:
                        upload_failures.append(f"{file_name} (non-text or unreadable)")
                        continue

                    doc_content = uploaded_text.strip()
                    doc_title = file_name.rsplit(".", 1)[0].strip() or "uploaded-document"
                    if len(doc_title) < 3:
                        doc_title = f"{doc_title}-doc"
                    if len(doc_content) < 20:
                        upload_failures.append(f"{doc_title} (content too short; minimum 20 characters)")
                        continue

                    auto_kind = infer_rag_kind(file_name, doc_content)
                    linked_ids = infer_linked_incident_ids(file_name, doc_content, catalog_entries)
                    inferred_services = infer_services_from_links(doc_content, catalog_entries, linked_ids)
                    inferred_change_id = infer_change_id(doc_content)
                    inferred_deployment = infer_deployment_tag(doc_content)

                    payload = {
                        "kind": auto_kind,
                        "title": doc_title,
                        "content": doc_content,
                        "services": inferred_services,
                        "deployment": inferred_deployment,
                        "dependencies": [],
                        "change_id": inferred_change_id,
                        "metadata": {
                            "source": "ui-upload-auto",
                            "uploaded_filename": file_name,
                            "auto_linked_incidents": ", ".join(linked_ids),
                            "auto_link_status": "linked" if linked_ids else "unmatched",
                        },
                    }

                    if linked_ids:
                        matched_entry = next((item for item in catalog_entries if str(item.get("id")) == linked_ids[0]), {})
                        recommended_action = str(matched_entry.get("recommended_action", "")).strip()
                        severity = str(matched_entry.get("severity", "")).strip().upper()
                        if recommended_action:
                            payload["metadata"]["recommended_action"] = recommended_action
                        if severity in {"CRITICAL", "HIGH", "WARNING"}:
                            payload["metadata"]["severity"] = severity

                    result = request_json("POST", f"{GATEWAY_BASE}/rag/documents", json=payload)
                    if result:
                        last_result = result
                        successes += 1
                        linked_summary.append(
                            {
                                "Document": doc_title,
                                "Detected Type": auto_kind,
                                "Linked Incident": ", ".join(linked_ids) if linked_ids else "No confident match",
                            }
                        )

                if last_result:
                    st.session_state["rag_ingest_result"] = last_result
                    st.session_state["rag_last_indexed_at"] = time.time()
                    st.session_state["rag_documents"] = request_json("GET", f"{GATEWAY_BASE}/rag/documents")
                    st.session_state.pop("flows", None)
                    refreshed_flows = request_json("GET", f"{GATEWAY_BASE}/sample/flows")
                    st.session_state["flows"] = data_from_gateway(refreshed_flows).get("flows", [])
                    st.session_state["flow_catalog_preview"] = request_json("GET", f"{GATEWAY_BASE}/rag/flow-catalog")

                if successes:
                    st.success(f"Uploaded and indexed {successes} document(s).")
                if linked_summary:
                    st.dataframe(linked_summary, hide_index=True, width="stretch")
                if upload_failures:
                    st.warning("Skipped files: " + ", ".join(upload_failures))

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
_export_left, _export_right = st.columns([12, 1])
with _export_right:
    st.download_button(
        "⬇",
        data=homepage_html,
        file_name=homepage_export_name,
        mime="text/html",
        width="content",
        help="Download complete webpage as HTML",
        key="kaiops_homepage_save_html",
    )

if not workflow:
    st.info("Choose an incident flow in Mission Control and click Run Flow.")
else:
    st.subheader(scenario.get("title", "Incident Flow"))
    _h_inc = str(incident.get("id", "—"))
    _h_trace = str(gateway_response.get("trace_id", "—"))
    st.markdown(
        f'<div style="display:flex;gap:10px;flex-wrap:wrap;margin:-4px 0 12px;">'
        f'<span style="font-family:monospace;font-size:0.72rem;color:#64748b;background:rgba(15,23,42,0.06);'
        f'border:1px solid #e2e8f0;border-radius:6px;padding:3px 10px;">'
        f'<b style="color:#94a3b8;">INC</b> {html.escape(_h_inc)}</span>'
        f'<span style="font-family:monospace;font-size:0.72rem;color:#64748b;background:rgba(15,23,42,0.06);'
        f'border:1px solid #e2e8f0;border-radius:6px;padding:3px 10px;">'
        f'<b style="color:#94a3b8;">TRACE</b> {html.escape(_h_trace)}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )
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
        # Severity badge class
        _sev = str(metrics.get("severity", alert.get("severity", "unknown"))).lower()
        _sev_class = {"critical": "kaiops-sev-critical", "high": "kaiops-sev-high",
                      "warning": "kaiops-sev-warning", "info": "kaiops-sev-info"}.get(_sev, "kaiops-sev-info")
        _confidence_pct = f"{float(metrics.get('recommendation_confidence', 0)):.0%}"
        _health = "✓ Restored" if metrics.get("health_restored") else "✗ Not Restored"
        _gw_decision = str(gateway.get("safety", {}).get("decision", "unknown")).upper()
        _active_flow = next(
            (flow for flow in catalog_entries if str(flow.get("id")) == str(scenario.get("id", selected_flow))),
            {},
        )
        _alert_display_id = str(_active_flow.get("alert_id") or scenario.get("id") or alert.get("id", "N/A"))
        _alert_display_name = str(
            _active_flow.get("alert_name")
            or _active_flow.get("title")
            or alert.get("name")
            or scenario.get("title")
            or "Incident"
        )
        _alert_type = str(_active_flow.get("alert_type") or alert.get("source") or "monitoring")
        _summary_service = str(_active_flow.get("service") or alert.get("service") or "N/A")
        _summary_description = str(
            _active_flow.get("description")
            or alert.get("description")
            or scenario.get("title")
            or "No incident description available."
        )

        # ── Hero incident header ──
        st.markdown(
            f"""
            <div class="kaiops-summary-hero">
              <div class="kaiops-summary-hero-alert">
                <span class="kaiops-summary-badge {_sev_class}">{_sev.upper()}</span>
                {html.escape(_alert_display_name)}
              </div>
              <div class="kaiops-summary-hero-meta">
                Alert <b style="color:#cbd5e1">{html.escape(_alert_display_id)}</b>
                &nbsp;·&nbsp; Service <b style="color:#cbd5e1">{html.escape(_summary_service)}</b>
                &nbsp;·&nbsp; Environment <b style="color:#cbd5e1">{html.escape(str(alert.get('environment','N/A')))}</b>
                &nbsp;·&nbsp; Type <b style="color:#cbd5e1">{html.escape(_alert_type)}</b>
              </div>
              <div style="font-size:0.86rem; color:#94a3b8; line-height:1.5;">
                {html.escape(_summary_description)}
              </div>
              <div class="kaiops-info-grid" style="margin-top:14px;">
                <div class="kaiops-info-cell">
                  <div class="kaiops-info-cell-label">Deployment</div>
                  <div class="kaiops-info-cell-value">{html.escape(str(context.get('deployment') or 'N/A'))}</div>
                </div>
                <div class="kaiops-info-cell">
                  <div class="kaiops-info-cell-label">Confidence</div>
                  <div class="kaiops-info-cell-value">{_confidence_pct}</div>
                </div>
                <div class="kaiops-info-cell">
                  <div class="kaiops-info-cell-label">Health</div>
                  <div class="kaiops-info-cell-value">{_health}</div>
                </div>
                <div class="kaiops-info-cell">
                  <div class="kaiops-info-cell-label">Gateway</div>
                  <div class="kaiops-info-cell-value">{_gw_decision}</div>
                </div>
                <div class="kaiops-info-cell">
                  <div class="kaiops-info-cell-label">Dedup Count</div>
                  <div class="kaiops-info-cell-value">{metrics.get('deduplicated_count', 1)}</div>
                </div>
                <div class="kaiops-info-cell">
                  <div class="kaiops-info-cell-label">Agent Handoffs</div>
                  <div class="kaiops-info-cell-value">{metrics.get('agent_handoffs', 'N/A')}</div>
                </div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        left, right = st.columns([1.3, 1])
        with left:
            st.markdown("#### Root Cause & Recommendation")
            _rc = str(recommendation.get("root_cause") or closure.get("root_cause") or "Pending analysis")
            st.markdown(
                f"""
                <div class="kaiops-recommendation-card">
                  <div class="kaiops-recommendation-action">
                    &#9654; {html.escape(str(recommendation.get('recommended_action','N/A')))}
                  </div>
                  <div style="font-size:0.78rem; color:#475569; font-weight:600; margin: 4px 0 6px;">
                    ROOT CAUSE
                  </div>
                  <div style="font-size:0.84rem; color:#cbd5e1; line-height:1.5; margin-bottom:8px;">
                    {html.escape(_rc)}
                  </div>
                  <div class="kaiops-recommendation-rationale">
                    {html.escape(str(recommendation.get('rationale','N/A')))}
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            _impact = str(recommendation.get("impact") or closure.get("impact") or "N/A")
            _risk = str(recommendation.get("risk", "medium")).upper()
            _risk_color = "#dc2626" if _risk == "HIGH" else ("#d97706" if _risk == "MEDIUM" else "#16a34a")
            st.markdown(
                f"""
                <div style="display:flex; gap:10px; margin-top:10px;">
                  <div class="kaiops-info-cell" style="flex:1">
                    <div class="kaiops-info-cell-label">Impact</div>
                    <div class="kaiops-info-cell-value" style="font-size:0.82rem">{html.escape(_impact)}</div>
                  </div>
                  <div class="kaiops-info-cell" style="flex:0 0 100px">
                    <div class="kaiops-info-cell-label">Risk</div>
                    <div class="kaiops-info-cell-value" style="color:{_risk_color}">{_risk}</div>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with right:
            st.markdown("#### Operational Context")
            _deps = context.get("dependency_services", [])
            _deps_str = ", ".join(_deps) if _deps else "None"
            _changes = context.get("recent_changes", [])
            _runbook = bool(context.get("runbook"))
            table_from_dict({
                "root_cause": recommendation.get("root_cause") or closure.get("root_cause"),
                "remediation_status": metrics.get("remediation_status"),
                "runbook_found": "Yes" if _runbook else "No",
                "dependencies": _deps_str,
                "recent_changes": len(_changes),
                "alerts_cleared": "Yes" if metrics.get("alerts_cleared") else "No",
            })
            _inc_id = str(incident.get("id", "—"))
            _trace_id = str(gateway_response.get("trace_id", "—"))
            st.markdown(
                f"""
                <div style="margin-top:10px;display:flex;flex-direction:column;gap:6px;">
                  <div style="background:rgba(15,23,42,0.5);border:1px solid rgba(51,65,85,0.5);
                               border-radius:8px;padding:8px 12px;">
                    <span style="font-size:0.65rem;font-weight:700;text-transform:uppercase;
                                 letter-spacing:0.05em;color:#475569;">Incident ID</span>
                    <div style="font-family:monospace;font-size:0.75rem;color:#94a3b8;
                                margin-top:2px;word-break:break-all;">{html.escape(_inc_id)}</div>
                  </div>
                  <div style="background:rgba(15,23,42,0.5);border:1px solid rgba(51,65,85,0.5);
                               border-radius:8px;padding:8px 12px;">
                    <span style="font-size:0.65rem;font-weight:700;text-transform:uppercase;
                                 letter-spacing:0.05em;color:#475569;">Trace ID</span>
                    <div style="font-family:monospace;font-size:0.75rem;color:#94a3b8;
                                margin-top:2px;word-break:break-all;">{html.escape(_trace_id)}</div>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
    else:
        st.info("Run a flow to populate the Incident Summary.")

with tab_approval:
    if not workflow:
        st.info("Run a flow first. The approval form will be prefilled with incident and recommendation IDs.")
    else:
        _rec_action = str(recommendation.get("recommended_action", "Rollback deployment"))
        _rec_risk = str(recommendation.get("risk", "medium")).upper()
        _rec_impact = str(recommendation.get("impact", "N/A"))
        _inc_id_val = str(incident.get("id", ""))
        _rec_id_val = str(recommendation.get("id", ""))
        _trace_val = str(gateway_response.get("trace_id", ""))

        # ── Incident context card ──
        st.markdown(
            f"""
            <div class="kaiops-approval-card">
              <div class="kaiops-approval-title">&#128274; Approval Workbench</div>
              <div style="color:#94a3b8;font-size:0.82rem;line-height:1.45;margin:-6px 0 14px;">
                Review the agent recommendation, confirm blast radius, and submit a policy-aware decision.
              </div>
              <div class="kaiops-approval-kv-row">
                <div class="kaiops-approval-kv">
                  <div class="kaiops-approval-kv-label">Alert</div>
                  <div class="kaiops-approval-kv-value">{html.escape(str(alert.get('name','N/A')))}</div>
                </div>
                <div class="kaiops-approval-kv">
                  <div class="kaiops-approval-kv-label">Service</div>
                  <div class="kaiops-approval-kv-value">{html.escape(str(alert.get('service','N/A')))}</div>
                </div>
                <div class="kaiops-approval-kv">
                  <div class="kaiops-approval-kv-label">Severity</div>
                  <div class="kaiops-approval-kv-value">{html.escape(str(metrics.get('severity','N/A')).upper())}</div>
                </div>
                <div class="kaiops-approval-kv">
                  <div class="kaiops-approval-kv-label">Recommended Action</div>
                  <div class="kaiops-approval-kv-value">{html.escape(_rec_action)}</div>
                </div>
                <div class="kaiops-approval-kv">
                  <div class="kaiops-approval-kv-label">Impact</div>
                  <div class="kaiops-approval-kv-value">{html.escape(_rec_impact)}</div>
                </div>
                <div class="kaiops-approval-kv">
                  <div class="kaiops-approval-kv-label">Risk Level</div>
                  <div class="kaiops-approval-kv-value">{html.escape(_rec_risk)}</div>
                </div>
                <div class="kaiops-approval-kv">
                  <div class="kaiops-approval-kv-label">Policy Gate</div>
                  <div class="kaiops-approval-kv-value">
                    {'Human approval required' if metrics.get('approval_required') else 'Auto-approval allowed'}
                  </div>
                </div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # ── Approval form ──
        st.markdown("#### Submit Approval Decision")
        with st.container(border=True):
            st.caption("The decision is routed through the API Gateway and captured in the audit/trace stream.")
            col_l, col_r = st.columns(2)
            with col_l:
                approval_incident_id = st.text_input(
                    "Incident ID", value=_inc_id_val, key="approval_inc_id"
                )
                approver = st.text_input("Approver email", value="sre@example.com")
                comment = st.text_input(
                    "Action / Comment", value=_rec_action, help="Override action here if modifying"
                )
            with col_r:
                recommendation_id = st.text_input(
                    "Recommendation ID", value=_rec_id_val, key="approval_rec_id"
                )
                channel = st.selectbox("Notification channel", ["web", "slack", "teams", "email"])

            payload = {
                "incident_id": approval_incident_id,
                "recommendation_id": recommendation_id,
                "approver": approver,
                "channel": channel,
                "comment": comment,
            }

            st.markdown("")
            col_approve, col_reject, col_modify = st.columns(3)
            if col_approve.button("✓ Approve", type="primary", width="stretch"):
                st.session_state["approval_response"] = request_json(
                    "POST", f"{GATEWAY_BASE}/approval/approve", json=payload
                )
            if col_reject.button("✗ Reject", width="stretch"):
                st.session_state["approval_response"] = request_json(
                    "POST", f"{GATEWAY_BASE}/approval/reject", json=payload
                )
            if col_modify.button("⟳ Modify", width="stretch"):
                payload["modified_action"] = comment
                st.session_state["approval_response"] = request_json(
                    "POST", f"{GATEWAY_BASE}/approval/modify", json=payload
                )

        # ── Result ──
        approval_response = st.session_state.get("approval_response", {})
        if approval_response:
            approval_data = approval_response.get("data", {})
            approval_gateway = approval_response.get("gateway", {})
            _decision = str(approval_data.get("decision", "unknown")).upper()
            _result_class = (
                "kaiops-approval-result-approved" if _decision == "APPROVED"
                else "kaiops-approval-result-rejected" if _decision == "REJECTED"
                else "kaiops-approval-result-modified"
            )
            _icon = "✓" if _decision == "APPROVED" else ("✗" if _decision == "REJECTED" else "⟳")
            st.markdown(
                f"""
                <div class="kaiops-approval-result {_result_class}">
                  <b>{_icon} Decision: {_decision}</b>
                  &nbsp;·&nbsp; Channel: {html.escape(str(approval_data.get('channel','N/A')))}
                  &nbsp;·&nbsp; Approver: {html.escape(str(approval_data.get('approver','N/A')))}
                  &nbsp;·&nbsp; Gateway: {html.escape(str(approval_gateway.get('safety',{{}}).get('decision','N/A')).upper())}
                </div>
                """,
                unsafe_allow_html=True,
            )
            render_copyable_id("Approval ID", approval_data.get("id"))
            render_copyable_id("Approval Trace ID", approval_response.get("trace_id"))

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
