from __future__ import annotations

import html
import os
import re
import time
from typing import Any
from urllib.parse import quote

import httpx
import streamlit as st
from agent_center import render_agent_command_center
from session_controller import apply_guidance_selection, apply_workflow_payload, ensure_ui_defaults
from workflow_actions import fetch_guidance_matches, run_selected_flow

GATEWAY_BASE = os.getenv("API_GATEWAY_URL", "http://localhost:8010")
MONITORING_ADAPTER_BASE = os.getenv("MONITORING_ADAPTER_URL", "http://localhost:8001")
MYSQL_MONITOR_BASE = os.getenv("MYSQL_MONITOR_URL", "http://localhost:8011")
UI_REQUEST_TIMEOUT_SECONDS = float(os.getenv("UI_REQUEST_TIMEOUT_SECONDS", "240"))

def _agent_icon_data_uri(glyph: str, background: str) -> str:
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' width='44' height='44' viewBox='0 0 44 44'>"
        f"<rect width='44' height='44' rx='10' fill='{background}'/>"
        f"<text x='22' y='28' text-anchor='middle' font-size='16' font-family='Segoe UI, Arial' "
        "font-weight='700' fill='#ffffff'>"
        f"{html.escape(glyph)}"
        "</text></svg>"
    )
    return f"data:image/svg+xml;utf8,{quote(svg)}"


AGENT_PROFILES: dict[str, dict[str, str]] = {
    "Alert Intelligence Agent": {
        "icon_image": _agent_icon_data_uri("AI", "#ef4444"),
        "mission": "Detects and enriches incoming alert signals.",
        "tone": "signal",
    },
    "Orchestrator Agent": {
        "icon_image": _agent_icon_data_uri("OR", "#2563eb"),
        "mission": "Selects workflow path and delegates downstream tasks.",
        "tone": "orchestrator",
    },
    "Context Intelligence Agent": {
        "icon_image": _agent_icon_data_uri("CX", "#0ea5e9"),
        "mission": "Collects dependencies, runbooks, and change evidence.",
        "tone": "context",
    },
    "Resolution Intelligence Agent": {
        "icon_image": _agent_icon_data_uri("RC", "#f97316"),
        "mission": "Produces root cause analysis and remediation recommendation.",
        "tone": "resolution",
    },
    "Human Approval Layer": {
        "icon_image": _agent_icon_data_uri("HA", "#14b8a6"),
        "mission": "Applies policy-aware human gate decisions.",
        "tone": "approval",
    },
    "Remediation Automation Engine": {
        "icon_image": _agent_icon_data_uri("RM", "#16a34a"),
        "mission": "Executes remediation strategy with auditable output.",
        "tone": "automation",
    },
    "Closure & Validation": {
        "icon_image": _agent_icon_data_uri("CL", "#7c3aed"),
        "mission": "Validates recovery and records lessons learned.",
        "tone": "closure",
    },
}


def request_json(method: str, url: str, show_error: bool = True, **kwargs) -> dict[str, Any]:
    try:
        with httpx.Client(timeout=UI_REQUEST_TIMEOUT_SECONDS) as client:
            response = client.request(method, url, **kwargs)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as exc:
        if show_error:
            st.error(f"Unable to reach {url}. Is the target service running? {exc}")
        return {}


def request_json_with_fallback(
    method: str,
    paths: list[str],
    *,
    suppress_last_error: bool = False,
    **kwargs,
) -> dict[str, Any]:
    last_path = paths[-1] if paths else ""
    for path in paths[:-1]:
        response = request_json(method, path, show_error=False, **kwargs)
        if response:
            return response
    if last_path:
        return request_json(method, last_path, show_error=not suppress_last_error, **kwargs)
    return {}


def test_connectivity(url: str, headers: dict[str, str] | None = None) -> tuple[bool, str]:
    endpoint = (url or "").strip()
    if not endpoint:
        return False, "Endpoint URL is required."
    try:
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            response = client.get(endpoint, headers=headers or {})
        if response.status_code < 400:
            return True, f"Connected (HTTP {response.status_code})"
        preview = response.text[:180].replace("\n", " ").strip()
        return False, f"HTTP {response.status_code}: {preview or 'Request failed'}"
    except Exception as exc:
        return False, f"Connection failed: {exc}"


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


@st.cache_data(ttl=300, show_spinner="Loading alert catalog…")
def _fetch_flows_cached() -> list[dict[str, Any]]:
    """Cross-session cached flow catalog fetch (TTL 5 min)."""
    try:
        with httpx.Client(timeout=12.0) as client:
            resp = client.get(f"{GATEWAY_BASE}/sample/flows")
            resp.raise_for_status()
            data = resp.json()
        inner = data.get("data", data)
        return inner.get("flows", [])
    except Exception:
        return []


@st.cache_data(ttl=10, show_spinner=False)
def _fetch_recent_alerts_cached(limit: int = 50) -> list[dict[str, Any]]:
    try:
        with httpx.Client(timeout=8.0) as client:
            resp = client.get(f"{GATEWAY_BASE}/alerts/recent", params={"limit": max(1, int(limit))})
            resp.raise_for_status()
            payload = resp.json()
        inner = payload.get("data", payload)
        rows = inner.get("rows", []) if isinstance(inner, dict) else []
        return [row for row in rows if isinstance(row, dict)]
    except Exception:
        return []


@st.cache_data(ttl=8, show_spinner=False)
def _fetch_all_alerts_cached(limit: int = 500) -> list[dict[str, Any]]:
    try:
        with httpx.Client(timeout=8.0) as client:
            resp = client.get(f"{GATEWAY_BASE}/alerts/all", params={"limit": max(1, int(limit))})
            resp.raise_for_status()
            payload = resp.json()
        inner = payload.get("data", payload)
        rows = inner.get("rows", []) if isinstance(inner, dict) else []
        return [row for row in rows if isinstance(row, dict)]
    except Exception:
        return []


def fetch_monitoring_alert_config() -> dict[str, Any]:
    response = request_json("GET", f"{MYSQL_MONITOR_BASE}/alerts/config", show_error=False)
    return response if isinstance(response, dict) else {}


def save_monitoring_alert_config(payload: dict[str, Any]) -> tuple[bool, str]:
    response = request_json("POST", f"{MYSQL_MONITOR_BASE}/alerts/config", json=payload, show_error=False)
    if response and isinstance(response, dict):
        return True, "Monitoring alert config saved."
    return False, "Unable to save config. Check mysql-monitor availability."


def _build_live_alert_stream_entries(recent_alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for row in recent_alerts:
        alert_name = str(row.get("name") or "Live Alert").strip()
        alert_id = str(row.get("id") or row.get("trace_id") or "LIVE").strip()
        service = str(row.get("service") or "unknown").strip() or "unknown"
        severity = str(row.get("severity") or "warning").strip().upper()
        description = str(row.get("description") or "").strip()
        entries.append(
            {
                "id": f"live-{alert_id}",
                "alert_id": alert_id,
                "alert_name": alert_name,
                "title": alert_name,
                "service": service,
                "severity": severity,
                "recommended_action": "Investigate",
                "description": description,
                "is_live_alert": True,
            }
        )
    return entries


def _match_live_alert_to_flow_id(alert_row: dict[str, Any], flow_entries: list[dict[str, Any]]) -> str | None:
    if not flow_entries:
        return None

    source = str(alert_row.get("source") or "").strip().lower()
    service = str(alert_row.get("service") or "").strip().lower()
    alert_name = str(alert_row.get("name") or "").strip().lower()
    description = str(alert_row.get("description") or "").strip().lower()
    blob = f"{service} {alert_name} {description} {source}".strip()

    best_flow_id: str | None = None
    best_score = -1
    for flow in flow_entries:
        if not isinstance(flow, dict):
            continue
        flow_id = str(flow.get("id") or "").strip()
        if not flow_id:
            continue

        flow_service = str(flow.get("service") or "").strip().lower()
        flow_name = str(flow.get("alert_name") or flow.get("title") or "").strip().lower()
        flow_source = str(flow.get("source") or "").strip().lower()
        flow_blob = f"{flow_service} {flow_name} {flow_source}".strip()

        score = 0
        if service and flow_service and service == flow_service:
            score += 6
        if service and flow_service and service in flow_service:
            score += 2
        if "mysql" in blob and "mysql" in flow_blob:
            score += 8
        if "unavailable" in blob and "unavailable" in flow_blob:
            score += 4

        shared_tokens = [token for token in ("mysql", "replica", "lag", "latency", "timeout", "unavailable") if token in blob and token in flow_blob]
        score += len(shared_tokens)

        if score > best_score:
            best_score = score
            best_flow_id = flow_id

    return best_flow_id if best_score > 0 else None


def _build_alert_stream_entries_from_all_alerts(
    all_alerts: list[dict[str, Any]],
    *,
    flow_entries: list[dict[str, Any]] | None = None,
    limit: int = 120,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    known_flows = flow_entries or []
    ordered_alerts = sorted(
        [row for row in all_alerts if isinstance(row, dict)],
        key=lambda row: str(row.get("created_at") or ""),
        reverse=True,
    )
    for row in ordered_alerts[: max(1, int(limit))]:
        alert_name = str(row.get("name") or "Live Alert").strip()
        alert_id = str(row.get("id") or row.get("trace_id") or "LIVE").strip()
        service = str(row.get("service") or "unknown").strip() or "unknown"
        severity = str(row.get("severity") or "warning").strip().upper()
        description = str(row.get("description") or "").strip()
        source = str(row.get("source") or "monitoring").strip()
        mapped_flow_id = _match_live_alert_to_flow_id(row, known_flows)
        entries.append(
            {
                "id": f"live-{alert_id}",
                "alert_id": alert_id,
                "alert_name": alert_name,
                "title": alert_name,
                "service": service,
                "severity": severity,
                "recommended_action": "Investigate",
                "description": description,
                "source": source,
                "flow_id": mapped_flow_id,
                "is_live_alert": True,
            }
        )
    return entries


@st.cache_data(ttl=20, show_spinner=False)
def _check_service_health() -> dict[str, bool]:
    """Cached health check for homepage status pills (TTL 20 s)."""
    checks: dict[str, bool] = {"gateway": False, "monitoring_adapter": False, "rag": False}
    try:
        with httpx.Client(timeout=4.0) as client:
            r = client.get(f"{GATEWAY_BASE}/healthz")
            checks["gateway"] = r.status_code < 400
    except Exception:
        pass
    adapter_base = GATEWAY_BASE.replace(":8010", ":8001")
    try:
        with httpx.Client(timeout=4.0) as client:
            r = client.get(f"{adapter_base}/healthz")
            checks["monitoring_adapter"] = r.status_code < 400
    except Exception:
        pass
    checks["rag"] = bool(_fetch_flows_cached())
    return checks


@st.cache_data(ttl=15, show_spinner=False)
def _fetch_observability_summary_cached() -> dict[str, Any]:
    """Cached gateway observability summary (TTL 15 s)."""
    try:
        with httpx.Client(timeout=8.0) as client:
            resp = client.get(f"{GATEWAY_BASE}/observability/summary")
            resp.raise_for_status()
            return resp.json()
    except Exception:
        return {}


@st.cache_data(ttl=10, show_spinner=False)
def _fetch_observability_recent_cached() -> dict[str, Any]:
    """Cached gateway recent events (TTL 10 s)."""
    try:
        with httpx.Client(timeout=8.0) as client:
            resp = client.get(f"{GATEWAY_BASE}/observability/recent")
            resp.raise_for_status()
            return resp.json()
    except Exception:
        return {}


@st.cache_data(ttl=6, show_spinner=False)
def _fetch_closed_incidents_cached(limit: int = 120) -> list[dict[str, Any]]:
    try:
        with httpx.Client(timeout=8.0) as client:
            resp = client.get(f"{GATEWAY_BASE}/incidents/closed", params={"limit": max(1, int(limit))})
            resp.raise_for_status()
            payload = resp.json()
        inner = payload.get("data", payload)
        rows = inner.get("rows", []) if isinstance(inner, dict) else []
        return [row for row in rows if isinstance(row, dict)]
    except Exception:
        return []


def get_flows(recent_alerts: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    flow_entries = _fetch_flows_cached()
    live_source = recent_alerts if recent_alerts is not None else _fetch_recent_alerts_cached(limit=50)
    live_entries = _build_live_alert_stream_entries(live_source)
    combined = live_entries + flow_entries
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in combined:
        key = str(item.get("id") or item.get("alert_id") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def get_alert_stream_entries(all_alerts: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    flow_entries = _fetch_flows_cached()
    live_entries = _build_alert_stream_entries_from_all_alerts(
        all_alerts or _fetch_all_alerts_cached(limit=500),
        flow_entries=flow_entries,
    )
    combined = live_entries + flow_entries
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in combined:
        key = str(item.get("id") or item.get("alert_id") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


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


def _normalize_alert_source(value: Any) -> str:
    source = str(value or "").strip().lower()
    return source or "unknown"


def _derive_alert_runtime_state(item: dict[str, Any]) -> tuple[str, str]:
    """Return (state_label, color_hex) from alert payload fields and known failure indicators."""
    explicit = str(item.get("status") or item.get("state") or item.get("health") or "").strip().lower()
    if explicit:
        if explicit in {"failed", "failure", "error", "down", "unhealthy", "stopped", "offline", "critical"}:
            return "FAILED", "#dc2626"
        if explicit in {"running", "ok", "healthy", "up", "online", "success", "active"}:
            return "RUNNING", "#16a34a"

    source = _normalize_alert_source(item.get("source"))
    name = str(item.get("alert_name") or item.get("title") or item.get("name") or "").lower()
    description = str(item.get("description") or "").lower()
    severity = str(item.get("severity") or "").strip().upper()
    failure_terms = ("fail", "failed", "failure", "unavailable", "down", "timeout", "error", "lag")
    has_failure_terms = any(term in name or term in description for term in failure_terms)

    if "mysql" in source and (severity in {"CRITICAL", "HIGH"} or has_failure_terms):
        return "FAILED", "#dc2626"
    if severity == "CRITICAL" or has_failure_terms:
        return "FAILED", "#dc2626"
    return "RUNNING", "#16a34a"


def render_alert_stream(entries: list[dict[str, Any]]) -> str | None:
    if not entries:
        st.caption("No alert stream entries available yet.")
        return None

    enriched_entries: list[dict[str, Any]] = []
    for item in entries:
        source = _normalize_alert_source(item.get("source"))
        source_label = "mysql" if "mysql" in source else source
        runtime_state, runtime_color = _derive_alert_runtime_state(item)
        enriched_entries.append(
            {
                "item": item,
                "source_label": source_label,
                "runtime_state": runtime_state,
                "runtime_color": runtime_color,
            }
        )

    mysql_total = 0
    mysql_failed = 0
    other_total = 0
    other_failed = 0
    for entry in enriched_entries:
        source_label = str(entry["source_label"])
        state_label = str(entry["runtime_state"])
        is_mysql = source_label == "mysql"
        if is_mysql:
            mysql_total += 1
            if state_label == "FAILED":
                mysql_failed += 1
        else:
            other_total += 1
            if state_label == "FAILED":
                other_failed += 1

    st.caption(
        "MySQL alerts: "
        f"{mysql_total} (FAILED {mysql_failed}, RUNNING {max(0, mysql_total - mysql_failed)}) | "
        "Other alerts: "
        f"{other_total} (FAILED {other_failed}, RUNNING {max(0, other_total - other_failed)})"
    )

    source_filter_col, state_filter_col = st.columns(2)
    with source_filter_col:
        source_filter = st.selectbox(
            "Source",
            ["All", "MySQL", "Others"],
            index=0,
            key="kaiops_alert_stream_source_filter",
        )
    with state_filter_col:
        state_filter = st.selectbox(
            "State",
            ["All", "Failed", "Running"],
            index=0,
            key="kaiops_alert_stream_state_filter",
        )

    filtered_entries = enriched_entries
    if source_filter == "MySQL":
        filtered_entries = [entry for entry in filtered_entries if str(entry["source_label"]) == "mysql"]
    elif source_filter == "Others":
        filtered_entries = [entry for entry in filtered_entries if str(entry["source_label"]) != "mysql"]

    if state_filter == "Failed":
        filtered_entries = [entry for entry in filtered_entries if str(entry["runtime_state"]) == "FAILED"]
    elif state_filter == "Running":
        filtered_entries = [entry for entry in filtered_entries if str(entry["runtime_state"]) == "RUNNING"]

    if not filtered_entries:
        st.caption("No alerts match the selected filters.")
        return None

    selected_flow_id: str | None = None
    for entry in filtered_entries[:20]:
        item = entry["item"]
        alert_id = str(item.get("alert_id") or item.get("id") or "N/A")
        alert_name = str(item.get("alert_name") or item.get("title") or "Alert")
        service = str(item.get("service") or "unknown")
        source_label = str(entry["source_label"])
        severity = str(item.get("severity") or "unknown").upper()
        recommended_action = str(item.get("recommended_action") or "").strip()
        flow_id = str(item.get("id") or "").strip()
        mapped_flow_id = str(item.get("flow_id") or "").strip()
        executable_flow_id = mapped_flow_id or (flow_id if not bool(item.get("is_live_alert", False)) else "")
        mapping_label = (
            f"Mapped Flow: {executable_flow_id}"
            if executable_flow_id
            else "Mapped Flow: none (guidance fallback)"
        )
        runtime_state = str(entry["runtime_state"])
        runtime_color = str(entry["runtime_color"])

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
                f'{service} · {severity} · {source_label} · '
                f'<span style="color:{runtime_color};font-weight:700;">{runtime_state}</span> · excluded from auto-run</div></div>',
                unsafe_allow_html=True,
            )
            st.caption(mapping_label)
        else:
            button_label = f"{alert_id} | {alert_name}"
            clicked = False
            if executable_flow_id:
                clicked = bool(
                    st.button(
                        button_label,
                        key=f"kaiops_alert_stream_{alert_id}_{executable_flow_id}",
                        width="stretch",
                    )
                )
            else:
                clicked = bool(
                    st.button(
                        f"{alert_id} | {alert_name} (Open Guidance)",
                        key=f"kaiops_alert_guidance_{alert_id}",
                        width="stretch",
                    )
                )
            if clicked:
                if executable_flow_id:
                    selected_flow_id = executable_flow_id
                else:
                    guidance_query = " ".join(
                        part
                        for part in [service, alert_name, str(item.get("description", "")), "issue troubleshooting resolution"]
                        if part
                    ).strip()
                    selected_flow_id = f"__guidance__::{guidance_query}"
            st.markdown(
                f'<span class="kaiops-alert-badge {badge_class}">{badge_label}</span>'
                f' <span style="font-size:0.7rem; color:#94a3b8; margin-bottom:4px;">'
                f'{service} · {severity} · {source_label} · '
                f'<span style="color:{runtime_color};font-weight:700;">{runtime_state}</span></span>',
                unsafe_allow_html=True,
            )
            st.caption(mapping_label)
    return selected_flow_id


def first_actionable_flow(entries: list[dict[str, Any]]) -> str | None:
    for item in entries:
        if bool(item.get("is_live_alert", False)):
            continue
        severity = str(item.get("severity") or "unknown").upper()
        recommended_action = str(item.get("recommended_action") or "").strip()
        alert_name = str(item.get("alert_name") or item.get("title") or "")
        flow_id = str(item.get("id") or "").strip()
        if not flow_id:
            continue
        _, badge_label = _alert_stream_status(severity, recommended_action, alert_name)
        if badge_label not in ("DUPLICATE", "NO ACTION", "IGNORE"):
            return flow_id
    return None


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
        {
            "icon_image": _agent_icon_data_uri("AG", "#64748b"),
            "mission": "Coordinates incident-resolution logic.",
            "tone": "default",
        },
    )


def render_agent_event_details(event: dict[str, Any]) -> None:
    profile = get_agent_profile(str(event.get("agent", "")))
    st.markdown(f"### {event.get('agent', 'Agent')} | Deep Dive")
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


def render_project_onboarding_section() -> None:
    st.markdown("## Project Onboarding")
    st.caption("Create a project and configure observability integrations.")

    if "onboarding_project" not in st.session_state:
        st.session_state["onboarding_project"] = {}
    if "onboarding_connectivity" not in st.session_state:
        st.session_state["onboarding_connectivity"] = {}
    if "onboarding_status" not in st.session_state:
        st.session_state["onboarding_status"] = {}
    if "onboarding_loaded" not in st.session_state:
        st.session_state["onboarding_loaded"] = False
    if "onboarding_rows" not in st.session_state:
        st.session_state["onboarding_rows"] = []

    provider_defaults = {
        "Prometheus": {
            "url": "http://localhost:9090/-/ready",
            "key_label": None,
            "key_type": None,
            "header_name": None,
        },
        "New Relic": {
            "url": "https://api.newrelic.com/v2/applications.json",
            "key_label": "New Relic API key",
            "key_type": "password",
            "header_name": "Api-Key",
        },
        "Datadog": {
            "url": "https://api.datadoghq.com/api/v1/validate",
            "key_label": "Datadog API key",
            "key_type": "password",
            "header_name": "DD-API-KEY",
        },
    }

    if not st.session_state["onboarding_loaded"]:
        persisted_response = request_json_with_fallback(
            "GET",
            [
                f"{GATEWAY_BASE}/onboarding/connectivity",
                f"{MONITORING_ADAPTER_BASE}/onboarding/connectivity",
            ],
        )
        persisted = data_from_gateway(persisted_response).get("connectivity", {}) if persisted_response else {}
        if isinstance(persisted, dict) and persisted:
            st.session_state["onboarding_project"] = persisted.get("project", {})
            st.session_state["onboarding_connectivity"] = {
                "prometheus_url": str(persisted.get("prometheus_url", "")).strip(),
                "new_relic_url": str(persisted.get("new_relic_url", "")).strip(),
                "datadog_url": str(persisted.get("datadog_url", "")).strip(),
                "updated_at": persisted.get("updated_at"),
            }
        state_response = request_json_with_fallback(
            "GET",
            [f"{GATEWAY_BASE}/onboarding/state", f"{MONITORING_ADAPTER_BASE}/onboarding/state"],
            suppress_last_error=True,
        )
        state_rows = data_from_gateway(state_response).get("rows", []) if state_response else []
        if isinstance(state_rows, list):
            st.session_state["onboarding_rows"] = [row for row in state_rows if isinstance(row, dict)]
        st.session_state["onboarding_loaded"] = True

    def refresh_onboarding_rows() -> None:
        state_response = request_json_with_fallback(
            "GET",
            [f"{GATEWAY_BASE}/onboarding/state", f"{MONITORING_ADAPTER_BASE}/onboarding/state"],
            suppress_last_error=True,
        )
        state_rows = data_from_gateway(state_response).get("rows", []) if state_response else []
        if isinstance(state_rows, list):
            st.session_state["onboarding_rows"] = [row for row in state_rows if isinstance(row, dict)]

    with st.container(border=True):
        st.markdown("### Project Setup")
        with st.form("project_onboarding_form"):
            col_a, col_b = st.columns(2)
            with col_a:
                project_name = st.text_input("Project name", value=st.session_state["onboarding_project"].get("name", ""))
                owner_team = st.text_input("Owner team", value=st.session_state["onboarding_project"].get("owner_team", "platform-ops"))
            with col_b:
                env_options = ["dev", "staging", "prod"]
                current_env = st.session_state["onboarding_project"].get("environment", "prod")
                env_index = env_options.index(current_env) if current_env in env_options else 2
                environment = st.selectbox("Environment", env_options, index=env_index)
                region = st.text_input("Region", value=st.session_state["onboarding_project"].get("region", "us-east-1"))

            save_project = st.form_submit_button("Save Project", type="primary", use_container_width=True)
            if save_project:
                project_name_value = str(project_name or "").strip()
                owner_team_value = str(owner_team or "").strip()
                region_value = str(region or "").strip()
                st.session_state["onboarding_project"] = {
                    "name": project_name_value,
                    "owner_team": owner_team_value,
                    "environment": environment,
                    "region": region_value,
                }
                payload = {
                    "project": st.session_state["onboarding_project"],
                    "prometheus_url": st.session_state["onboarding_connectivity"].get("prometheus_url", provider_defaults["Prometheus"]["url"]),
                    "new_relic_url": st.session_state["onboarding_connectivity"].get("new_relic_url", provider_defaults["New Relic"]["url"]),
                    "datadog_url": st.session_state["onboarding_connectivity"].get("datadog_url", provider_defaults["Datadog"]["url"]),
                    "provider_statuses": st.session_state.get("onboarding_status", {}),
                    "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
                save_response = request_json_with_fallback(
                    "POST",
                    [f"{GATEWAY_BASE}/onboarding/connectivity", f"{MONITORING_ADAPTER_BASE}/onboarding/connectivity"],
                    json=payload,
                )
                persisted = data_from_gateway(save_response).get("connectivity", {}) if save_response else {}
                if persisted:
                    st.session_state["onboarding_connectivity"] = persisted
                    refresh_onboarding_rows()
                    st.success("Project details saved and persisted to MySQL.")
                else:
                    st.success("Project details saved.")

        st.markdown("#### Configure Connectivity")
        provider_options = ["Prometheus", "New Relic", "Datadog"]
        selected_provider = st.selectbox(
            "Connectivity provider",
            provider_options,
            key="onboarding_provider_selector",
        )

        provider_key_map = {
            "Prometheus": "prometheus_url",
            "New Relic": "new_relic_url",
            "Datadog": "datadog_url",
        }
        selected_key = provider_key_map[selected_provider]
        provider_config = provider_defaults[selected_provider]
        provider_values = st.session_state["onboarding_connectivity"]
        connectivity_url = st.text_input(
            f"{selected_provider} endpoint",
            value=provider_values.get(selected_key, provider_config["url"]),
            key=f"onboard_{selected_key}",
        )
        secret_value = None
        if provider_config["key_label"]:
            secret_value = st.text_input(
                provider_config["key_label"],
                value="",
                type=provider_config["key_type"],
                key=f"onboard_{selected_key}_secret",
            )

        if st.button(f"Test {selected_provider}", key="test_selected_provider", use_container_width=True):
            connectivity_endpoint = str(connectivity_url or "").strip()
            headers: dict[str, str] = {}
            if provider_config["header_name"] and secret_value:
                headers[provider_config["header_name"]] = secret_value
            ok, message = test_connectivity(connectivity_endpoint, headers=headers)
            provider_key = selected_provider.lower().replace(" ", "_")
            st.session_state["onboarding_connectivity"][selected_key] = connectivity_endpoint
            st.session_state["onboarding_status"][provider_key] = {"ok": ok, "message": message}
            payload = {
                "project": st.session_state.get("onboarding_project", {}),
                "prometheus_url": st.session_state["onboarding_connectivity"].get("prometheus_url", provider_defaults["Prometheus"]["url"]),
                "new_relic_url": st.session_state["onboarding_connectivity"].get("new_relic_url", provider_defaults["New Relic"]["url"]),
                "datadog_url": st.session_state["onboarding_connectivity"].get("datadog_url", provider_defaults["Datadog"]["url"]),
                "provider_statuses": st.session_state["onboarding_status"],
                "active_provider": provider_key,
                "test_status": ok,
                "test_message": message,
                "tested_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            request_json_with_fallback(
                "POST",
                [f"{GATEWAY_BASE}/onboarding/connectivity", f"{MONITORING_ADAPTER_BASE}/onboarding/connectivity"],
                json=payload,
            )
            refresh_onboarding_rows()
            st.success(message) if ok else st.error(message)

        if st.button("Save Connectivity Configuration", key="save_connectivity", use_container_width=True):
            st.session_state["onboarding_connectivity"][selected_key] = str(connectivity_url or "").strip()
            payload = {
                "project": st.session_state.get("onboarding_project", {}),
                "prometheus_url": st.session_state["onboarding_connectivity"].get("prometheus_url", provider_defaults["Prometheus"]["url"]),
                "new_relic_url": st.session_state["onboarding_connectivity"].get("new_relic_url", provider_defaults["New Relic"]["url"]),
                "datadog_url": st.session_state["onboarding_connectivity"].get("datadog_url", provider_defaults["Datadog"]["url"]),
                "provider_statuses": st.session_state.get("onboarding_status", {}),
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            save_response = request_json_with_fallback(
                "POST",
                [f"{GATEWAY_BASE}/onboarding/connectivity", f"{MONITORING_ADAPTER_BASE}/onboarding/connectivity"],
                json=payload,
            )
            persisted = data_from_gateway(save_response).get("connectivity", {}) if save_response else {}
            if persisted:
                st.session_state["onboarding_connectivity"] = persisted
                refresh_onboarding_rows()
                st.success("Connectivity configuration persisted.")

        if st.session_state.get("onboarding_status"):
            st.markdown("#### Connectivity Status")
            for provider in ("prometheus", "new_relic", "datadog"):
                if provider in st.session_state["onboarding_status"]:
                    state = st.session_state["onboarding_status"][provider]
                    label = provider.replace("_", " ").title()
                    if state.get("ok"):
                        st.success(f"{label}: {state.get('message', 'Connected')}")
                    else:
                        st.error(f"{label}: {state.get('message', 'Not connected')}")

        st.markdown("#### Saved onboarding rows")
        onboarding_rows = st.session_state.get("onboarding_rows", [])
        if onboarding_rows:
            table_rows = []
            for row in onboarding_rows:
                table_rows.append(
                    {
                        "Project": row.get("project_name", ""),
                        "Provider": str(row.get("provider_name", "")).replace("_", " ").title(),
                        "Environment": row.get("environment", ""),
                        "Region": row.get("region", ""),
                        "Endpoint": row.get("endpoint_url", ""),
                        "Status": row.get("test_status", ""),
                        "Last Tested": row.get("last_tested_at") or row.get("updated_at"),
                    }
                )
            st.dataframe(table_rows, hide_index=True, use_container_width=True)
        else:
            st.caption("No onboarding rows have been saved to MySQL yet.")


st.set_page_config(page_title="KaiOps", page_icon="K", layout="wide", initial_sidebar_state="expanded")

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
            .kaiops-role-card {
                background: linear-gradient(180deg, #ffffff, #f8fafc);
                border: 1px solid #dbe4ef;
                border-radius: 10px;
                min-height: 245px;
                padding: 12px 14px;
                display: flex;
                flex-direction: column;
                gap: 8px;
            }
            .kaiops-role-step {
                font-size: 0.78rem;
                color: #6b7280;
                margin: 0;
            }
            .kaiops-role-title-row {
                display: flex;
                align-items: flex-start;
                gap: 8px;
                min-height: 48px;
            }
            .kaiops-role-icon {
                width: 28px;
                height: 28px;
                border-radius: 8px;
                border: 1px solid #dbe4ef;
                flex-shrink: 0;
            }
            .kaiops-role-title {
                margin: 0;
                color: #0f172a;
                font-size: 1.03rem;
                font-weight: 700;
                line-height: 1.35;
                flex: 1;
            }
            .kaiops-role-help {
                color: #64748b;
                font-size: 0.9rem;
                cursor: help;
                user-select: none;
            }
            .kaiops-role-decision {
                margin-top: auto;
                border-radius: 8px;
                padding: 10px 12px;
                min-height: 56px;
                font-size: 0.95rem;
                line-height: 1.45;
                display: flex;
                align-items: center;
            }
            .kaiops-role-decision-complete {
                background: rgba(16,185,129,0.15);
                color: #047857;
            }
            .kaiops-role-decision-standby {
                background: rgba(59,130,246,0.12);
                color: #1d4ed8;
            }
            .kaiops-agent-pipeline-wrap {
                margin: 6px 0 14px;
                padding: 12px;
                border-radius: 12px;
                background: linear-gradient(180deg, #ffffff, #f8fafc);
                border: 1px solid #dbe4ef;
            }
            .kaiops-agent-pipeline-track {
                display: flex;
                align-items: center;
                gap: 8px;
                overflow-x: auto;
                padding-bottom: 4px;
            }
            .kaiops-agent-pipeline-line {
                width: 18px;
                height: 2px;
                background: #cbd5e1;
                flex: 0 0 18px;
            }
            .kaiops-agent-pipeline-node {
                min-width: 170px;
                border: 1px solid #dbe4ef;
                border-radius: 10px;
                background: #f8fafc;
                padding: 8px 10px;
            }
            .kaiops-agent-pipeline-step {
                font-size: 0.65rem;
                color: #64748b;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.03em;
            }
            .kaiops-agent-pipeline-name {
                margin-top: 2px;
                font-size: 0.82rem;
                color: #0f172a;
                font-weight: 700;
                line-height: 1.25;
            }
            .kaiops-agent-pipeline-status {
                margin-top: 6px;
                font-size: 0.74rem;
                font-weight: 700;
            }
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

_health = _check_service_health()
_dot_gw = "kaiops-hero-pill-dot-amber" if _health.get("gateway") else "kaiops-hero-pill-dot-offline"
_dot_rag = "kaiops-hero-pill-dot-blue" if _health.get("rag") else "kaiops-hero-pill-dot-offline"
_dot_agents = "" if _health.get("monitoring_adapter") else "kaiops-hero-pill-dot-offline"
_gw_label = "Gateway Active" if _health.get("gateway") else "Gateway Offline"
_rag_label = "RAG Grounded" if _health.get("rag") else "RAG Not Ready"
_agents_label = "Agents Online" if _health.get("monitoring_adapter") else "Agents Offline"
recent_alerts_snapshot = _fetch_recent_alerts_cached(limit=50)
all_alerts_snapshot = _fetch_all_alerts_cached(limit=500)
flows = _fetch_flows_cached()
alert_stream_entries = get_alert_stream_entries(all_alerts=all_alerts_snapshot)
ensure_ui_defaults(st.session_state)
workflow = st.session_state.get("workflow", {})
if "flow_catalog_preview" not in st.session_state:
    st.session_state["flow_catalog_preview"] = {
        "data": {"entries": flows, "count": len(flows), "path": "rag/flows.json"}
    }
catalog_preview = st.session_state.get("flow_catalog_preview")
catalog_entries = data_from_gateway(catalog_preview).get("entries", []) if catalog_preview else flows
if "initial_flow_loaded" not in st.session_state:
    st.session_state["initial_flow_loaded"] = False
if "nav_section" not in st.session_state:
    st.session_state["nav_section"] = "home"
if "kaiops_nav_section" in st.session_state:
        st.session_state["nav_section"] = (
                "onboarding" if st.session_state.get("kaiops_nav_section") == "Project Onboarding" else "home"
        )
current_nav_section = st.session_state.get("nav_section", "home")

if current_nav_section != "onboarding":
    sorted_events = sorted(workflow.get("events", []), key=lambda item: item.get("sequence", 0))
    st.markdown(
        f"""
        <style>
            .kaiops-hero-pill-dot-offline {{ background: #64748b !important; }}
        </style>
        <div class="kaiops-hero-wrap">
            <div class="kaiops-hero-label">&#9679; AI-Powered SRE Platform</div>
            <div class="kaiops-hero-title">KaiOps Autonomous Operations</div>            
            <div class="kaiops-hero-pills">
                <span class="kaiops-hero-pill"><span class="kaiops-hero-pill-dot {_dot_agents}"></span> {_agents_label}</span>
                <span class="kaiops-hero-pill"><span class="kaiops-hero-pill-dot {_dot_rag}"></span> {_rag_label}</span>
                <span class="kaiops-hero-pill"><span class="kaiops-hero-pill-dot {_dot_gw}"></span> {_gw_label}</span>
                <span class="kaiops-hero-pill">7-Step Workflow</span>
                <span class="kaiops-hero-pill">GPT-Powered RCA</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
if current_nav_section != "onboarding" and not st.session_state.get("workflow") and not st.session_state.get("initial_flow_loaded"):
    default_flow_id = first_actionable_flow(catalog_entries)
    if default_flow_id:
        st.session_state["selected_flow"] = default_flow_id
        st.session_state["initial_flow_loaded"] = True

if (
    current_nav_section != "onboarding"
    and not st.session_state.get("workflow")
    and not st.session_state.get("alerts_guidance_open")
    and st.session_state.get("selected_flow")
):
    if run_selected_flow(
        str(st.session_state.get("selected_flow", "")),
        gateway_base=GATEWAY_BASE,
        request_json=request_json,
        state=st.session_state,
        fast_mode_enabled=bool(st.session_state.get("fast_mode_enabled", True)),
    ):
        st.session_state["last_flow_refresh_ts"] = time.time()
        st.rerun()

with st.sidebar:
    if current_nav_section != "onboarding":
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
                
            </div>
            """,
            unsafe_allow_html=True,
        )

    menu_choice = st.radio(
        "Menu",
        ["Home", "Project Onboarding"],
        index=0 if current_nav_section != "onboarding" else 1,
        key="kaiops_nav_section",
        horizontal=False,
    )
    st.session_state["nav_section"] = "onboarding" if menu_choice == "Project Onboarding" else "home"

    st.markdown('<div class="kaiops-sidebar-section">Alert Stream</div>', unsafe_allow_html=True)
    with st.container(border=True):
        if alert_stream_entries:
            selected_from_stream = render_alert_stream(alert_stream_entries)
            if selected_from_stream:
                if selected_from_stream.startswith("__guidance__::"):
                    apply_guidance_selection(st.session_state, selected_from_stream.split("::", 1)[1])
                    st.success("Opened RAG guidance for selected live alert.")
                    st.rerun()
                else:
                    if run_selected_flow(
                        selected_from_stream,
                        gateway_base=GATEWAY_BASE,
                        request_json=request_json,
                        state=st.session_state,
                        fast_mode_enabled=bool(st.session_state.get("fast_mode_enabled", True)),
                    ):
                        _fetch_closed_incidents_cached.clear()
                        st.session_state["last_flow_refresh_ts"] = time.time()
                        st.success(f"Flow {selected_from_stream} executed from alert stream.")
                        st.rerun()
        else:
            st.caption("Load the catalog or ingest incident documents to populate the live alert stream.")

    st.markdown('<div class="kaiops-sidebar-section">Monitoring Alert Config</div>', unsafe_allow_html=True)
    with st.container(border=True):
        current_config = fetch_monitoring_alert_config()
        if not current_config:
            st.caption("mysql-monitor config endpoint is not reachable.")
        with st.form("monitoring_alert_config_form"):
            alerts_enabled = st.toggle(
                "Enable MySQL alert ingestion",
                value=bool(current_config.get("alerts_enabled", True)),
            )
            cooldown = st.number_input(
                "Alert cooldown seconds",
                min_value=30,
                max_value=3600,
                value=int(current_config.get("alert_cooldown_seconds", 300) or 300),
                step=10,
            )
            threads_threshold = st.number_input(
                "Threads running threshold",
                min_value=1,
                max_value=100000,
                value=int(current_config.get("threads_running_threshold", 40) or 40),
                step=1,
            )
            slow_queries_threshold = st.number_input(
                "Slow queries delta threshold",
                min_value=1,
                max_value=100000,
                value=int(current_config.get("slow_queries_delta_threshold", 5) or 5),
                step=1,
            )
            aborted_threshold = st.number_input(
                "Aborted connects delta threshold",
                min_value=1,
                max_value=100000,
                value=int(current_config.get("aborted_connects_delta_threshold", 3) or 3),
                step=1,
            )
            alert_endpoint = st.text_input(
                "KaiOps alert endpoint",
                value=str(current_config.get("kaiops_alert_endpoint", f"{GATEWAY_BASE}/alerts")),
            )
            alert_timeout = st.number_input(
                "Alert endpoint timeout seconds",
                min_value=1.0,
                max_value=120.0,
                value=float(current_config.get("kaiops_alert_timeout_seconds", 8.0) or 8.0),
                step=0.5,
            )

            if st.form_submit_button("Save Monitoring Alert Config", use_container_width=True):
                ok, message = save_monitoring_alert_config(
                    {
                        "alerts_enabled": alerts_enabled,
                        "alert_cooldown_seconds": int(cooldown),
                        "threads_running_threshold": int(threads_threshold),
                        "slow_queries_delta_threshold": int(slow_queries_threshold),
                        "aborted_connects_delta_threshold": int(aborted_threshold),
                        "kaiops_alert_endpoint": alert_endpoint.strip(),
                        "kaiops_alert_timeout_seconds": float(alert_timeout),
                    }
                )
                if ok:
                    st.success(message)
                else:
                    st.error(message)

    st.session_state.pop("selected_trace_step", None)

    st.markdown('<div class="kaiops-sidebar-section">Live Monitoring</div>', unsafe_allow_html=True)
    with st.container(border=True):
        fast_mode_enabled = st.toggle(
            "Fast mode (skip model comparisons)",
            value=st.session_state.get("fast_mode_enabled", True),
            help="Runs flows faster by skipping side-by-side model comparison calls.",
        )
        st.session_state["fast_mode_enabled"] = fast_mode_enabled

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
            _fetch_recent_alerts_cached.clear()
            _fetch_all_alerts_cached.clear()
            st.session_state["gateway_summary"] = request_json("GET", f"{GATEWAY_BASE}/observability/summary")
            st.session_state["gateway_recent"] = request_json("GET", f"{GATEWAY_BASE}/observability/recent")
            st.session_state["last_gateway_refresh_ts"] = time.time()
            st.rerun()

if st.session_state.get("nav_section") == "onboarding":
    render_project_onboarding_section()
    st.stop()

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
        _fetch_recent_alerts_cached.clear()
        _fetch_all_alerts_cached.clear()
        st.session_state["gateway_summary"] = request_json("GET", f"{GATEWAY_BASE}/observability/summary")
        st.session_state["gateway_recent"] = request_json("GET", f"{GATEWAY_BASE}/observability/recent")
        st.session_state["last_gateway_refresh_ts"] = now

    if st.session_state.get("flow_rerun_enabled") and st.session_state.get("selected_flow"):
        if now - last_flow_refresh >= flow_interval:
            if run_selected_flow(
                str(st.session_state.get("selected_flow", "")),
                gateway_base=GATEWAY_BASE,
                request_json=request_json,
                state=st.session_state,
                fast_mode_enabled=bool(st.session_state.get("fast_mode_enabled", True)),
            ):
                st.session_state["last_flow_refresh_ts"] = now
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
guidance_query = str(st.session_state.get("alerts_guidance_query", "")).strip()
guidance_open = bool(st.session_state.get("alerts_guidance_open"))
guidance_matches = (
    fetch_guidance_matches(
        guidance_query,
        gateway_base=GATEWAY_BASE,
        request_json=request_json,
        data_from_gateway=data_from_gateway,
        limit=5,
    )
    if guidance_open and guidance_query
    else []
)
render_agent_command_center(
    workflow=workflow,
    agent_profiles=AGENT_PROFILES,
    fallback_icon_data_uri=_agent_icon_data_uri("AG", "#64748b"),
)
grounded_rag_response: dict[str, Any] = {}
if workflow:
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
    if not (guidance_open and guidance_query):
        st.info("Select an incident from Alert Stream to run a flow.")
else:
    _incident_top_name = str(scenario.get("title") or alert.get("name") or "Incident")
    st.markdown(
        f"""
        <div style="margin-bottom:10px;">
            <div style="font-size:1.45rem;font-weight:800;color:#0f172a;line-height:1.2;">
                {html.escape(_incident_top_name)}
            </div>
            <div style="font-size:0.82rem;color:#64748b;margin-top:4px;">
                Incident <b style="color:#334155;">{html.escape(str(incident.get('id', '—')))}</b>
                &nbsp;·&nbsp; Service <b style="color:#334155;">{html.escape(str(alert.get('service', 'N/A')))}</b>
                &nbsp;·&nbsp; Severity <b style="color:#334155;">{html.escape(str(metrics.get('severity', 'unknown')).upper())}</b>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
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

tab_summary, tab_alerts, tab_approval, tab_trace, tab_finops, tab_closed = st.tabs(
    ["Incident Summary", "Alerts Raised", "Approval", "Agent Trace", "FinOps", "Closed Incidents"]
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
        _selected_flow_id = st.session_state.get("selected_flow", "payment-latency")
        _active_flow = next(
            (flow for flow in catalog_entries if str(flow.get("id")) == str(scenario.get("id", _selected_flow_id))),
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
    else:
        st.info("Run a flow to populate the Incident Summary.")

with tab_alerts:
    st.markdown("### Alerts Raised")
    all_alerts = all_alerts_snapshot
    if not all_alerts:
        st.info("No alerts available yet. Ingest alerts via /alerts or wait for mysql-monitor threshold triggers.")
    else:
        severity_options = ["ALL", "CRITICAL", "HIGH", "WARNING", "INFO"]
        selected_severity = st.selectbox("Severity filter", severity_options, index=0, key="alerts_tab_severity")
        filtered = all_alerts
        if selected_severity != "ALL":
            filtered = [
                row for row in all_alerts if str(row.get("severity", "")).upper() == selected_severity
            ]

        st.metric("Total Alerts", len(all_alerts))
        st.metric("Visible Alerts", len(filtered))
        st.dataframe(
            [
                {
                    "Created": row.get("created_at", ""),
                    "Alert": row.get("name", ""),
                    "Source": row.get("source", ""),
                    "Service": row.get("service", ""),
                    "Severity": str(row.get("severity", "")).upper(),
                    "Description": row.get("description", ""),
                    "Trace": row.get("trace_id", ""),
                }
                for row in filtered
            ],
            hide_index=True,
            width="stretch",
        )

        st.markdown("#### Quick Doc Links")
        link_rows = filtered[:20]
        if link_rows:
            for index, row in enumerate(link_rows, start=1):
                alert_name = str(row.get("name", "")).strip()
                service_name = str(row.get("service", "")).strip()
                description = str(row.get("description", "")).strip()
                base_terms = " ".join(part for part in [alert_name, service_name, description] if part).strip()
                runbook_query = f"{base_terms} runbook troubleshooting resolution".strip()
                incident_query = f"{base_terms} incident issue resolution".strip()
                runbook_url = f"{GATEWAY_BASE}/rag/search?query={quote(runbook_query)}&limit=5"
                incident_url = f"{GATEWAY_BASE}/rag/search?query={quote(incident_query)}&limit=5"

                col_name, col_runbook, col_incident = st.columns([2.2, 1, 1])
                with col_name:
                    st.caption(f"{index}. {alert_name or 'Alert'}")
                with col_runbook:
                    st.link_button(
                        "View Runbook",
                        runbook_url,
                        use_container_width=True,
                    )
                with col_incident:
                    st.link_button(
                        "View Incident",
                        incident_url,
                        use_container_width=True,
                    )
        else:
            st.caption("No alert rows available for quick links.")

        st.markdown("#### RAG Guidance (Issue / Troubleshooting / Resolution)")
        default_query = st.session_state.get("alerts_guidance_query", "mysql unavailable issue troubleshooting resolution")
        guidance_query = st.text_input("Guidance query", value=default_query, key="alerts_guidance_query_input")
        if st.button("Search Guidance", key="alerts_guidance_search", use_container_width=True):
            apply_guidance_selection(st.session_state, str(guidance_query or ""))

        if st.session_state.get("alerts_guidance_open") and st.session_state.get("alerts_guidance_query"):
            matches = fetch_guidance_matches(
                str(st.session_state.get("alerts_guidance_query", "")),
                gateway_base=GATEWAY_BASE,
                request_json=request_json,
                data_from_gateway=data_from_gateway,
                limit=5,
            )
            if matches:
                for index, match in enumerate(matches, start=1):
                    title = str(match.get("title") or f"Guidance {index}")
                    kind = str(match.get("kind") or "document").title()
                    preview = str(match.get("preview") or "No preview available.")
                    with st.expander(f"{index}. {title} ({kind})", expanded=(index == 1)):
                        st.markdown(preview)
            else:
                st.caption("No guidance matches found. Try broader keywords like mysql, unavailable, runbook, resolution.")

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
        _approval_pending = str(workflow.get("approval", {}).get("decision", "")).strip().upper() == "PENDING"
        _active_flow_id = str(scenario.get("id") or st.session_state.get("selected_flow", "")).strip()

        if _approval_pending:
            st.warning("High-risk workflow is paused. Submit an approval decision to continue remediation and closure.")

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
                if _approval_pending and _active_flow_id:
                    resume_payload = {**payload, "decision": "approve"}
                    resume_response = request_json(
                        "POST",
                        f"{GATEWAY_BASE}/sample/{_active_flow_id}/workflow/continue",
                        json=resume_payload,
                    )
                    if apply_workflow_payload(st.session_state, _active_flow_id, resume_response):
                        _fetch_closed_incidents_cached.clear()
                        st.success("Approval recorded and workflow completed.")
                        st.rerun()
            if col_reject.button("✗ Reject", width="stretch"):
                st.session_state["approval_response"] = request_json(
                    "POST", f"{GATEWAY_BASE}/approval/reject", json=payload
                )
                if _approval_pending and _active_flow_id:
                    resume_payload = {**payload, "decision": "reject"}
                    resume_response = request_json(
                        "POST",
                        f"{GATEWAY_BASE}/sample/{_active_flow_id}/workflow/continue",
                        json=resume_payload,
                    )
                    if apply_workflow_payload(st.session_state, _active_flow_id, resume_response):
                        _fetch_closed_incidents_cached.clear()
                        st.warning("Approval rejected and workflow closed without remediation.")
                        st.rerun()
            if col_modify.button("⟳ Modify", width="stretch"):
                payload["modified_action"] = comment
                st.session_state["approval_response"] = request_json(
                    "POST", f"{GATEWAY_BASE}/approval/modify", json=payload
                )
                if _approval_pending and _active_flow_id:
                    resume_payload = {**payload, "decision": "modify", "modified_action": comment}
                    resume_response = request_json(
                        "POST",
                        f"{GATEWAY_BASE}/sample/{_active_flow_id}/workflow/continue",
                        json=resume_payload,
                    )
                    if apply_workflow_payload(st.session_state, _active_flow_id, resume_response):
                        _fetch_closed_incidents_cached.clear()
                        st.success("Modified approval recorded and workflow completed.")
                        st.rerun()

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
                                    &nbsp;·&nbsp; Gateway: {html.escape(str(approval_gateway.get('safety', {}).get('decision', 'N/A')).upper())}
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

    trace_tab1, trace_tab2 = st.tabs(["Raw Trace", "Gateway & Safety"])

    with trace_tab1:
        if workflow.get("events"):
            render_event_trace(workflow.get("events", []))
        else:
            st.info("Run a flow to view the raw trace.")

    with trace_tab2:
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

        summary = st.session_state.get("gateway_summary") or _fetch_observability_summary_cached()
        recent = st.session_state.get("gateway_recent") or _fetch_observability_recent_cached()
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
    st.markdown("### Closed Incidents")
    col_closed_refresh, col_closed_spacer = st.columns([1, 3])
    with col_closed_refresh:
        if st.button("Refresh Closed Incidents", key="closed_incidents_refresh", width="stretch"):
            _fetch_closed_incidents_cached.clear()
            st.rerun()

    closed_rows = _fetch_closed_incidents_cached(limit=120)
    if closed_rows:
        st.metric("Closed Incidents", len(closed_rows))
        st.dataframe(
            [
                {
                    "Closed At": row.get("closed_at", ""),
                    "Incident": row.get("incident_id", ""),
                    "Title": row.get("title", ""),
                    "Service": row.get("service", ""),
                    "Severity": row.get("severity", ""),
                    "Risk": row.get("risk", ""),
                    "Action": row.get("action_type", ""),
                    "Status": row.get("action_status", ""),
                    "Health Restored": "YES" if bool(row.get("health_restored")) else "NO",
                    "Alerts Cleared": "YES" if bool(row.get("alerts_cleared")) else "NO",
                    "Trace": row.get("trace_id", ""),
                }
                for row in closed_rows
            ],
            hide_index=True,
            width="stretch",
        )

    st.markdown("### Current Closure Report")
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

