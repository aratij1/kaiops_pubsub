from __future__ import annotations

import html
import os
import re
import time
from datetime import datetime, timedelta, timezone
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import httpx
import streamlit as st
from agent_center import render_agent_command_center
import backend_api
from components import metric_row, render_trace_output_with_kv, status_badge, table_from_dict
from home_views import (
    render_agent_flow_view,
    render_alerts_quick_docs_view,
    render_closed_incidents_view,
    render_finops_view,
    render_gateway_safety_view,
    render_message_bus_view,
)
from session_controller import apply_guidance_selection, apply_workflow_payload, ensure_ui_defaults
from workflow_actions import fetch_guidance_matches, run_selected_flow

try:
    from common.topics import ALL_TOPICS
except Exception:
    ALL_TOPICS = [
        "raw-alerts",
        "enriched-alerts",
        "orchestration-events",
        "context-events",
        "resolution-events",
        "approval-events",
        "remediation-events",
        "closure-events",
    ]

GATEWAY_BASE = backend_api.GATEWAY_BASE
MONITORING_ADAPTER_BASE = backend_api.MONITORING_ADAPTER_BASE
UI_REQUEST_TIMEOUT_SECONDS = backend_api.UI_REQUEST_TIMEOUT_SECONDS
_WARMUP_EXECUTOR = ThreadPoolExecutor(max_workers=3)
ALERT_STREAM_LATEST_LIMIT = 50


def apply_datamatics_stylesheet() -> None:
    stylesheet_path = os.getenv("DATAMATICS_STYLESHEET_PATH", "").strip()
    if stylesheet_path:
        candidate = Path(stylesheet_path)
    else:
        candidate = Path(__file__).with_name("datamatics-standard.css")

    if not candidate.exists():
        return

    try:
        css_text = candidate.read_text(encoding="utf-8")
    except OSError:
        return

    if not css_text.strip():
        return

    st.markdown(f"<style>{css_text}</style>", unsafe_allow_html=True)


def apply_datamatics_base_stylesheet() -> None:
    candidate = Path(__file__).with_name("datamatics-base.css")
    if not candidate.exists():
        return

    try:
        css_text = candidate.read_text(encoding="utf-8")
    except OSError:
        return

    if not css_text.strip():
        return

    st.markdown(f"<style>{css_text}</style>", unsafe_allow_html=True)


def apply_datamatics_theme_stylesheet(theme_mode: str) -> None:
    mode = "light" if str(theme_mode).strip().lower() == "light" else "dark"
    candidate = Path(__file__).with_name(f"datamatics-{mode}.css")
    if not candidate.exists():
        return

    try:
        css_text = candidate.read_text(encoding="utf-8")
    except OSError:
        return

    if not css_text.strip():
        return

    st.markdown(f"<style>{css_text}</style>", unsafe_allow_html=True)


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


@st.cache_data(ttl=300, show_spinner="Loading alert catalog...")
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


def refresh_alert_snapshots(*, force: bool = False) -> None:
    now = time.time()
    last_refresh = float(st.session_state.get("alerts_snapshot_refreshed_at", 0.0) or 0.0)
    if not force and now - last_refresh < 6:
        return

    if force:
        _fetch_recent_alerts_cached.clear()
        _fetch_all_alerts_cached.clear()

    st.session_state["recent_alerts_snapshot"] = _fetch_recent_alerts_cached(limit=50)
    st.session_state["all_alerts_snapshot"] = _fetch_all_alerts_cached(limit=500)
    st.session_state["alerts_snapshot_refreshed_at"] = now


def fetch_ingestion_status() -> dict[str, Any]:
    response = request_json_with_fallback(
        "GET",
        [f"{GATEWAY_BASE}/ingestion/status", f"{MONITORING_ADAPTER_BASE}/ingestion/status"],
        suppress_last_error=True,
    )
    return response if isinstance(response, dict) else {}


def run_ingestion_manual() -> tuple[bool, dict[str, Any]]:
    response = request_json_with_fallback(
        "POST",
        [f"{GATEWAY_BASE}/ingestion/run", f"{MONITORING_ADAPTER_BASE}/ingestion/run"],
        suppress_last_error=True,
    )
    if response and isinstance(response, dict):
        return True, response
    return False, {}


def fetch_processed_result_for_alert(alert_id: str) -> dict[str, Any]:
    normalized = str(alert_id or "").strip()
    if not normalized:
        return {}
    return request_json_with_fallback(
        "GET",
        [
            f"{GATEWAY_BASE}/alerts/{normalized}/processed-result",
            f"{MONITORING_ADAPTER_BASE}/alerts/{normalized}/processed-result",
        ],
        suppress_last_error=True,
    )


def user_mgmt_auth_headers() -> dict[str, str]:
    access_token = str(st.session_state.get("user_mgmt_access_token", "")).strip()
    if not access_token:
        return {}
    return {"Authorization": f"Bearer {access_token}"}


def user_mgmt_request(method: str, path: str, show_error: bool = True, **kwargs) -> dict[str, Any]:
    headers = dict(kwargs.pop("headers", {}) or {})
    headers.update(user_mgmt_auth_headers())
    return request_json(method, f"{GATEWAY_BASE}{path}", show_error=show_error, headers=headers, **kwargs)


def user_mgmt_request_with_fallback(method: str, paths: list[str], *, suppress_last_error: bool = False, **kwargs) -> dict[str, Any]:
    last_path = paths[-1] if paths else ""
    for path in paths[:-1]:
        response = user_mgmt_request(method, path, show_error=False, **kwargs)
        if response:
            return response
    if last_path:
        return user_mgmt_request(method, last_path, show_error=not suppress_last_error, **kwargs)
    return {}


def user_mgmt_clear_session() -> None:
    for key in (
        "user_mgmt_access_token",
        "user_mgmt_refresh_token",
        "user_mgmt_user",
        "user_mgmt_roles",
        "user_mgmt_users",
        "user_mgmt_audit_logs",
    ):
        st.session_state.pop(key, None)


def user_mgmt_refresh_caches() -> None:
    if not st.session_state.get("user_mgmt_access_token"):
        return
    st.session_state["user_mgmt_me"] = user_mgmt_request("GET", "/auth/me", show_error=False)
    st.session_state["user_mgmt_roles"] = user_mgmt_request("GET", "/roles", show_error=False)
    st.session_state["user_mgmt_users"] = user_mgmt_request("GET", "/users?page=1&page_size=50", show_error=False)
    st.session_state["user_mgmt_audit_logs"] = user_mgmt_request("GET", "/audit-logs?page=1&page_size=50", show_error=False)


# Route all backend/data-access helpers through the dedicated backend module to keep app.py UI-centric.
request_json = backend_api.request_json
request_json_with_fallback = backend_api.request_json_with_fallback
test_connectivity = backend_api.test_connectivity
data_from_gateway = backend_api.data_from_gateway
_fetch_flows_cached = backend_api._fetch_flows_cached
_fetch_recent_alerts_cached = backend_api._fetch_recent_alerts_cached
_fetch_all_alerts_cached = backend_api._fetch_all_alerts_cached
refresh_alert_snapshots = backend_api.refresh_alert_snapshots
fetch_ingestion_status = backend_api.fetch_ingestion_status
run_ingestion_manual = backend_api.run_ingestion_manual
fetch_processed_result_for_alert = backend_api.fetch_processed_result_for_alert
user_mgmt_auth_headers = backend_api.user_mgmt_auth_headers
user_mgmt_request = backend_api.user_mgmt_request
user_mgmt_request_with_fallback = backend_api.user_mgmt_request_with_fallback
user_mgmt_clear_session = backend_api.user_mgmt_clear_session
user_mgmt_refresh_caches = backend_api.user_mgmt_refresh_caches
_fetch_observability_summary_cached = backend_api._fetch_observability_summary_cached
_fetch_observability_recent_cached = backend_api._fetch_observability_recent_cached
_fetch_closed_incidents_cached = backend_api._fetch_closed_incidents_cached
_fetch_incident_metadata_cached = backend_api._fetch_incident_metadata_cached


def render_admin_access_panel(*, sidebar: bool = False) -> None:
    user_mgmt_me = st.session_state.get("user_mgmt_me", {})
    if isinstance(user_mgmt_me, dict):
        account = user_mgmt_me.get("user", user_mgmt_me)
    else:
        account = {}
    if not isinstance(account, dict):
        account = {}

    account_name = str(account.get("username") or st.session_state.get("user_mgmt_user", {}).get("username") or "").strip()
    account_role = str(account.get("role_name") or st.session_state.get("user_mgmt_user", {}).get("role_name") or "").strip()
    is_admin_account = account_role.lower() == "administrator"

    if st.session_state.get("user_mgmt_access_token"):
        if account_name:
            st.caption(f"Signed in as {account_name} ({account_role or 'Unknown'})")
        if not is_admin_account:
            st.warning("Project Onboarding and User Management are visible only to Administrator accounts.")
        action_cols = st.columns(2)
        with action_cols[0]:
            if st.button("Refresh Admin Session", key=f"admin_refresh_{'sidebar' if sidebar else 'panel'}", width="stretch"):
                user_mgmt_refresh_caches()
                st.rerun()
        with action_cols[1]:
            if st.button("Logout", key=f"admin_logout_{'sidebar' if sidebar else 'panel'}", width="stretch"):
                user_mgmt_request("POST", "/auth/logout", show_error=False)
                user_mgmt_clear_session()
                st.rerun()
        return

    st.caption("Administrator sign-in reveals Project Onboarding and User Management.")
    st.caption("Seeded local credentials: admin / Admin@123456")
    with st.form(f"user_mgmt_login_form_{'sidebar' if sidebar else 'panel'}"):
        login_user = st.text_input("Username", value="admin", key=f"admin_user_{'sidebar' if sidebar else 'panel'}")
        login_password = st.text_input("Password", type="password", value="", key=f"admin_password_{'sidebar' if sidebar else 'panel'}")
        login_device = st.text_input("Device", value="Streamlit UI", key=f"admin_device_{'sidebar' if sidebar else 'panel'}")
        submitted = st.form_submit_button("Sign In", type="primary", use_container_width=True)
    if submitted:
        login_payload = {"username": login_user.strip(), "password": login_password, "device": login_device.strip()}
        login_response = user_mgmt_request("POST", "/auth/login", show_error=False, json=login_payload)
        if login_response and login_response.get("access_token"):
            st.session_state["user_mgmt_access_token"] = str(login_response.get("access_token", ""))
            st.session_state["user_mgmt_refresh_token"] = str(login_response.get("refresh_token", ""))
            st.session_state["user_mgmt_user"] = login_response.get("user", {})
            user_mgmt_refresh_caches()
            st.success("Signed in successfully.")
            st.rerun()
        else:
            st.error("Login failed. Check the seeded credentials and API Gateway availability.")


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

        shared_tokens = [
            token
            for token in ("mysql", "replica", "lag", "latency", "timeout", "unavailable")
            if token in blob and token in flow_blob
        ]
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
        with httpx.Client(timeout=1.0) as client:
            r = client.get(f"{GATEWAY_BASE}/healthz")
            checks["gateway"] = r.status_code < 400
    except Exception:
        pass
    try:
        with httpx.Client(timeout=1.0) as client:
            r = client.get(f"{MONITORING_ADAPTER_BASE}/healthz")
            checks["monitoring_adapter"] = r.status_code < 400
    except Exception:
        pass
    # Avoid an extra startup network call; use gateway availability as RAG readiness hint.
    checks["rag"] = checks["gateway"]
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
    return get_alert_stream_entries_with_limit(all_alerts=all_alerts, max_entries=ALERT_STREAM_LATEST_LIMIT)


def get_alert_stream_entries_with_limit(
    all_alerts: list[dict[str, Any]] | None = None,
    *,
    max_entries: int = ALERT_STREAM_LATEST_LIMIT,
) -> list[dict[str, Any]]:
    flow_entries = _fetch_flows_cached()
    safe_max_entries = max(1, int(max_entries))
    live_entries = _build_alert_stream_entries_from_all_alerts(
        all_alerts or _fetch_all_alerts_cached(limit=500),
        flow_entries=flow_entries,
        limit=safe_max_entries,
    )
    combined = live_entries[:safe_max_entries]

    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in combined:
        key = str(item.get("id") or item.get("alert_id") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _start_background_warmup_jobs() -> None:
    if st.session_state.get("warmup_jobs"):
        return

    st.session_state["warmup_jobs"] = {
        "recent_alerts": _WARMUP_EXECUTOR.submit(_fetch_recent_alerts_cached, 50),
        "all_alerts": _WARMUP_EXECUTOR.submit(_fetch_all_alerts_cached, 500),
        "flows": _WARMUP_EXECUTOR.submit(_fetch_flows_cached),
    }


def _collect_background_warmup_results() -> bool:
    jobs = st.session_state.get("warmup_jobs")
    if not isinstance(jobs, dict) or not jobs:
        return False

    changed = False
    done_keys: list[str] = []

    for key, future in jobs.items():
        if not isinstance(future, Future) or not future.done():
            continue
        done_keys.append(key)
        try:
            result = future.result()
        except Exception:
            result = []

        if key == "recent_alerts":
            st.session_state["recent_alerts_snapshot"] = result if isinstance(result, list) else []
            changed = True
        elif key == "all_alerts":
            st.session_state["all_alerts_snapshot"] = result if isinstance(result, list) else []
            changed = True
        elif key == "flows":
            flows = result if isinstance(result, list) else []
            st.session_state["flows"] = flows
            st.session_state["flow_catalog_preview"] = {
                "data": {"entries": flows, "count": len(flows), "path": "rag/flows.json"}
            }
            changed = True

    for key in done_keys:
        jobs.pop(key, None)

    if not jobs:
        st.session_state.pop("warmup_jobs", None)
        st.session_state["warmup_completed_once"] = True

    return changed


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
        title = html.escape(str(scenario.get("title", "KaiMS Incident Report")))
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
                title = html.escape(str(scenario.get("title", "KaiMS Homepage Export")))
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
    <title>KaiMS Homepage Export</title>
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
    <h1>KaiMS Autonomous Operations</h1>
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


def _parse_alert_timestamp(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    candidate = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


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


def render_alert_stream(
    entries: list[dict[str, Any]],
    status_filter: str = "All",
    display_limit: int = ALERT_STREAM_LATEST_LIMIT,
) -> dict[str, Any] | None:
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

    normalized_filter = str(status_filter or "All").strip().upper()
    if normalized_filter == "FAILED":
        filtered_entries = [entry for entry in enriched_entries if str(entry.get("runtime_state") or "").upper() == "FAILED"]
    elif normalized_filter == "RUNNING":
        filtered_entries = [entry for entry in enriched_entries if str(entry.get("runtime_state") or "").upper() == "RUNNING"]
    else:
        filtered_entries = enriched_entries

    if not filtered_entries:
        st.caption("No alerts match the selected filters.")
        return None

    available_severities = sorted(
        {
            str(entry["item"].get("severity") or "unknown").upper()
            for entry in filtered_entries
        }
    )
    available_sources = sorted({str(entry.get("source_label") or "unknown") for entry in filtered_entries})

    filter_col_left, filter_col_mid, filter_col_right = st.columns([3, 2, 2])
    with filter_col_left:
        search_query = st.text_input(
            "Search",
            value="",
            placeholder="Alert ID, alert name, or service",
            key="alert_stream_search_query",
            label_visibility="collapsed",
        )
    with filter_col_mid:
        selected_severities = st.multiselect(
            "Severity",
            options=available_severities,
            default=available_severities,
            key="alert_stream_severity_filter",
        )
    with filter_col_right:
        selected_sources = st.multiselect(
            "Source",
            options=available_sources,
            default=available_sources,
            key="alert_stream_source_filter",
        )

    normalized_query = str(search_query or "").strip().lower()
    selected_severity_set = {str(value).upper() for value in selected_severities}
    selected_source_set = {str(value) for value in selected_sources}
    scoped_entries: list[dict[str, Any]] = []
    for entry in filtered_entries:
        item = entry["item"]
        alert_id = str(item.get("alert_id") or item.get("id") or "")
        alert_name = str(item.get("alert_name") or item.get("title") or "")
        service = str(item.get("service") or "")
        severity = str(item.get("severity") or "unknown").upper()
        source_label = str(entry.get("source_label") or "unknown")
        searchable_blob = f"{alert_id} {alert_name} {service}".lower()

        if selected_severity_set and severity not in selected_severity_set:
            continue
        if selected_source_set and source_label not in selected_source_set:
            continue
        if normalized_query and normalized_query not in searchable_blob:
            continue
        scoped_entries.append(entry)

    if not scoped_entries:
        st.caption("No alerts match the selected search and filters.")
        return None

    safe_display_limit = max(1, int(display_limit))
    display_entries = scoped_entries[:safe_display_limit]
    table_rows: list[dict[str, Any]] = []
    open_targets: list[dict[str, str]] = []

    for entry in display_entries:
        item = entry["item"]
        alert_id = str(item.get("alert_id") or item.get("id") or "N/A")
        alert_name = str(item.get("alert_name") or item.get("title") or "Alert")
        service = str(item.get("service") or "unknown")
        source_label = str(entry["source_label"])
        severity = str(item.get("severity") or "unknown").upper()
        recommended_action = str(item.get("recommended_action") or "").strip() or "Investigate"
        runtime_state = str(entry["runtime_state"])
        flow_id = str(item.get("id") or "").strip()
        mapped_flow_id = str(item.get("flow_id") or "").strip()
        executable_flow_id = mapped_flow_id or (flow_id if not bool(item.get("is_live_alert", False)) else "")
        _, badge_label = _alert_stream_status(severity, recommended_action, alert_name)
        created_at = str(item.get("created_at") or item.get("updated_at") or "").strip()
        action_preview = recommended_action if len(recommended_action) <= 80 else f"{recommended_action[:77]}..."

        table_rows.append(
            {
                "Alert ID": alert_id,
                "Alert": alert_name,
                "Service": service,
                "Severity": severity,
                "Runtime": runtime_state,
                "Status": badge_label,
                "Source": source_label,
                "Recommended Action": action_preview,
                "Updated": created_at or "n/a",
            }
        )
        open_targets.append(
            {
                "alert_id": alert_id,
                "alert_name": alert_name,
                "service": service,
                "severity": severity,
                "source": source_label,
                "runtime_state": runtime_state,
                "mapped_flow_id": executable_flow_id,
                "description": str(item.get("description") or "").strip(),
                "recommended_action": recommended_action,
            }
        )

    st.dataframe(table_rows, hide_index=True, width="stretch")
    st.caption("Select an alert below and open details in Alert Stream workspace.")

    if not open_targets:
        return None

    open_labels = [target["alert_id"] for target in open_targets]
    open_target_by_id = {target["alert_id"]: target for target in open_targets}
    action_left, action_right = st.columns([4, 1])
    with action_left:
        selected_alert_id = st.selectbox(
            "Alert ID",
            options=open_labels,
            key="alert_stream_selected_row",
            format_func=lambda alert_id: (
                f"{alert_id} | {open_target_by_id[alert_id]['alert_name']} | "
                f"{open_target_by_id[alert_id]['service']} | {open_target_by_id[alert_id]['severity']}"
            ),
        )
    with action_right:
        open_clicked = st.button("Open Alert", key="open_selected_alert", use_container_width=True)

    selected_preview = open_target_by_id.get(selected_alert_id)
    if selected_preview:
        st.caption(
            f"Selected: {selected_preview['alert_name']} | Service {selected_preview['service']} | "
            f"Severity {selected_preview['severity']} | Action {selected_preview['recommended_action']}"
        )

    if open_clicked:
        selected_target = open_target_by_id[selected_alert_id]
        st.session_state["alert_stream_selected"] = {
            **selected_target,
            "selected_at": datetime.now(timezone.utc).isoformat(),
        }
        return {
            "kind": "alert_stream",
            "alert_id": selected_target["alert_id"],
            "alert_name": selected_target["alert_name"],
            "service": selected_target["service"],
            "severity": selected_target["severity"],
        }

    st.caption(f"Showing {len(display_entries)} of {len(scoped_entries)} alerts after filters.")

    return None


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
    for event in sorted(events, key=lambda item: item.get("sequence", 0)):
        with st.expander(f"{event.get('sequence')}. {event.get('agent')}"):
            st.write(event.get("action"))
            status_badge("Input", event.get("input", "N/A"))
            event_output = event.get("output", "N/A")
            status_badge("Output", event_output)
            if isinstance(event_output, dict):
                st.markdown("**Output (key-value)**")
                table_from_dict(event_output, "Field", "Value")
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
                        render_trace_output_with_kv(call.get("response", ""))
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
                render_trace_output_with_kv(call.get("response", ""))
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


def _slugify_alert_id(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return normalized or "new-alert"


def render_alert_onboarding_pack_section() -> None:
    st.markdown("## Alert Onboarding Pack")
    st.caption(
        "Generate scenarios and RAG knowledge documents for a new alert in one step: "
        "runbook, SOP, incident, change, dependency, deployment, and onboarding profile."
    )

    repo_root = Path(__file__).resolve().parents[2]
    rag_root = repo_root / "rag"
    scenarios_path = rag_root / "scenarios.txt"
    generated_paths: list[str] = []
    connectivity_defaults = {
        "prometheus_url": "http://localhost:9090/-/ready",
        "new_relic_url": "https://api.newrelic.com/v2/applications.json",
        "datadog_url": "https://api.datadoghq.com/api/v1/validate",
    }

    with st.form("alert_onboarding_pack_form"):
        st.markdown("### Alert Definition")
        col_left, col_right = st.columns(2)
        with col_left:
            alert_id_raw = st.text_input("Alert ID", value="orders-replica-lag")
            title = st.text_input("Title", value="Orders database replica lag")
            source = st.text_input("Source", value="prometheus")
            service = st.text_input("Service", value="orders-db")
            severity = st.selectbox("Severity", options=["CRITICAL", "HIGH", "WARNING", "INFO"], index=0)
        with col_right:
            description = st.text_area("Description", value="Replica lag above threshold for 10 minutes", height=90)
            root_cause = st.text_input("Root Cause", value="Primary write saturation")
            impact = st.text_input("Impact", value="Stale reads on order queries")
            recommended_action = st.text_input("Recommended Action", value="Failover database")

        st.markdown("### Ownership and Environment")
        env_col_left, env_col_right = st.columns(2)
        with env_col_left:
            owner_team = st.text_input("Owner Team", value="platform-ops")
            environment = st.selectbox("Environment", options=["prod", "staging", "dev"], index=0)
        with env_col_right:
            region = st.text_input("Region", value="us-east-1")
            source_ref = st.text_input("Source Ref", value="INC-NEW")

        st.markdown("### Connectivity Defaults")
        save_connectivity_defaults = st.checkbox(
            "Also save provider connectivity defaults",
            value=True,
            help="Persists project and endpoint defaults to onboarding connectivity/state via API.",
        )
        project_name = st.text_input("Project Name", value="orders-platform")
        conn_col_left, conn_col_right, conn_col_third = st.columns(3)
        with conn_col_left:
            prometheus_url = st.text_input("Prometheus URL", value=connectivity_defaults["prometheus_url"])
        with conn_col_right:
            new_relic_url = st.text_input("New Relic URL", value=connectivity_defaults["new_relic_url"])
        with conn_col_third:
            datadog_url = st.text_input("Datadog URL", value=connectivity_defaults["datadog_url"])

        secret_col_left, secret_col_right = st.columns(2)
        with secret_col_left:
            new_relic_api_key = st.text_input("New Relic API Key (optional)", value="", type="password")
        with secret_col_right:
            datadog_api_key = st.text_input("Datadog API Key (optional)", value="", type="password")

        st.markdown("#### Connectivity Validation")
        test_col_left, test_col_mid, test_col_right = st.columns(3)
        with test_col_left:
            test_prometheus_clicked = st.form_submit_button("Test Prometheus", use_container_width=True)
        with test_col_mid:
            test_new_relic_clicked = st.form_submit_button("Test New Relic", use_container_width=True)
        with test_col_right:
            test_datadog_clicked = st.form_submit_button("Test Datadog", use_container_width=True)

        auto_reload_rag = st.checkbox("Reload RAG index after generation", value=True)
        submitted = st.form_submit_button("Generate Onboarding Pack", type="primary", use_container_width=True)

    if test_prometheus_clicked:
        ok, message = test_connectivity(str(prometheus_url or "").strip())
        if ok:
            st.success(f"Prometheus: {message}")
        else:
            st.error(f"Prometheus: {message}")
        return

    if test_new_relic_clicked:
        headers: dict[str, str] = {}
        if str(new_relic_api_key or "").strip():
            headers["Api-Key"] = str(new_relic_api_key).strip()
        ok, message = test_connectivity(str(new_relic_url or "").strip(), headers=headers)
        if ok:
            st.success(f"New Relic: {message}")
        else:
            st.error(f"New Relic: {message}")
        return

    if test_datadog_clicked:
        headers = {}
        if str(datadog_api_key or "").strip():
            headers["DD-API-KEY"] = str(datadog_api_key).strip()
        ok, message = test_connectivity(str(datadog_url or "").strip(), headers=headers)
        if ok:
            st.success(f"Datadog: {message}")
        else:
            st.error(f"Datadog: {message}")
        return

    if not submitted:
        return

    flow_id = _slugify_alert_id(alert_id_raw)
    if not title.strip() or not service.strip() or not description.strip():
        st.error("Title, Service, and Description are required.")
        return

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    alert_name = title.strip()
    normalized_source_ref = source_ref.strip() or flow_id.upper()

    scenarios_path.parent.mkdir(parents=True, exist_ok=True)
    if not scenarios_path.exists():
        scenarios_path.write_text(
            "# Pipe-delimited scenarios for Monitoring Adapter\n"
            "# id|title|source|service|severity|description|root_cause|impact|recommended_action\n",
            encoding="utf-8",
        )

    scenario_line = (
        f"{flow_id}|{alert_name}|{source.strip()}|{service.strip()}|{severity}|"
        f"{description.strip()}|{root_cause.strip()}|{impact.strip()}|{recommended_action.strip()}"
    )
    existing_lines = scenarios_path.read_text(encoding="utf-8").splitlines()
    if not any(line.split("|", 1)[0].strip().lower() == flow_id for line in existing_lines if line and not line.startswith("#")):
        with scenarios_path.open("a", encoding="utf-8") as handle:
            if existing_lines and existing_lines[-1].strip():
                handle.write("\n")
            handle.write(scenario_line)
        generated_paths.append("rag/scenarios.txt")

    file_payloads: dict[Path, str] = {
        rag_root / "runbooks" / f"{flow_id}-runbook.md": (
            f"kind: runbook\n"
            f"title: {alert_name} response runbook\n"
            f"services: {service.strip()}\n"
            f"owner_team: {owner_team.strip()}\n"
            f"last_reviewed: {now_iso}\n"
            f"source_system: internal\n"
            f"source_ref: {normalized_source_ref}\n\n"
            f"# {alert_name} response runbook\n\n"
            f"## Triage\n"
            f"1. Confirm alert severity {severity} and impacted service {service.strip()}.\n"
            f"2. Check metrics, logs, and dependencies for anomaly start time.\n"
            f"3. Validate whether recent deployment/change windows overlap incident start.\n\n"
            f"## Remediation\n"
            f"1. Execute: {recommended_action.strip()}.\n"
            f"2. Validate service recovery and alert stabilization.\n"
            f"3. Record root cause and prevention notes.\n"
        ),
        rag_root / "sops" / f"{flow_id}-sop.md": (
            f"kind: sop\n"
            f"title: {alert_name} operational SOP\n"
            f"services: {service.strip()}\n"
            f"owner_team: {owner_team.strip()}\n"
            f"last_reviewed: {now_iso}\n"
            f"source_system: internal\n"
            f"source_ref: {normalized_source_ref}\n\n"
            f"# {alert_name} SOP\n\n"
            f"## Objective\n"
            f"Standardize operator response for {alert_name}.\n\n"
            f"## Trigger Conditions\n"
            f"- Alert {flow_id} is active in {environment}.\n"
            f"- Severity is {severity}.\n\n"
            f"## Procedure\n"
            f"1. Verify incident context and impacted dependencies.\n"
            f"2. Apply approved action: {recommended_action.strip()}.\n"
            f"3. Confirm closure criteria and document evidence.\n"
        ),
        rag_root / "incidents" / f"{flow_id}-incident.md": (
            f"alert_id: {flow_id.upper()}\n"
            f"alert_name: {alert_name}\n"
            f"service: {service.strip()}\n"
            f"severity: {severity.lower()}\n"
            f"alert_type: incident\n"
            f"source_system: internal\n"
            f"source_ref: {normalized_source_ref}\n"
            f"resolved_by: {owner_team.strip()}\n"
            f"closed_at: {now_iso}\n\n"
            f"# {alert_name}\n\n"
            f"## Summary\n"
            f"{description.strip()}\n\n"
            f"## Root Cause\n"
            f"{root_cause.strip()}\n\n"
            f"## Impact\n"
            f"{impact.strip()}\n\n"
            f"## Remediation\n"
            f"{recommended_action.strip()}\n"
        ),
        rag_root / "changes" / f"{flow_id}-change.md": (
            f"kind: change\n"
            f"title: {flow_id.upper()} change context\n"
            f"services: {service.strip()}\n"
            f"deployment: incident-driven\n"
            f"change_id: CHG-{flow_id.upper()}\n"
            f"source_system: internal\n"
            f"source_ref: {normalized_source_ref}\n\n"
            f"# {alert_name} change context\n\n"
            f"## Summary\n"
            f"- Service: {service.strip()}\n"
            f"- Severity: {severity}\n"
            f"- Alert: {flow_id}\n\n"
            f"## Operational Guidance\n"
            f"1. Check release and change windows around incident start.\n"
            f"2. Validate rollback possibility before irreversible remediation.\n"
        ),
        rag_root / "dependencies" / f"{flow_id}-dependency.md": (
            f"kind: dependency\n"
            f"title: {flow_id.upper()} dependency context\n"
            f"services: {service.strip()}\n"
            f"dependencies: cmdb, observability, message-bus\n"
            f"source_system: internal\n"
            f"source_ref: {normalized_source_ref}\n"
            f"last_reviewed: {now_iso}\n\n"
            f"# {alert_name} dependency context\n\n"
            f"## Expected Dependency Checks\n"
            f"- Upstream availability\n"
            f"- Downstream consumer health\n"
            f"- Network and broker path status\n"
        ),
        rag_root / "deployments" / f"{flow_id}-deployment.md": (
            f"kind: deployment\n"
            f"title: {flow_id.upper()} deployment context\n"
            f"services: {service.strip()}\n"
            f"deployment: incident-driven\n"
            f"source_system: internal\n"
            f"source_ref: {normalized_source_ref}\n"
            f"last_reviewed: {now_iso}\n\n"
            f"# {alert_name} deployment context\n\n"
            f"## Checks\n"
            f"1. Verify recent deployment version and rollout window.\n"
            f"2. Correlate deployment timeline with alert start.\n"
            f"3. Validate rollback criteria before executing changes.\n"
        ),
        rag_root / "onboarding" / f"{flow_id}-onboarding.md": (
            f"kind: onboarding\n"
            f"title: {flow_id.upper()} onboarding readiness\n"
            f"services: {service.strip()}\n"
            f"owner_team: {owner_team.strip()}\n"
            f"last_reviewed: {now_iso}\n"
            f"source_system: internal\n"
            f"source_ref: {normalized_source_ref}\n\n"
            f"# {alert_name} onboarding readiness\n\n"
            f"## Required Readiness\n"
            f"- Monitoring provider connected and tested\n"
            f"- Environment: {environment}\n"
            f"- Region: {region.strip()}\n"
            f"- Escalation owner: {owner_team.strip()}\n"
        ),
    }

    for file_path, file_content in file_payloads.items():
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(file_content.strip() + "\n", encoding="utf-8")
        generated_paths.append(str(file_path.relative_to(repo_root)).replace("\\", "/"))

    if save_connectivity_defaults:
        onboarding_payload = {
            "project": {
                "name": str(project_name or "").strip() or service.strip(),
                "owner_team": owner_team.strip(),
                "environment": environment,
                "region": region.strip(),
            },
            "prometheus_url": str(prometheus_url or "").strip(),
            "new_relic_url": str(new_relic_url or "").strip(),
            "datadog_url": str(datadog_url or "").strip(),
            "provider_statuses": {},
            "active_provider": "prometheus",
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        connectivity_response = request_json_with_fallback(
            "POST",
            [f"{GATEWAY_BASE}/onboarding/connectivity", f"{MONITORING_ADAPTER_BASE}/onboarding/connectivity"],
            suppress_last_error=True,
            json=onboarding_payload,
        )
        connectivity_data = data_from_gateway(connectivity_response) if connectivity_response else {}
        if isinstance(connectivity_data, dict) and isinstance(connectivity_data.get("connectivity"), dict):
            generated_paths.append("rag/onboarding/connectivity.json")
            st.info("Connectivity defaults saved to onboarding state.")
        else:
            st.warning("Document pack created, but connectivity defaults were not persisted.")

    if auto_reload_rag:
        rag_reload = request_json("POST", f"{GATEWAY_BASE}/rag/reload", show_error=False)
        if rag_reload:
            st.success("Onboarding pack generated and RAG index reloaded.")
        else:
            st.warning("Onboarding pack generated, but RAG reload failed. You can retry from RAG controls.")
    else:
        st.success("Onboarding pack generated.")

    st.markdown("### Generated Files")
    st.dataframe([{"Path": path} for path in generated_paths], hide_index=True, use_container_width=True)


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
    provider_key_map = {
        "Prometheus": "prometheus_url",
        "New Relic": "new_relic_url",
        "Datadog": "datadog_url",
    }

    def is_valid_endpoint_url(value: str) -> bool:
        candidate = str(value or "").strip()
        if not candidate:
            return False
        parsed = urlparse(candidate)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    def hydrate_status_from_rows(rows: list[dict[str, Any]]) -> None:
        status_map: dict[str, dict[str, Any]] = {}
        for row in rows:
            provider = str(row.get("provider_name", "")).strip().lower()
            if provider not in {"prometheus", "new_relic", "datadog"}:
                continue
            raw_status = str(row.get("test_status", "")).strip().lower()
            message = str(row.get("test_message", "")).strip() or "Not tested"
            if raw_status in {"connected", "failed"}:
                status_map[provider] = {"ok": raw_status == "connected", "message": message}
        if status_map:
            current = st.session_state.get("onboarding_status", {})
            if not isinstance(current, dict):
                current = {}
            current.update(status_map)
            st.session_state["onboarding_status"] = current

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
                "user_assignments": persisted.get("user_assignments", {}) if isinstance(persisted.get("user_assignments"), dict) else {},
                "updated_at": persisted.get("updated_at"),
            }
        state_response = request_json_with_fallback(
            "GET",
            [f"{GATEWAY_BASE}/onboarding/state", f"{MONITORING_ADAPTER_BASE}/onboarding/state"],
            suppress_last_error=True,
        )
        state_rows = data_from_gateway(state_response).get("rows", []) if state_response else []
        if isinstance(state_rows, list):
            filtered_rows = [row for row in state_rows if isinstance(row, dict)]
            st.session_state["onboarding_rows"] = filtered_rows
            hydrate_status_from_rows(filtered_rows)
        st.session_state["onboarding_loaded"] = True

    def refresh_onboarding_rows() -> None:
        state_response = request_json_with_fallback(
            "GET",
            [f"{GATEWAY_BASE}/onboarding/state", f"{MONITORING_ADAPTER_BASE}/onboarding/state"],
            suppress_last_error=True,
        )
        state_rows = data_from_gateway(state_response).get("rows", []) if state_response else []
        if isinstance(state_rows, list):
            filtered_rows = [row for row in state_rows if isinstance(row, dict)]
            st.session_state["onboarding_rows"] = filtered_rows
            hydrate_status_from_rows(filtered_rows)

    with st.container(border=True):
        project_state = st.session_state.get("onboarding_project", {})
        conn_state = st.session_state.get("onboarding_connectivity", {})
        status_state = st.session_state.get("onboarding_status", {})
        project_ready = bool(str(project_state.get("name", "")).strip() and str(project_state.get("owner_team", "")).strip())
        configured_endpoints = sum(
            1
            for endpoint_key in provider_key_map.values()
            if str(conn_state.get(endpoint_key, "")).strip()
        )
        connectivity_ready = configured_endpoints > 0
        tested_providers = sum(1 for provider in ("prometheus", "new_relic", "datadog") if provider in status_state)
        successful_tests = sum(
            1
            for provider in ("prometheus", "new_relic", "datadog")
            if bool((status_state.get(provider, {}) or {}).get("ok"))
        )
        rows_ready = bool(st.session_state.get("onboarding_rows", []))
        completed_steps = sum([project_ready, connectivity_ready, successful_tests > 0, rows_ready])

        st.markdown("### Guided Onboarding")
        st.progress(completed_steps / 4)
        stat_cols = st.columns(4)
        stat_cols[0].metric("Step 1", "Done" if project_ready else "Pending")
        stat_cols[1].metric("Step 2", f"{configured_endpoints}/3 configured")
        stat_cols[2].metric("Step 3", f"{successful_tests}/3 passing")
        stat_cols[3].metric("Step 4", "Done" if rows_ready else "Pending")

        step_labels = [
            "Step 1 - Project Setup",
            "Step 2 - Connectivity",
            "Step 3 - Validation Status",
            "Step 4 - Saved Rows",
        ]
        if "onboarding_step_index" not in st.session_state:
            st.session_state["onboarding_step_index"] = 0
        current_step_index = int(st.session_state.get("onboarding_step_index", 0) or 0)
        current_step_index = max(0, min(current_step_index, len(step_labels) - 1))
        st.session_state["onboarding_step_index"] = current_step_index
        can_advance_step = False
        if current_step_index == 0:
            can_advance_step = project_ready
        elif current_step_index == 1:
            can_advance_step = connectivity_ready
        elif current_step_index == 2:
            can_advance_step = successful_tests > 0
        else:
            can_advance_step = rows_ready

        nav_left, nav_mid, nav_right = st.columns([1, 2.6, 1])
        with nav_left:
            if st.button("<- Previous", key="onboarding_prev_step", use_container_width=True, disabled=current_step_index == 0):
                st.session_state["onboarding_step_index"] = max(0, current_step_index - 1)
                st.rerun()
        with nav_mid:
            selected_step_label = st.selectbox(
                "Onboarding Step",
                step_labels,
                index=current_step_index,
                key="onboarding_step_selector",
            )
            selected_index = step_labels.index(selected_step_label)
            if selected_index != current_step_index:
                st.session_state["onboarding_step_index"] = selected_index
                current_step_index = selected_index
                st.rerun()
        with nav_right:
            if st.button(
                "Next ->",
                key="onboarding_next_step",
                use_container_width=True,
                disabled=current_step_index == len(step_labels) - 1 or not can_advance_step,
            ):
                st.session_state["onboarding_step_index"] = min(len(step_labels) - 1, current_step_index + 1)
                st.rerun()

        st.caption(f"Current step: {step_labels[current_step_index]}")

        if current_step_index == 0:
            st.caption("Define the project metadata before testing providers.")
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
                    if not project_name_value:
                        st.error("Project name is required.")
                        return
                    if not owner_team_value:
                        st.error("Owner team is required.")
                        return
                    if not region_value:
                        st.error("Region is required.")
                        return
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
                        "user_assignments": st.session_state["onboarding_connectivity"].get("user_assignments", {}),
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
                        st.session_state["onboarding_connectivity"] = {
                            "prometheus_url": str(persisted.get("prometheus_url", "")).strip(),
                            "new_relic_url": str(persisted.get("new_relic_url", "")).strip(),
                            "datadog_url": str(persisted.get("datadog_url", "")).strip(),
                            "user_assignments": persisted.get("user_assignments", {}) if isinstance(persisted.get("user_assignments"), dict) else {},
                            "updated_at": persisted.get("updated_at"),
                        }
                        refresh_onboarding_rows()
                        st.success("Project details saved and persisted to MySQL.")
                        st.session_state["onboarding_step_index"] = 1
                        st.rerun()
                    else:
                        st.success("Project details saved.")
                        st.session_state["onboarding_step_index"] = 1
                        st.rerun()

        elif current_step_index == 1:
            st.caption("Configure and test each provider endpoint.")
            provider_options = ["Prometheus", "New Relic", "Datadog"]
            selected_provider = st.selectbox(
                "Connectivity provider",
                provider_options,
                key="onboarding_provider_selector",
            )
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

            action_left, action_right = st.columns(2)
            with action_left:
                test_clicked = st.button(f"Test {selected_provider}", key="test_selected_provider", use_container_width=True)
            with action_right:
                save_clicked = st.button("Save Connectivity Configuration", key="save_connectivity", use_container_width=True)

            if test_clicked:
                if not project_ready:
                    st.warning("Complete Step 1 project setup before testing provider connectivity.")
                    return
                connectivity_endpoint = str(connectivity_url or "").strip()
                if not is_valid_endpoint_url(connectivity_endpoint):
                    st.error("Enter a valid endpoint URL with http:// or https://.")
                    return
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
                    "user_assignments": st.session_state["onboarding_connectivity"].get("user_assignments", {}),
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
                if ok:
                    st.success(message)
                    st.session_state["onboarding_step_index"] = 2
                    st.rerun()
                else:
                    st.error(message)

            if save_clicked:
                if not project_ready:
                    st.warning("Complete Step 1 project setup before saving connectivity.")
                    return
                normalized_endpoint = str(connectivity_url or "").strip()
                if not is_valid_endpoint_url(normalized_endpoint):
                    st.error("Enter a valid endpoint URL with http:// or https://.")
                    return
                st.session_state["onboarding_connectivity"][selected_key] = normalized_endpoint
                payload = {
                    "project": st.session_state.get("onboarding_project", {}),
                    "prometheus_url": st.session_state["onboarding_connectivity"].get("prometheus_url", provider_defaults["Prometheus"]["url"]),
                    "new_relic_url": st.session_state["onboarding_connectivity"].get("new_relic_url", provider_defaults["New Relic"]["url"]),
                    "datadog_url": st.session_state["onboarding_connectivity"].get("datadog_url", provider_defaults["Datadog"]["url"]),
                    "user_assignments": st.session_state["onboarding_connectivity"].get("user_assignments", {}),
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
                    st.session_state["onboarding_connectivity"] = {
                        "prometheus_url": str(persisted.get("prometheus_url", "")).strip(),
                        "new_relic_url": str(persisted.get("new_relic_url", "")).strip(),
                        "datadog_url": str(persisted.get("datadog_url", "")).strip(),
                        "user_assignments": persisted.get("user_assignments", {}) if isinstance(persisted.get("user_assignments"), dict) else {},
                        "updated_at": persisted.get("updated_at"),
                    }
                    refresh_onboarding_rows()
                    st.success("Connectivity configuration persisted.")
                    st.session_state["onboarding_step_index"] = 2
                    st.rerun()

        elif current_step_index == 2:
            st.caption("Review latest provider test results.")
            if st.session_state.get("onboarding_status"):
                for provider in ("prometheus", "new_relic", "datadog"):
                    if provider in st.session_state["onboarding_status"]:
                        state = st.session_state["onboarding_status"][provider]
                        label = provider.replace("_", " ").title()
                        if state.get("ok"):
                            st.success(f"{label}: {state.get('message', 'Connected')}")
                        else:
                            st.error(f"{label}: {state.get('message', 'Not connected')}")
            else:
                st.info("Run at least one provider connectivity test in Step 2.")

        else:
            st.caption("Persisted onboarding rows from MySQL for audit and review.")
            if st.button("Refresh Saved Rows", key="refresh_onboarding_rows_btn", use_container_width=True):
                refresh_onboarding_rows()
                st.rerun()
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


def render_user_management_section() -> None:
    st.markdown("### User Management")
    st.caption("Admin workflow: create users, edit existing profiles, and assign projects.")

    user_mgmt_me = st.session_state.get("user_mgmt_me", {})
    user_mgmt_roles_payload = st.session_state.get("user_mgmt_roles", {})
    user_mgmt_users_payload = st.session_state.get("user_mgmt_users", {})
    user_mgmt_audit_payload = st.session_state.get("user_mgmt_audit_logs", {})

    if not st.session_state.get("user_mgmt_access_token"):
        st.info("Sign in with an Administrator account to open user management.")
        return

    account = user_mgmt_me.get("user", user_mgmt_me) if isinstance(user_mgmt_me, dict) else {}

    if str(account.get("role_name") or "").strip().lower() != "administrator":
        st.warning("Only Administrator accounts can manage users and project assignments.")
        return

    account_name = str(account.get("username") or st.session_state.get("user_mgmt_user", {}).get("username") or "administrator")
    account_role = str(account.get("role_name") or st.session_state.get("user_mgmt_user", {}).get("role_name") or "Unknown")
    top_left, top_right = st.columns([1.3, 1])
    with top_left:
        st.success(f"Signed in as {account_name} ({account_role})")
    with top_right:
        col_refresh, col_logout = st.columns(2)
        with col_refresh:
            if st.button("Refresh", width="stretch", key="user_mgmt_refresh_rail"):
                user_mgmt_refresh_caches()
                st.rerun()
        with col_logout:
            if st.button("Logout", width="stretch", key="user_mgmt_logout_rail"):
                user_mgmt_request("POST", "/auth/logout", show_error=False)
                user_mgmt_clear_session()
                st.rerun()

    roles_data = user_mgmt_roles_payload if isinstance(user_mgmt_roles_payload, list) else user_mgmt_roles_payload.get("rows", []) if isinstance(user_mgmt_roles_payload, dict) else []
    users_data = data_from_gateway(user_mgmt_users_payload).get("rows", []) if isinstance(user_mgmt_users_payload, dict) else []
    audit_data = data_from_gateway(user_mgmt_audit_payload).get("rows", []) if isinstance(user_mgmt_audit_payload, dict) else []

    onboarding_connectivity_response = request_json_with_fallback(
        "GET",
        [f"{GATEWAY_BASE}/onboarding/connectivity", f"{MONITORING_ADAPTER_BASE}/onboarding/connectivity"],
        suppress_last_error=True,
    )
    onboarding_connectivity = data_from_gateway(onboarding_connectivity_response).get("connectivity", {}) if onboarding_connectivity_response else {}

    onboarding_state_response = request_json_with_fallback(
        "GET",
        [f"{GATEWAY_BASE}/onboarding/state", f"{MONITORING_ADAPTER_BASE}/onboarding/state"],
        suppress_last_error=True,
    )
    onboarding_state_rows = data_from_gateway(onboarding_state_response).get("rows", []) if onboarding_state_response else []
    if not isinstance(onboarding_state_rows, list):
        onboarding_state_rows = []

    project_names = sorted(
        {
            str(row.get("project_name", "")).strip()
            for row in onboarding_state_rows
            if isinstance(row, dict) and str(row.get("project_name", "")).strip()
        }
    )

    raw_assignment_map = onboarding_connectivity.get("user_assignments", {}) if isinstance(onboarding_connectivity, dict) else {}
    assignment_map: dict[str, list[str]] = {}
    if isinstance(raw_assignment_map, dict):
        for key, value in raw_assignment_map.items():
            if isinstance(value, list):
                assignment_map[str(key)] = [str(item).strip() for item in value if str(item).strip()]

    metric_row(
        [
            ("Roles", len(roles_data)),
            ("Users", len(users_data)),
            ("Projects", len(project_names)),
            ("Assignments", sum(len(v) for v in assignment_map.values())),
        ]
    )

    tab_overview, tab_create, tab_edit, tab_assign, tab_audit = st.tabs(
        ["Overview", "Create User", "Edit User", "Assign Projects", "Audit Log"]
    )

    with tab_overview:
        st.markdown("#### Roles")
        if roles_data:
            st.dataframe(
                [
                    {
                        "ID": role.get("id"),
                        "Name": role.get("name"),
                        "Description": role.get("description"),
                        "System": "YES" if role.get("is_system_role") else "NO",
                    }
                    for role in roles_data
                    if isinstance(role, dict)
                ],
                hide_index=True,
                width="stretch",
            )
        else:
            st.caption("No roles returned from the API.")

        st.markdown("#### Users")
        if users_data:
            st.dataframe(
                [
                    {
                        "ID": row.get("id"),
                        "Username": row.get("username"),
                        "Email": row.get("email"),
                        "Role": row.get("role_name"),
                        "Status": row.get("status"),
                        "Active": "YES" if row.get("is_active") else "NO",
                        "Projects": ", ".join(assignment_map.get(str(row.get("username", "")), [])),
                    }
                    for row in users_data
                    if isinstance(row, dict)
                ],
                hide_index=True,
                width="stretch",
            )
        else:
            st.caption("No users returned from the API.")

    with tab_create:
        if not roles_data:
            st.caption("No roles loaded yet. Refresh after signing in.")
        else:
            with st.form("user_mgmt_create_form"):
                create_left, create_right = st.columns(2)
                with create_left:
                    new_username = st.text_input("Username", key="user_mgmt_new_username")
                    new_email = st.text_input("Email", key="user_mgmt_new_email")
                    new_first_name = st.text_input("First name", key="user_mgmt_new_first_name")
                    new_last_name = st.text_input("Last name", key="user_mgmt_new_last_name")
                with create_right:
                    role_labels = [f"{str(role.get('id'))} - {str(role.get('name'))}" for role in roles_data if isinstance(role, dict)]
                    selected_role_label = st.selectbox("Role", role_labels, key="user_mgmt_new_role")
                    new_password = st.text_input("Password", type="password", key="user_mgmt_new_password")
                    new_status = st.selectbox("Status", ["active", "inactive", "locked"], key="user_mgmt_new_status")
                    new_is_active = st.checkbox("Is active", value=True, key="user_mgmt_new_is_active")
                create_submitted = st.form_submit_button("Create User", type="primary", use_container_width=True)

            if create_submitted:
                try:
                    role_id = int(str(selected_role_label).split(" - ", 1)[0])
                except Exception:
                    role_id = 0
                create_payload = {
                    "username": new_username.strip(),
                    "email": new_email.strip(),
                    "password": new_password,
                    "first_name": new_first_name.strip(),
                    "last_name": new_last_name.strip(),
                    "role_id": role_id,
                    "status": new_status,
                    "is_active": bool(new_is_active),
                }
                create_response = user_mgmt_request("POST", "/users", show_error=False, json=create_payload)
                if create_response and create_response.get("username"):
                    st.success(f"Created user {create_response.get('username')}.")
                    user_mgmt_refresh_caches()
                    st.rerun()
                else:
                    st.error("Unable to create user. Check the fields and password policy.")

    with tab_edit:
        editable_users = [row for row in users_data if isinstance(row, dict)]
        if not editable_users:
            st.caption("No users available to edit.")
        else:
            selected_user_label = st.selectbox(
                "Select user",
                [f"{row.get('id')} - {row.get('username')}" for row in editable_users],
                key="user_mgmt_edit_user_selector",
            )
            selected_user_id = int(str(selected_user_label).split(" - ", 1)[0])
            selected_user = next((row for row in editable_users if int(row.get("id", -1)) == selected_user_id), {})
            role_labels = [f"{str(role.get('id'))} - {str(role.get('name'))}" for role in roles_data if isinstance(role, dict)]
            current_role_id = int(selected_user.get("role_id", 0) or 0)
            default_role_idx = 0
            for idx, label in enumerate(role_labels):
                try:
                    if int(str(label).split(" - ", 1)[0]) == current_role_id:
                        default_role_idx = idx
                        break
                except Exception:
                    continue

            with st.form("user_mgmt_edit_form"):
                edit_left, edit_right = st.columns(2)
                with edit_left:
                    edit_email = st.text_input("Email", value=str(selected_user.get("email", "")), key="user_mgmt_edit_email")
                    edit_first_name = st.text_input("First name", value=str(selected_user.get("first_name", "")), key="user_mgmt_edit_first_name")
                    edit_last_name = st.text_input("Last name", value=str(selected_user.get("last_name", "")), key="user_mgmt_edit_last_name")
                with edit_right:
                    selected_edit_role = st.selectbox("Role", role_labels, index=default_role_idx, key="user_mgmt_edit_role")
                    edit_status = st.selectbox("Status", ["active", "inactive", "locked"], index=["active", "inactive", "locked"].index(str(selected_user.get("status", "active")) if str(selected_user.get("status", "active")) in ["active", "inactive", "locked"] else "active"), key="user_mgmt_edit_status")
                    edit_is_active = st.checkbox("Is active", value=bool(selected_user.get("is_active", True)), key="user_mgmt_edit_is_active")
                edit_submitted = st.form_submit_button("Save Changes", type="primary", use_container_width=True)

            if edit_submitted:
                try:
                    edit_role_id = int(str(selected_edit_role).split(" - ", 1)[0])
                except Exception:
                    edit_role_id = current_role_id
                update_payload = {
                    "email": edit_email.strip(),
                    "first_name": edit_first_name.strip(),
                    "last_name": edit_last_name.strip(),
                    "role_id": edit_role_id,
                    "status": edit_status,
                    "is_active": bool(edit_is_active),
                }
                update_response = user_mgmt_request("PUT", f"/users/{selected_user_id}", show_error=False, json=update_payload)
                if update_response and update_response.get("id"):
                    st.success("User profile updated.")
                    user_mgmt_refresh_caches()
                    st.rerun()
                else:
                    st.error("Unable to update user.")

    with tab_assign:
        assignable_users = [row for row in users_data if isinstance(row, dict)]
        if not assignable_users:
            st.caption("Create users first to assign projects.")
        elif not project_names:
            st.caption("No projects found yet. Complete Project Onboarding first.")
        else:
            selected_assign_user = st.selectbox(
                "User",
                [str(row.get("username")) for row in assignable_users if str(row.get("username", "")).strip()],
                key="user_mgmt_assign_user_selector",
            )
            existing_assignments = assignment_map.get(selected_assign_user, [])
            selected_projects = st.multiselect(
                "Assigned projects",
                project_names,
                default=[project for project in existing_assignments if project in project_names],
                key="user_mgmt_assign_projects",
            )

            if st.button("Save Project Assignment", key="user_mgmt_assign_save", type="primary", use_container_width=True):
                assignment_map[selected_assign_user] = selected_projects

                project_payload = onboarding_connectivity.get("project", {}) if isinstance(onboarding_connectivity, dict) else {}
                if not isinstance(project_payload, dict):
                    project_payload = {}

                payload = {
                    "project": project_payload,
                    "prometheus_url": onboarding_connectivity.get("prometheus_url", "") if isinstance(onboarding_connectivity, dict) else "",
                    "new_relic_url": onboarding_connectivity.get("new_relic_url", "") if isinstance(onboarding_connectivity, dict) else "",
                    "datadog_url": onboarding_connectivity.get("datadog_url", "") if isinstance(onboarding_connectivity, dict) else "",
                    "provider_statuses": st.session_state.get("onboarding_status", {}),
                    "user_assignments": assignment_map,
                    "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
                save_response = request_json_with_fallback(
                    "POST",
                    [f"{GATEWAY_BASE}/onboarding/connectivity", f"{MONITORING_ADAPTER_BASE}/onboarding/connectivity"],
                    json=payload,
                )
                persisted = data_from_gateway(save_response).get("connectivity", {}) if save_response else {}
                if isinstance(persisted, dict):
                    st.session_state["onboarding_connectivity"] = persisted
                    st.success("Project assignment saved.")
                    st.rerun()
                else:
                    st.error("Unable to save project assignment.")

            st.markdown("#### Current Assignment Matrix")
            assignment_rows = []
            for row in assignable_users:
                username = str(row.get("username", "")).strip()
                if not username:
                    continue
                assignment_rows.append(
                    {
                        "Username": username,
                        "Projects": ", ".join(assignment_map.get(username, [])),
                    }
                )
            if assignment_rows:
                st.dataframe(assignment_rows, hide_index=True, width="stretch")

    with tab_audit:
        if audit_data:
            st.dataframe(
                [
                    {
                        "Actor": row.get("actor_username") or row.get("actor"),
                        "Action": row.get("action"),
                        "Resource": row.get("resource_type"),
                        "Resource ID": row.get("resource_id"),
                        "Message": row.get("message") or row.get("payload"),
                        "At": row.get("created_at"),
                    }
                    for row in audit_data
                    if isinstance(row, dict)
                ],
                hide_index=True,
                width="stretch",
            )
        else:
            st.caption("No audit log rows returned yet.")


def render_executive_dashboard_section() -> None:
    st.markdown("## Executive Dashboard")
    st.caption("Business-level view of reliability, risk, and cost.")

    user_mgmt_me = st.session_state.get("user_mgmt_me", {})
    account = user_mgmt_me.get("user", user_mgmt_me) if isinstance(user_mgmt_me, dict) else {}
    role_name = str(account.get("role_name") or st.session_state.get("user_mgmt_user", {}).get("role_name") or "").strip()
    is_allowed = role_name.lower() in {"executive", "administrator"}
    if not is_allowed:
        st.warning("Executive Dashboard is available to Executive and Administrator roles.")
        return

    refresh_alert_snapshots()
    recent_alerts = [row for row in st.session_state.get("recent_alerts_snapshot", []) if isinstance(row, dict)]
    all_alerts = [row for row in st.session_state.get("all_alerts_snapshot", []) if isinstance(row, dict)]
    closed_incidents = _fetch_closed_incidents_cached(limit=250)

    workflow = st.session_state.get("workflow") or st.session_state.get("last_workflow", {})
    finops = workflow.get("finops", {}) if isinstance(workflow, dict) else {}
    totals = finops.get("totals", {}) if isinstance(finops, dict) else {}

    by_severity: dict[str, int] = {}
    for row in all_alerts:
        severity = str(row.get("severity") or "unknown").strip().upper() or "UNKNOWN"
        by_severity[severity] = by_severity.get(severity, 0) + 1

    now_utc = datetime.now(timezone.utc)
    closed_last_24h = 0
    for row in closed_incidents:
        if not isinstance(row, dict):
            continue
        created = str(row.get("created_at") or "").strip()
        if not created:
            continue
        try:
            created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            if created_dt.tzinfo is None:
                created_dt = created_dt.replace(tzinfo=timezone.utc)
            if (now_utc - created_dt).total_seconds() <= 86400:
                closed_last_24h += 1
        except Exception:
            continue

    sev_order = ["CRITICAL", "HIGH", "WARNING", "INFO", "UNKNOWN"]
    critical_open = by_severity.get("CRITICAL", 0)
    high_open = by_severity.get("HIGH", 0)
    total_open = len(all_alerts)

    metric_row(
        [
            ("Open Alerts", total_open),
            ("Critical Open", critical_open),
            ("Closed (24h)", closed_last_24h),
            ("Recent Alerts", len(recent_alerts)),
        ]
    )

    metric_row(
        [
            ("High Open", high_open),
            ("Estimated Cost", f"${float(totals.get('estimated_cost_usd', 0.0) or 0.0):.4f}"),
            ("Total Tokens", int(totals.get("tokens", 0) or 0)),
            ("Role", role_name or "Unknown"),
        ]
    )

    left, right = st.columns([1, 1], gap="large")
    with left:
        st.markdown("### Alert Severity Mix")
        sev_rows = [{"Severity": severity, "Count": by_severity.get(severity, 0)} for severity in sev_order if severity in by_severity]
        if sev_rows:
            st.dataframe(sev_rows, hide_index=True, width="stretch")
        else:
            st.caption("No alert severity data available.")

    with right:
        st.markdown("### Closed Incident Trend")
        by_service: dict[str, int] = {}
        for row in closed_incidents:
            if not isinstance(row, dict):
                continue
            service = str(row.get("service") or "unknown").strip() or "unknown"
            by_service[service] = by_service.get(service, 0) + 1
        service_rows = [{"Service": service, "Closed Incidents": count} for service, count in sorted(by_service.items(), key=lambda item: item[1], reverse=True)]
        if service_rows:
            st.dataframe(service_rows, hide_index=True, width="stretch")
        else:
            st.caption("No closed incidents available yet.")

    st.markdown("### Executive Summary")
    summary_lines = [
        f"Open alerts currently at {total_open}, with {critical_open} critical and {high_open} high-severity alerts.",
        f"{closed_last_24h} incidents were closed in the last 24 hours.",
        f"Estimated AI spend is ${float(totals.get('estimated_cost_usd', 0.0) or 0.0):.4f} across {int(totals.get('tokens', 0) or 0)} tokens.",
    ]
    for line in summary_lines:
        st.write(f"- {line}")


def render_alert_details_page() -> None:
    workflow = st.session_state.get("workflow") or st.session_state.get("last_workflow") or {}
    selected = st.session_state.get("alert_stream_selected", {})

    if not isinstance(workflow, dict) or not workflow:
        st.warning("No alert details are available yet. Open an alert from the stream first.")
        if st.button("Back To Alert Stream", key="alert_details_back_empty", use_container_width=True):
            st.session_state["alert_stream_details_view"] = False
            st.rerun()
        return

    incident = workflow.get("incident", {}) if isinstance(workflow.get("incident"), dict) else {}
    alert = workflow.get("alert", {}) if isinstance(workflow.get("alert"), dict) else {}
    recommendation = workflow.get("recommendation", {}) if isinstance(workflow.get("recommendation"), dict) else {}
    remediation = workflow.get("remediation_action", {}) if isinstance(workflow.get("remediation_action"), dict) else {}
    closure = workflow.get("closure_report", {}) if isinstance(workflow.get("closure_report"), dict) else {}
    metrics = workflow.get("metrics", {}) if isinstance(workflow.get("metrics"), dict) else {}
    decision = workflow.get("decision", {}) if isinstance(workflow.get("decision"), dict) else {}
    finops = workflow.get("finops", {}) if isinstance(workflow.get("finops"), dict) else {}
    gateway_response = st.session_state.get("gateway_response") or st.session_state.get("last_gateway_response") or {}
    gateway = gateway_response.get("gateway", {}) if isinstance(gateway_response.get("gateway"), dict) else {}
    events = workflow.get("events", []) if isinstance(workflow.get("events"), list) else []

    back_col, _ = st.columns([1.2, 5])
    with back_col:
        if st.button("Back To Alert Stream", key="alert_details_back", use_container_width=True):
            st.session_state["alert_stream_details_view"] = False
            st.rerun()

    selected_name = str(selected.get("alert_name") or alert.get("name") or incident.get("title") or "Alert")
    selected_id = str(selected.get("alert_id") or alert.get("id") or "N/A")
    service = str(selected.get("service") or alert.get("service") or incident.get("service") or "unknown")
    severity = str(selected.get("severity") or alert.get("severity") or metrics.get("severity") or "unknown").upper()

    st.markdown(f"## Alert Details: {html.escape(selected_name)}")
    st.caption(f"ID: {selected_id} | Service: {service} | Severity: {severity}")

    metric_row(
        [
            ("Incident ID", str(incident.get("id") or "N/A")),
            ("Workflow", str(workflow.get("scenario", {}).get("id") if isinstance(workflow.get("scenario"), dict) else "N/A")),
            ("Health Restored", "YES" if bool(metrics.get("health_restored", False)) else "NO"),
            ("Recommendation Confidence", f"{float(metrics.get('recommendation_confidence', 0.0) or 0.0):.0%}"),
        ]
    )

    policy_version = str(decision.get("policy_version") or "N/A")
    requires_approval = bool(decision.get("requires_approval", False))
    risk_tier = str(decision.get("risk_tier") or "unknown").strip().lower()
    execution_mode = str(decision.get("execution_mode") or "unknown").strip().lower()

    metric_row(
        [
            ("Risk Tier", risk_tier.upper()),
            ("Execution Mode", execution_mode.upper()),
            ("Approval Required", "YES" if requires_approval else "NO"),
            ("Policy Version", policy_version),
        ]
    )

    planner_used_raw = decision.get("planner_used")
    planner_model = str(decision.get("planner_model") or "").strip()
    planner_reason = str(decision.get("planner_reason") or "").strip()
    planner_visible = planner_used_raw is not None or bool(planner_model) or bool(planner_reason)
    if planner_visible:
        st.markdown("### Planner Metadata")
        planner_used = bool(planner_used_raw)
        left, right = st.columns([2.2, 1])
        with left:
            st.write(f"- Planner Used: {'YES' if planner_used else 'NO'}")
            st.write(f"- Planner Model: {planner_model or 'N/A'}")
            st.write(f"- Planner Reason: {planner_reason or 'N/A'}")
        with right:
            status_badge("Planner", "ENABLED" if planner_used else "FALLBACK")

    tab_summary, tab_events, tab_finops, tab_api, tab_topics, tab_raw = st.tabs(
        ["Summary", "Agent Events", "FinOps", "API Gateway", "Message Bus Topics", "Raw Payload"]
    )

    with tab_summary:
        st.markdown("### Summary")
        st.write(f"- Description: {str(alert.get('description') or selected.get('description') or 'N/A')}")
        st.write(f"- Recommended Action: {str(recommendation.get('recommended_action') or 'N/A')}")
        st.write(f"- Root Cause: {str(closure.get('root_cause') or recommendation.get('root_cause') or 'N/A')}")
        st.write(f"- Impact: {str(closure.get('impact') or recommendation.get('impact') or 'N/A')}")
        st.write(f"- Risk Tier: {risk_tier.upper()}")
        st.write(f"- Execution Mode: {execution_mode.upper()}")
        st.write(f"- Approval Required: {'YES' if requires_approval else 'NO'}")
        st.write(f"- Policy Reason: {str(decision.get('policy_reason') or 'N/A')}")

    with tab_events:
        if events:
            st.markdown("### Agent Events")
            planner_used_raw = decision.get("planner_used")
            planner_model = str(decision.get("planner_model") or "").strip()
            planner_reason = str(decision.get("planner_reason") or "").strip()
            planner_status = "N/A"
            if planner_used_raw is not None or planner_model or planner_reason:
                planner_status = "ENABLED" if bool(planner_used_raw) else "FALLBACK"

            placeholder_tokens = {"", "-", "n/a", "na", "none", "null", "unknown"}

            def _display_text(value: Any) -> str:
                text = str(value or "").strip()
                if text.lower() in placeholder_tokens:
                    return "N/A"
                return text

            def _fallback_event_fields(event: dict[str, Any]) -> tuple[str, str, str, str]:
                agent_name = str(event.get("agent") or "").strip()
                action = _display_text(event.get("action"))
                decision_text = _display_text(event.get("decision"))
                output_text = _display_text(event.get("output"))
                communicates_to = _display_text(event.get("communicates_to"))

                if agent_name == "Alert Intelligence Agent":
                    if action == "N/A":
                        action = "Assigned to incident workflow"
                    if decision_text == "N/A":
                        correlation_id = (
                            str(
                                event.get("correlation_id")
                                or alert.get("correlation_id")
                                or incident.get("correlation_id")
                                or ""
                            )
                            .strip()
                        )
                        if correlation_id:
                            decision_text = f"Severity classified as {severity.lower()}; correlation ID {correlation_id}"
                        else:
                            decision_text = f"Severity classified as {severity.lower()}"
                    if output_text in {"N/A", "pending", "Pending"}:
                        output_text = "Created incident and enriched alert event" if incident.get("id") else "Awaiting enrichment output"
                    if communicates_to == "N/A":
                        communicates_to = "Orchestrator Agent"

                elif agent_name == "Orchestrator Agent":
                    workflow_name = str(decision.get("workflow") or scenario.get("id") or "").strip()
                    next_action = str(decision.get("next_action") or "collect-context").strip() or "collect-context"
                    provider = str(decision.get("message_bus_provider") or "rabbitmq").strip().lower() or "rabbitmq"
                    if action == "N/A":
                        action = "Routing incident through policy-aware workflow"
                    if decision_text in {"N/A", "pending", "Pending"}:
                        decision_text = workflow_name or "Workflow selected"
                    if output_text in {"N/A", "pending", "Pending"}:
                        output_text = (
                            f"Next action: {next_action}; approval required: {requires_approval}; "
                            f"message bus: {provider}"
                        )
                    if communicates_to == "N/A":
                        communicates_to = "Context Intelligence Agent"

                elif agent_name == "Human Approval Layer":
                    approval_payload = workflow.get("approval", {}) if isinstance(workflow.get("approval"), dict) else {}
                    approval_decision = str(approval_payload.get("decision") or "").strip().lower()
                    if action == "N/A":
                        action = "Applying policy-aware human gate"
                    if decision_text in {"N/A", "pending", "Pending"}:
                        if approval_decision in {"approved", "rejected"}:
                            decision_text = approval_decision
                        else:
                            decision_text = "pending"
                    if output_text in {"N/A", "pending", "Pending"}:
                        output_text = "Awaiting explicit user decision in Approval Workbench"
                    if communicates_to == "N/A":
                        communicates_to = "Remediation Automation Engine"

                return action, decision_text, output_text, communicates_to

            st.dataframe(
                [
                    {
                        "Step": event.get("sequence"),
                        "Agent": event.get("agent"),
                        "Decision": _fallback_event_fields(event)[1],
                        "Output": _fallback_event_fields(event)[2],
                        "Planner": planner_status if str(event.get("agent") or "") == "Orchestrator Agent" else "-",
                        "Planner Model": planner_model if str(event.get("agent") or "") == "Orchestrator Agent" else "-",
                    }
                    for event in sorted([e for e in events if isinstance(e, dict)], key=lambda item: int(item.get("sequence", 0) or 0))
                ],
                hide_index=True,
                width="stretch",
            )

            st.markdown("#### Event Details")
            ordered_events = sorted([e for e in events if isinstance(e, dict)], key=lambda item: int(item.get("sequence", 0) or 0))
            for event in ordered_events:
                step = int(event.get("sequence", 0) or 0)
                agent_name = str(event.get("agent") or "Agent")
                action, decision_text, output_text, communicates_to = _fallback_event_fields(event)
                with st.expander(f"Step {step} | {agent_name}"):
                    st.write(f"- Action: {action}")
                    st.write(f"- Decision: {decision_text}")
                    st.write(f"- Output: {output_text}")
                    st.write(f"- Communicates To: {communicates_to}")
                    input_payload = event.get("input") if isinstance(event.get("input"), dict) else {}
                    if input_payload:
                        st.markdown("**Input Parameters**")
                        st.json(input_payload)
                    metrics_payload = event.get("metrics") if isinstance(event.get("metrics"), dict) else {}
                    if metrics_payload:
                        st.markdown("**Metrics**")
                        st.json(metrics_payload)
                    llm_calls = event.get("llm_calls") if isinstance(event.get("llm_calls"), list) else []
                    if llm_calls:
                        st.markdown("**LLM Calls**")
                        st.json(llm_calls)
                    llm_errors = event.get("llm_errors") if isinstance(event.get("llm_errors"), list) else []
                    if llm_errors:
                        st.markdown("**LLM Errors**")
                        st.json(llm_errors)
        else:
            st.caption("No agent events available.")

    with tab_finops:
        st.markdown("### FinOps")
        finops_totals = finops.get("totals", {}) if isinstance(finops, dict) else {}
        finops_provider_rows = finops.get("by_provider", []) if isinstance(finops, dict) else []
        finops_errors = finops.get("errors", []) if isinstance(finops, dict) else []

        if not finops_totals:
            rec_metadata = recommendation.get("metadata", {}) if isinstance(recommendation.get("metadata"), dict) else {}
            model_usage = rec_metadata.get("model_usage", []) if isinstance(rec_metadata.get("model_usage"), list) else []
            if model_usage:
                finops_totals = {
                    "input_tokens": sum(int(item.get("input_tokens", 0) or 0) for item in model_usage if isinstance(item, dict)),
                    "output_tokens": sum(int(item.get("output_tokens", 0) or 0) for item in model_usage if isinstance(item, dict)),
                    "total_tokens": sum(int(item.get("total_tokens", 0) or 0) for item in model_usage if isinstance(item, dict)),
                    "total_cost_usd": round(sum(float(item.get("total_cost_usd", 0.0) or 0.0) for item in model_usage if isinstance(item, dict)), 8),
                    "calls": len([item for item in model_usage if isinstance(item, dict)]),
                    "failed_calls": 0,
                    "source": "inferred-from-recommendation-metadata",
                }
                provider_totals: dict[str, dict[str, Any]] = {}
                for item in model_usage:
                    if not isinstance(item, dict):
                        continue
                    provider = str(item.get("provider") or "unknown")
                    row = provider_totals.setdefault(
                        provider,
                        {"provider": provider, "calls": 0, "total_tokens": 0, "total_cost_usd": 0.0},
                    )
                    row["calls"] += 1
                    row["total_tokens"] += int(item.get("total_tokens", 0) or 0)
                    row["total_cost_usd"] = round(float(row["total_cost_usd"]) + float(item.get("total_cost_usd", 0.0) or 0.0), 8)
                finops_provider_rows = list(provider_totals.values())

        if finops_totals:
            metric_row(
                [
                    ("Total Tokens", int(finops_totals.get("total_tokens", 0) or 0)),
                    ("Total Cost (USD)", f"${float(finops_totals.get('total_cost_usd', 0.0) or 0.0):.6f}"),
                    ("Calls", int(finops_totals.get("calls", 0) or 0)),
                    ("Failed Calls", int(finops_totals.get("failed_calls", 0) or 0)),
                ]
            )
            st.markdown("#### Totals")
            table_from_dict(finops_totals, "Metric", "Value")
        else:
            st.caption("No FinOps totals available.")

        st.markdown("#### By Provider")
        if isinstance(finops_provider_rows, list) and finops_provider_rows:
            st.dataframe(
                [row for row in finops_provider_rows if isinstance(row, dict)],
                hide_index=True,
                width="stretch",
            )
        else:
            st.caption("No provider-level FinOps records.")

        if isinstance(finops_errors, list) and finops_errors:
            st.markdown("#### Errors")
            st.dataframe(
                [row for row in finops_errors if isinstance(row, dict)],
                hide_index=True,
                width="stretch",
            )

    with tab_api:
        st.markdown("### API Gateway")
        trace_id = str(gateway_response.get("trace_id") or incident.get("trace_id") or "N/A")
        safety = gateway.get("safety", {}) if isinstance(gateway, dict) and isinstance(gateway.get("safety"), dict) else {}
        metric_row(
            [
                ("Trace ID", trace_id),
                ("Safety Decision", str(safety.get("decision") or "unknown").upper()),
                ("Risk", str(safety.get("risk") or "unknown").upper()),
                ("Policy", str(safety.get("policy") or "N/A")),
            ]
        )

        if gateway:
            st.markdown("#### Gateway Payload")
            st.json(gateway)
        else:
            st.caption("Gateway details are not available for this alert payload.")

        if isinstance(gateway_response, dict) and gateway_response:
            st.markdown("#### Response Envelope")
            st.json({
                "trace_id": gateway_response.get("trace_id"),
                "has_data": bool(gateway_response.get("data")),
                "keys": list(gateway_response.keys()),
            })
        else:
            st.markdown("#### Inferred Gateway Context")
            st.json(
                {
                    "trace_id": trace_id,
                    "mode": workflow.get("mode"),
                    "safety_decision": str(safety.get("decision") or "unknown").upper(),
                    "note": "Gateway envelope not present in processed payload; showing inferred context.",
                }
            )

    with tab_topics:
        st.markdown("### Message Bus Topics")
        provider = str(decision.get("message_bus_provider") or "unknown").strip().lower() or "unknown"
        stream_count = int(decision.get("stream_count", 0) or 0)
        stream_threshold = int(decision.get("stream_threshold", 0) or 0)
        metric_row(
            [
                ("Provider", provider.upper()),
                ("Stream Count", stream_count),
                ("Threshold", stream_threshold),
                ("Workflow", str(decision.get("workflow") or "N/A")),
            ]
        )

        def _fallback_published_topic(agent_name: str) -> str:
            key = str(agent_name or "").strip().lower()
            if key == "alert intelligence agent":
                return "enriched-alerts"
            if key == "orchestrator agent":
                return "orchestration-events"
            if key == "context intelligence agent":
                return "context-events"
            if key == "resolution intelligence agent":
                return "resolution-events"
            if key == "human approval layer":
                return "approval-events"
            if key == "remediation automation engine":
                return "remediation-events"
            if key == "closure & validation":
                return "closure-events"
            return "N/A"

        def _fallback_parameters(agent_name: str) -> dict[str, Any]:
            key = str(agent_name or "").strip().lower()
            if key == "alert intelligence agent":
                return {
                    "flow_id": (workflow.get("scenario", {}) if isinstance(workflow.get("scenario"), dict) else {}).get("id"),
                    "source": alert.get("source"),
                    "name": alert.get("name"),
                    "service": alert.get("service"),
                    "severity": alert.get("severity"),
                    "description": alert.get("description"),
                    "labels": alert.get("labels"),
                    "annotations": alert.get("annotations"),
                }
            if key == "orchestrator agent":
                return {
                    "incident_id": incident.get("id"),
                    "service": incident.get("service"),
                    "severity": incident.get("severity") or alert.get("severity"),
                    "title": incident.get("title"),
                }
            if key == "context intelligence agent":
                labels_payload = alert.get("labels")
                labels_map = labels_payload if isinstance(labels_payload, dict) else {}
                return {
                    "incident_id": incident.get("id"),
                    "alert_service": alert.get("service"),
                    "alert_severity": alert.get("severity"),
                    "deployment_label": labels_map.get("deployment"),
                    "trace_id": gateway_response.get("trace_id") or incident.get("trace_id"),
                }
            if key == "resolution intelligence agent":
                return {
                    "incident_id": incident.get("id"),
                    "root_cause": recommendation.get("root_cause"),
                    "recommended_action": recommendation.get("recommended_action"),
                    "confidence": recommendation.get("confidence"),
                }
            if key == "human approval layer":
                approval_payload = workflow.get("approval", {}) if isinstance(workflow.get("approval"), dict) else {}
                return {
                    "incident_id": incident.get("id"),
                    "recommendation_id": recommendation.get("id"),
                    "decision": approval_payload.get("decision"),
                    "approver": approval_payload.get("approver"),
                    "channel": approval_payload.get("channel"),
                }
            if key == "remediation automation engine":
                return {
                    "incident_id": incident.get("id"),
                    "action_type": remediation.get("action_type"),
                    "target": remediation.get("target"),
                    "status": remediation.get("status"),
                }
            if key == "closure & validation":
                return {
                    "incident_id": incident.get("id"),
                    "health_restored": closure.get("health_restored"),
                    "alerts_cleared": closure.get("alerts_cleared"),
                    "root_cause": closure.get("root_cause") or recommendation.get("root_cause"),
                }
            return {}

        ordered_events = sorted([e for e in events if isinstance(e, dict)], key=lambda item: int(item.get("sequence", 0) or 0))
        flow_rows: list[dict[str, Any]] = []
        flow_parameters: list[tuple[int, str, dict[str, Any]]] = []
        publish_edges: list[tuple[str, str, int]] = []
        consume_edges: list[tuple[str, str, int]] = []
        previous_published_topic = "raw-alerts"
        for index, event in enumerate(ordered_events):
            agent_name = str(event.get("agent") or "")
            channel_text = str(event.get("communicates_to") or "")
            matches = re.findall(r"via\s+([a-z0-9-]+)", channel_text.lower())
            published_topic = matches[0] if matches else _fallback_published_topic(agent_name)
            consumed_topic = "raw-alerts" if index == 0 else previous_published_topic
            if published_topic != "N/A":
                previous_published_topic = published_topic

            event_input = event.get("input", {}) if isinstance(event.get("input"), dict) else {}
            if not event_input:
                event_input = {k: v for k, v in _fallback_parameters(agent_name).items() if v not in (None, "", [], {})}
            parameter_keys = ", ".join(sorted(event_input.keys())) if event_input else "-"

            flow_rows.append(
                {
                    "Step": event.get("sequence"),
                    "Publisher": agent_name,
                    "Consumed Topic": consumed_topic,
                    "Published Topic": published_topic,
                    "Consumer": str(ordered_events[index + 1].get("agent") or "(end)") if index + 1 < len(ordered_events) else "(end)",
                    "Parameter Keys": parameter_keys,
                }
            )
            sequence_value = int(event.get("sequence", 0) or 0)
            if published_topic != "N/A":
                publish_edges.append((agent_name or f"agent-{index + 1}", published_topic, sequence_value))
            if consumed_topic != "N/A":
                consume_edges.append((consumed_topic, agent_name or f"agent-{index + 1}", sequence_value))
            if event_input:
                flow_parameters.append((int(event.get("sequence", 0) or 0), agent_name or "Agent", event_input))

        st.markdown("#### Message Bus Topology")
        if flow_rows:
            dot_lines = [
                "digraph MessageBusFlow {",
                "rankdir=LR;",
                'graph [fontsize=10 fontname="Arial"];',
                'node [fontsize=10 fontname="Arial"];',
                'edge [fontsize=9 fontname="Arial"];',
            ]
            known_agent_nodes: set[str] = set()
            known_topic_nodes: set[str] = set()

            def _node_id(value: str, prefix: str) -> str:
                return prefix + re.sub(r"[^a-zA-Z0-9_]", "_", value)

            for publisher, topic, step in publish_edges:
                publisher_id = _node_id(publisher, "agent_")
                topic_id = _node_id(topic, "topic_")
                if publisher_id not in known_agent_nodes:
                    known_agent_nodes.add(publisher_id)
                    dot_lines.append(f'{publisher_id} [label="{publisher}" shape=box style="rounded,filled" fillcolor="#e7f0ff"];')
                if topic_id not in known_topic_nodes:
                    known_topic_nodes.add(topic_id)
                    dot_lines.append(f'{topic_id} [label="{topic}" shape=ellipse style="filled" fillcolor="#fff4cc"];')
                dot_lines.append(f'{publisher_id} -> {topic_id} [label="publish s{step}"];')

            for topic, consumer, step in consume_edges:
                topic_id = _node_id(topic, "topic_")
                consumer_id = _node_id(consumer, "agent_")
                if topic_id not in known_topic_nodes:
                    known_topic_nodes.add(topic_id)
                    dot_lines.append(f'{topic_id} [label="{topic}" shape=ellipse style="filled" fillcolor="#fff4cc"];')
                if consumer_id not in known_agent_nodes:
                    known_agent_nodes.add(consumer_id)
                    dot_lines.append(f'{consumer_id} [label="{consumer}" shape=box style="rounded,filled" fillcolor="#e7f0ff"];')
                dot_lines.append(f'{topic_id} -> {consumer_id} [label="consume s{step}"];')

            dot_lines.append("}")
            st.graphviz_chart("\n".join(dot_lines), use_container_width=True)
        else:
            st.caption("No topology could be rendered because no event flow rows were found.")

        st.markdown("#### What Makes Sense")
        if flow_rows:
            missing_published = sum(1 for row in flow_rows if str(row.get("Published Topic") or "") == "N/A")
            missing_consumed = sum(1 for row in flow_rows if str(row.get("Consumed Topic") or "") == "N/A")
            detected_publish_topics = sorted({str(row.get("Published Topic") or "") for row in flow_rows if str(row.get("Published Topic") or "") not in {"", "N/A"}})
            st.write(f"- Publisher/consumer path is visible across {len(flow_rows)} agent steps.")
            st.write(f"- Distinct published topics detected: {len(detected_publish_topics)} ({', '.join(detected_publish_topics) if detected_publish_topics else 'none'}).")
            st.write(f"- Missing published topic mappings: {missing_published}; missing consumed topic mappings: {missing_consumed}.")
            st.write(f"- Active provider is {provider.upper()}, while topic names remain domain-level (provider-agnostic), which is expected.")
            if flow_parameters:
                st.write(f"- Parameter payloads are available for {len(flow_parameters)} of {len(flow_rows)} steps.")
            else:
                st.write("- Parameter payloads are not present in the event trace; fallback inference is being used.")
        else:
            st.caption("No interpretation available because no flow rows were generated.")

        st.markdown("#### Published vs Consumed")
        if flow_rows:
            st.dataframe(flow_rows, hide_index=True, width="stretch")
        else:
            st.caption("No event flow data available.")

        st.markdown("#### Parameters Passed")
        if flow_parameters:
            for step, agent_name, params in flow_parameters:
                with st.expander(f"Step {step} | {agent_name}"):
                    st.json(params)
        else:
            st.caption("No parameter payloads found in event inputs.")

        detected_topics: set[str] = set()
        for event in events:
            if not isinstance(event, dict):
                continue
            channel_text = str(event.get("communicates_to") or "")
            for match in re.findall(r"via\s+([a-z0-9-]+)", channel_text.lower()):
                detected_topics.add(match)

        for row in flow_rows:
            published_topic = str(row.get("Published Topic") or "").strip().lower()
            consumed_topic = str(row.get("Consumed Topic") or "").strip().lower()
            if published_topic and published_topic != "n/a":
                detected_topics.add(published_topic)
            if consumed_topic and consumed_topic != "n/a":
                detected_topics.add(consumed_topic)

        canonical_topics = [str(topic) for topic in ALL_TOPICS]
        topic_rows = [
            {
                "Topic": topic,
                "Present In Event Trace": "YES" if topic in detected_topics else "NO",
                "Type": "canonical",
            }
            for topic in canonical_topics
        ]
        for topic in sorted(detected_topics):
            if topic not in canonical_topics:
                topic_rows.append(
                    {
                        "Topic": topic,
                        "Present In Event Trace": "YES",
                        "Type": "detected",
                    }
                )

        st.dataframe(topic_rows, hide_index=True, width="stretch")

    with tab_raw:
        st.markdown("### Raw Workflow Payload")
        st.json(workflow)


def render_alert_stream_section(entries: list[dict[str, Any]]) -> None:
    if bool(st.session_state.get("alert_stream_details_view", False)):
        render_alert_details_page()
        return

    st.markdown("## Alert Stream")
    st.caption("Live incident feed with latest and historical alert views. Alerts from ingestion are auto-processed.")

    ingestion_status = fetch_ingestion_status()
    pipeline = ingestion_status.get("status", {}) if isinstance(ingestion_status.get("status"), dict) else {}
    pending_count = int(ingestion_status.get("pending_count", 0) or 0)
    if pipeline:
        st.caption(
            "Ingestion pipeline: "
            f"runs={pipeline.get('runs', 0)} | "
            f"last={pipeline.get('last_finished_at') or 'n/a'} | "
            f"pending_files={pending_count}"
        )

    action_left, action_right = st.columns([1, 5])
    with action_left:
        if st.button("Refresh Alerts", key="alert_stream_refresh_main", use_container_width=True):
            refresh_alert_snapshots(force=True)
            st.rerun()

    with action_right:
        stream_view_mode = st.radio(
            "Alert Scope",
            options=["Latest 50", "Historical"],
            index=0,
            horizontal=True,
            key="alert_stream_view_mode",
            label_visibility="collapsed",
        )

    history_limit = ALERT_STREAM_LATEST_LIMIT
    history_window = "All available"
    if stream_view_mode == "Historical":
        hist_col_left, hist_col_right = st.columns([2, 3])
        with hist_col_left:
            history_limit = st.slider(
                "Historical rows",
                min_value=50,
                max_value=500,
                value=200,
                step=25,
                key="alert_stream_history_limit",
            )
        with hist_col_right:
            history_window = st.selectbox(
                "History window",
                options=["Last 24 hours", "Last 7 days", "Last 30 days", "All available"],
                index=1,
                key="alert_stream_history_window",
            )

    status_filter = st.radio(
        "Status",
        options=["All", "Failed", "Running"],
        index=0,
        horizontal=True,
        key="alert_stream_status_filter",
        label_visibility="collapsed",
    )

    all_alerts_snapshot = [row for row in st.session_state.get("all_alerts_snapshot", []) if isinstance(row, dict)]
    recent_alerts_snapshot = [row for row in st.session_state.get("recent_alerts_snapshot", []) if isinstance(row, dict)]
    selected_limit = ALERT_STREAM_LATEST_LIMIT if stream_view_mode == "Latest 50" else int(history_limit)

    selected_entries = get_alert_stream_entries_with_limit(all_alerts_snapshot, max_entries=selected_limit)

    if stream_view_mode == "Historical" and history_window != "All available":
        now_utc = datetime.now(timezone.utc)
        cutoff_map = {
            "Last 24 hours": now_utc - timedelta(hours=24),
            "Last 7 days": now_utc - timedelta(days=7),
            "Last 30 days": now_utc - timedelta(days=30),
        }
        cutoff = cutoff_map.get(history_window)
        if cutoff is not None:
            filtered_entries: list[dict[str, Any]] = []
            for item in selected_entries:
                created_at = _parse_alert_timestamp(item.get("created_at") or item.get("updated_at"))
                if created_at is None or created_at >= cutoff:
                    filtered_entries.append(item)
            selected_entries = filtered_entries

    if not selected_entries and stream_view_mode == "Latest 50":
        selected_entries = entries or get_flows(recent_alerts_snapshot)

    if stream_view_mode == "Latest 50":
        st.caption(f"Showing the latest {ALERT_STREAM_LATEST_LIMIT} alerts.")
    else:
        st.caption(f"Showing historical alerts: up to {selected_limit} rows, window {history_window}.")

    selected_from_stream = render_alert_stream(selected_entries, status_filter=status_filter, display_limit=selected_limit)
    if selected_from_stream and isinstance(selected_from_stream, dict):
        selected_alert_id = str(selected_from_stream.get("alert_id") or "").strip()
        processed_result = fetch_processed_result_for_alert(selected_alert_id)
        processed_payload = data_from_gateway(processed_result) if processed_result else {}
        if isinstance(processed_payload, dict) and processed_payload.get("incident"):
            st.session_state["workflow"] = processed_payload
            st.session_state["last_workflow"] = processed_payload
            inferred_trace_id = (
                str(processed_payload.get("incident", {}).get("trace_id") or "").strip()
                if isinstance(processed_payload.get("incident"), dict)
                else ""
            )
            gateway_snapshot = {
                "trace_id": inferred_trace_id or None,
                "gateway": {
                    "path": "/alerts/{id}/processed-result",
                    "target_url": MONITORING_ADAPTER_BASE,
                    "safety": {"decision": "unknown", "risk": "unknown", "policy": "n/a"},
                },
                "data": processed_payload,
            }
            st.session_state["gateway_response"] = gateway_snapshot
            st.session_state["last_gateway_response"] = gateway_snapshot
            st.session_state["pending_nav_label"] = "Alert Stream"
            st.session_state["alert_stream_details_view"] = True
            st.success("Loaded processed alert summary from database.")
            st.rerun()

        selection_kind = str(selected_from_stream.get("kind") or "").strip().lower()
        if selection_kind == "guidance":
            apply_guidance_selection(st.session_state, str(selected_from_stream.get("guidance_query") or ""))
            st.session_state["selected_flow"] = str(st.session_state.get("selected_flow") or "payment-latency")
            st.session_state.pop("workflow", None)
            st.session_state.pop("gateway_response", None)
            st.success("Processed result not found yet. Opened guidance for selected alert.")
            st.rerun()

        selected_flow = str(selected_from_stream.get("flow_id") or "").strip()
        if selected_flow:
            st.session_state["selected_flow"] = selected_flow
            loaded = run_selected_flow(
                selected_flow,
                gateway_base=GATEWAY_BASE,
                request_json=request_json,
                state=st.session_state,
                fast_mode_enabled=bool(st.session_state.get("fast_mode_enabled", True)),
            )
            if not loaded:
                st.session_state.pop("workflow", None)
                st.session_state.pop("gateway_response", None)
            if loaded:
                st.session_state["alert_stream_details_view"] = True
                st.success("Loaded latest alert summary.")
            else:
                st.info("Processed result not found yet. Loading latest flow summary.")
            st.rerun()

        if selection_kind in {"home", "alert_stream"}:
            st.session_state["pending_nav_label"] = "Alert Stream"
            st.session_state["alert_stream_details_view"] = True
            st.rerun()

    if not entries:
        st.info("No alert stream entries available yet. Generate a demo event or refresh.")


def render_ingestion_pipeline_section() -> None:
    st.markdown("## Ingestion Pipeline")
    st.caption("Reads alert files from the input folder every 10 minutes and auto-processes workflows.")

    status_payload = fetch_ingestion_status()
    status = status_payload.get("status", {}) if isinstance(status_payload.get("status"), dict) else {}
    config = status_payload.get("config", {}) if isinstance(status_payload.get("config"), dict) else {}
    pending_files = status_payload.get("pending_files", []) if isinstance(status_payload.get("pending_files"), list) else []

    control_left, control_right = st.columns([1, 1])
    with control_left:
        if st.button("Run Ingestion Now", key="run_ingestion_now_btn", type="primary", use_container_width=True):
            ok, response = run_ingestion_manual()
            if ok:
                result = response.get("result", {}) if isinstance(response.get("result"), dict) else {}
                st.success(
                    "Ingestion run completed. "
                    f"processed_files={result.get('processed_files', 0)}, processed_alerts={result.get('processed_alerts', 0)}, failed_files={result.get('failed_files', 0)}"
                )
                refresh_alert_snapshots(force=True)
                _fetch_closed_incidents_cached.clear()
                st.rerun()
            else:
                st.error("Unable to trigger ingestion run. Ensure monitoring-adapter is available.")
    with control_right:
        if st.button("Refresh Pipeline Status", key="refresh_ingestion_status_btn", use_container_width=True):
            st.rerun()

    metric_row(
        [
            ("Enabled", "YES" if bool(config.get("enabled", status.get("enabled", False))) else "NO"),
            ("Interval (s)", int(config.get("interval_seconds", status.get("interval_seconds", 0)) or 0)),
            ("Pending Files", len(pending_files)),
            ("Runs", int(status.get("runs", 0) or 0)),
        ]
    )

    st.markdown("### Folder Wiring")
    st.write(f"- Input folder: {config.get('input_dir', 'n/a')}")
    st.write(f"- Processed folder: {config.get('processed_dir', 'n/a')}")
    st.write(f"- Failed folder: {config.get('failed_dir', 'n/a')}")
    st.write(
        "- Processing mode: "
        + ("Auto-process enabled" if bool(config.get("auto_process", True)) else "Ingest only")
    )

    st.markdown("### Pending Input Files")
    if pending_files:
        st.dataframe([{"File": str(name)} for name in pending_files], hide_index=True, width="stretch")
    else:
        st.caption("No pending files in input folder.")

    last_run = status.get("last_run", {}) if isinstance(status.get("last_run"), dict) else {}
    if last_run:
        st.markdown("### Last Run Summary")
        table_from_dict(
            {
                "reason": last_run.get("reason"),
                "status": last_run.get("status"),
                "processed_files": last_run.get("processed_files"),
                "processed_alerts": last_run.get("processed_alerts"),
                "failed_files": last_run.get("failed_files"),
                "last_started_at": status.get("last_started_at"),
                "last_finished_at": status.get("last_finished_at"),
            }
        )


st.set_page_config(page_title="KaiMS", page_icon="K", layout="wide", initial_sidebar_state="expanded")
apply_datamatics_stylesheet()

if "ui_theme_mode" not in st.session_state:
    st.session_state["ui_theme_mode"] = "Dark"

_theme_col_left, _theme_col_right = st.columns([8, 2])
with _theme_col_right:
    st.selectbox(
        "Theme",
        ["Dark", "Light"],
        key="ui_theme_mode",
        help="Switch between dark and light application theme.",
    )

theme_mode = str(st.session_state.get("ui_theme_mode", "Dark"))

apply_datamatics_base_stylesheet()
apply_datamatics_theme_stylesheet(theme_mode)

if not st.session_state.get("user_mgmt_access_token"):
    st.markdown("## KaiMS Autonomous Operations")
    st.caption("Sign in to access the operational workspace, alert stream, and enterprise admin tools.")
    auth_left, auth_right = st.columns([1, 1])
    with auth_left:
        render_admin_access_panel()
    with auth_right:
        st.markdown("#### What you can access")
        st.write("- Incident workspace and alert stream")
        st.write("- Executive dashboard for leadership KPIs")
        st.write("- Project onboarding and user management for administrators")
        st.write("- Workflow execution, approvals, and audit history")
    st.stop()

_health = _check_service_health()
_dot_gw = "kaiops-hero-pill-dot-amber" if _health.get("gateway") else "kaiops-hero-pill-dot-offline"
_dot_rag = "kaiops-hero-pill-dot-blue" if _health.get("rag") else "kaiops-hero-pill-dot-offline"
_dot_agents = "" if _health.get("monitoring_adapter") else "kaiops-hero-pill-dot-offline"
_gw_label = "Gateway Active" if _health.get("gateway") else "Gateway Offline"
_rag_label = "RAG Grounded" if _health.get("rag") else "RAG Not Ready"
_agents_label = "Agents Online" if _health.get("monitoring_adapter") else "Agents Offline"
recent_alerts_snapshot = st.session_state.get("recent_alerts_snapshot", [])
all_alerts_snapshot = st.session_state.get("all_alerts_snapshot", [])
flows = st.session_state.get("flows", [])
alert_stream_entries = get_alert_stream_entries(all_alerts_snapshot)
if not alert_stream_entries:
    alert_stream_entries = get_flows(recent_alerts_snapshot)
ensure_ui_defaults(st.session_state)
if "background_warmup_enabled" not in st.session_state:
    st.session_state["background_warmup_enabled"] = True
if "auto_run_on_load" not in st.session_state:
    st.session_state["auto_run_on_load"] = False
workflow = st.session_state.get("workflow") or st.session_state.get("last_workflow", {})
if "flow_catalog_preview" not in st.session_state:
    st.session_state["flow_catalog_preview"] = {
        "data": {"entries": flows, "count": len(flows), "path": "rag/flows.json"}
    }
catalog_preview = st.session_state.get("flow_catalog_preview")
catalog_entries = data_from_gateway(catalog_preview).get("entries", []) if catalog_preview else flows
if "initial_flow_loaded" not in st.session_state:
    st.session_state["initial_flow_loaded"] = False

current_user_mgmt_me = st.session_state.get("user_mgmt_me", {})
if isinstance(current_user_mgmt_me, dict):
    current_account = current_user_mgmt_me.get("user", current_user_mgmt_me)
else:
    current_account = {}
current_role_name = str(current_account.get("role_name") or st.session_state.get("user_mgmt_user", {}).get("role_name") or "").strip()
is_admin_user_nav = current_role_name.lower() == "administrator"
is_executive_user_nav = current_role_name.lower() == "executive"

menu_options = ["Alert Stream", "Ingestion Pipeline"]
if is_admin_user_nav or is_executive_user_nav:
    menu_options.append("Executive Dashboard")
if is_admin_user_nav:
    menu_options.append("Admin Center")

home_workspace_options = [
    "Incident Summary",
    "Alerts & Quick Docs",
    "Agent Flow",
    "Gateway Safety",
    "Message Bus",
    "FinOps",
    "Closed Incidents",
    "Incident Metadata Explorer",
]
admin_workspace_options = ["Project Onboarding", "User Management", "Alert Onboarding Pack"]

nav_label_to_section = {
    "Alert Stream": "alert_stream",
    "Ingestion Pipeline": "ingestion_pipeline",
    "Executive Dashboard": "executive",
    "Admin Center": "admin",
}
nav_section_to_label = {value: key for key, value in nav_label_to_section.items()}
if "nav_section" not in st.session_state:
    st.session_state["nav_section"] = "alert_stream"
if "home_workspace_view" not in st.session_state:
    st.session_state["home_workspace_view"] = "Incident Summary"
if st.session_state.get("home_workspace_view") not in home_workspace_options:
    st.session_state["home_workspace_view"] = "Incident Summary"
if "admin_workspace_view" not in st.session_state:
    st.session_state["admin_workspace_view"] = "Project Onboarding"
if st.session_state.get("admin_workspace_view") not in admin_workspace_options:
    st.session_state["admin_workspace_view"] = "Project Onboarding"
if st.session_state.get("nav_section") not in nav_section_to_label:
    st.session_state["nav_section"] = "alert_stream"

pending_nav_label = str(st.session_state.pop("pending_nav_label", "") or "").strip()
if pending_nav_label:
    if pending_nav_label in nav_label_to_section:
        st.session_state["nav_section"] = nav_label_to_section[pending_nav_label]
    st.session_state["kaiops_nav_section"] = pending_nav_label

if "kaiops_nav_section" in st.session_state:
    st.session_state["nav_section"] = nav_label_to_section.get(
        str(st.session_state.get("kaiops_nav_section") or "Alert Stream"),
        "alert_stream",
    )
allowed_sections = {nav_label_to_section[label] for label in menu_options}
if st.session_state.get("nav_section") not in allowed_sections:
    st.session_state["nav_section"] = "executive" if is_executive_user_nav else "alert_stream"
current_nav_section = st.session_state.get("nav_section", "alert_stream")

if current_nav_section == "alert_stream" and st.session_state.get("background_warmup_enabled", True):
    if _collect_background_warmup_results():
        st.rerun()
    data_loaded = bool(st.session_state.get("recent_alerts_snapshot")) and bool(st.session_state.get("flows"))
    if not data_loaded:
        _start_background_warmup_jobs()

if current_nav_section == "home":
    sorted_events = sorted(workflow.get("events", []), key=lambda item: item.get("sequence", 0))
    st.markdown(
        f"""
        <style>
            .kaiops-hero-pill-dot-offline {{ background: #64748b !important; }}
        </style>
        <div class="kaiops-hero-wrap">
            <div class="kaiops-hero-title">KaiMS Autonomous Operations - AI Powered SRE Platform..</div>
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
if current_nav_section == "home" and not st.session_state.get("workflow") and not st.session_state.get("initial_flow_loaded"):
    default_flow_id = first_actionable_flow(catalog_entries)
    if default_flow_id:
        st.session_state["selected_flow"] = default_flow_id
        st.session_state["initial_flow_loaded"] = True

if (
    current_nav_section == "home"
    and not st.session_state.get("workflow")
    and not st.session_state.get("alerts_guidance_open")
    and bool(st.session_state.get("auto_run_on_load", False))
    and st.session_state.get("selected_flow")
):
    if run_selected_flow(
        str(st.session_state.get("selected_flow", "")),
        gateway_base=GATEWAY_BASE,
        request_json=request_json,
        state=st.session_state,
        fast_mode_enabled=bool(st.session_state.get("fast_mode_enabled", True)),
    ):
        refresh_alert_snapshots(force=True)
        st.session_state["last_flow_refresh_ts"] = time.time()
        st.rerun()

with st.sidebar:
    st.markdown(
        """
        <div class="kaiops-sidebar-hero" style="position:relative;overflow:hidden;">
            <div style="position:absolute;right:-35px;top:-35px;width:110px;height:110px;border-radius:999px;
                            background:rgba(56,189,248,0.16);filter:blur(2px);"></div>
            <div class="kaiops-sidebar-title-row">
                <span class="kaiops-sidebar-icon">&#128640;</span>
                <h3>Mission Control</h3>
                <span class="kaiops-sidebar-live">
                    <span class="kaiops-sidebar-live-dot"></span>
                    LIVE
                </span>
            </div>
            <p>Everything is now routed from this left navigation rail.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="kaiops-sidebar-section">Primary Navigation</div>', unsafe_allow_html=True)
    menu_choice = st.radio(
        "Menu",
        menu_options,
        index=menu_options.index(nav_section_to_label.get(current_nav_section, "Alert Stream")) if nav_section_to_label.get(current_nav_section, "Alert Stream") in menu_options else 0,
        key="kaiops_nav_section",
        horizontal=False,
        label_visibility="collapsed",
    )
    st.session_state["nav_section"] = nav_label_to_section.get(menu_choice, "alert_stream")
    active_nav_section = st.session_state.get("nav_section", "alert_stream")

    if active_nav_section == "admin":
        st.markdown(
            """
            <div class="kaiops-nav-active-card">
                <div class="kaiops-nav-active-label">Workspace Views</div>
                <div class="kaiops-nav-active-value">Views are available as tabs in the main workspace.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown('<div class="kaiops-sidebar-section">Demo Links</div>', unsafe_allow_html=True)
    st.markdown(
        f"""
        <div class="kaiops-demo-links">
            <a href="http://localhost:8501" target="_blank">Open KaiMS UI</a>
            <a href="{GATEWAY_BASE}/sample/flows" target="_blank">Open Sample Flows API</a>
            <a href="{GATEWAY_BASE}/docs" target="_blank">Open API Docs (Swagger)</a>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("Run Payment Latency Demo", key="run_payment_demo_sidebar", width="stretch"):
        demo_response = request_json("POST", f"{GATEWAY_BASE}/sample/payment-latency/workflow", show_error=False)
        if isinstance(demo_response, dict) and apply_workflow_payload(
            st.session_state,
            "payment-latency",
            demo_response,
        ):
            refresh_alert_snapshots(force=True)
            st.session_state["last_flow_refresh_ts"] = time.time()
            st.success("Payment latency demo flow started.")
            st.rerun()
        else:
            st.error("Demo flow endpoint did not return a valid workflow payload.")

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

        background_warmup_enabled = st.toggle(
            "Background warm-up on load",
            value=st.session_state.get("background_warmup_enabled", True),
            help="Load alerts and flow catalog in the background after page render.",
        )
        st.session_state["background_warmup_enabled"] = background_warmup_enabled

        pending_warmup = st.session_state.get("warmup_jobs", {})
        if isinstance(pending_warmup, dict) and pending_warmup:
            st.caption(f"Warm-up running: {len(pending_warmup)} task(s) in background")
        elif st.session_state.get("warmup_completed_once"):
            st.caption("Warm-up complete")

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

if st.session_state.get("nav_section") == "executive":
    render_executive_dashboard_section()
    st.stop()

if st.session_state.get("nav_section") == "alert_stream":
    render_alert_stream_section(alert_stream_entries)
    st.stop()

if st.session_state.get("nav_section") == "ingestion_pipeline":
    render_ingestion_pipeline_section()
    st.stop()

if st.session_state.get("nav_section") == "admin":
    st.markdown("## Admin Center")
    st.caption("Onboarding and user administration are grouped here to keep the operational workspace clean.")
    render_admin_access_panel()

    user_mgmt_me = st.session_state.get("user_mgmt_me", {})
    if isinstance(user_mgmt_me, dict):
        admin_account = user_mgmt_me.get("user", user_mgmt_me)
    else:
        admin_account = {}

    role_name = str(admin_account.get("role_name") or st.session_state.get("user_mgmt_user", {}).get("role_name") or "").strip()
    if st.session_state.get("user_mgmt_access_token") and role_name.lower() == "administrator":
        admin_tabs = st.tabs(admin_workspace_options)
        with admin_tabs[0]:
            render_project_onboarding_section()
        with admin_tabs[1]:
            render_user_management_section()
        with admin_tabs[2]:
            render_alert_onboarding_pack_section()
    elif st.session_state.get("user_mgmt_access_token"):
        st.warning("Your account is signed in, but it is not an Administrator role.")
    else:
        st.info("Sign in as Administrator to unlock onboarding and user management.")

    st.stop()

    # RAG Workspace - placed after Live Monitoring as a knowledge-base admin section
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
            st.success(f"RAG reloaded - {reloaded_count} docs in index")

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
        st.caption("Upload docs only. KaiMS auto-detects type, extracts metadata, and links to likely incidents.")
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
            st.caption(f"Indexed: {data.get('document_count', '?')} docs in index")

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
                refresh_alert_snapshots(force=True)
                st.session_state["last_flow_refresh_ts"] = now
            st.session_state["last_flow_refresh_ts"] = now

workflow = st.session_state.get("workflow") or st.session_state.get("last_workflow", {})
gateway_response = st.session_state.get("gateway_response") or st.session_state.get("last_gateway_response", {})
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
grounded_rag_response: dict[str, Any] = {}
if workflow:
    current_workflow_export_key = f"{incident.get('id', '')}:{gateway_response.get('trace_id', '')}"
    if st.session_state.get("homepage_export_key") != current_workflow_export_key:
        st.session_state.pop("homepage_export_html", None)
        st.session_state.pop("homepage_export_name", None)
        st.session_state["homepage_export_key"] = current_workflow_export_key

    _export_left, _export_right = st.columns([12, 1])
    with _export_right:
        if st.button("📄", key="kaiops_prepare_html", width="content", help="Prepare HTML"):
            grounded_rag_response = get_grounded_rag_search(
                scenario=scenario,
                alert=alert,
                context=context,
                recommendation=recommendation,
                closure=closure,
            )
            st.session_state["homepage_export_html"] = build_complete_webpage_html(
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
            st.session_state["homepage_export_name"] = f"kaiops-homepage-{time.strftime('%Y%m%d-%H%M%S')}.html"

        if st.session_state.get("homepage_export_html"):
            st.download_button(
                "Download",
                data=st.session_state["homepage_export_html"],
                file_name=st.session_state.get("homepage_export_name", "kaiops-homepage.html"),
                mime="text/html",
                width="content",
                help="Download complete webpage as HTML",
                key="kaiops_homepage_save_html",
            )

if not workflow:
    if not (guidance_open and guidance_query):
        st.info("Select an incident from Alert Stream to run a flow.")
else:
    selected_alert = st.session_state.get("alert_stream_selected", {})
    if isinstance(selected_alert, dict) and selected_alert:
        selected_alert_action_left, selected_alert_action_right = st.columns([1, 4])
        with selected_alert_action_left:
            if st.button("Back to Alert Stream", key="back_to_alert_stream_btn", use_container_width=True):
                st.session_state["nav_section"] = "alert_stream"
                st.session_state["pending_nav_label"] = "Alert Stream"
                st.rerun()
        st.markdown(
            """
            <div style="margin-bottom:10px;padding:10px 12px;border-radius:10px;
                        border:1px solid rgba(56,189,248,0.35);background:rgba(56,189,248,0.08);">
                <div style="font-size:0.74rem;letter-spacing:0.04em;text-transform:uppercase;
                            color:#0369a1;font-weight:700;">Selected Alert</div>
                <div style="font-size:0.92rem;color:#0f172a;font-weight:700;margin-top:2px;">
                    {selected_alert_name}
                </div>
                <div style="font-size:0.8rem;color:#334155;margin-top:2px;">
                    ID {selected_alert_id} | Service {selected_alert_service} | Severity {selected_alert_severity}
                </div>
            </div>
            """.format(
                selected_alert_name=html.escape(str(selected_alert.get("alert_name") or "Alert")),
                selected_alert_id=html.escape(str(selected_alert.get("alert_id") or "N/A")),
                selected_alert_service=html.escape(str(selected_alert.get("service") or "unknown")),
                selected_alert_severity=html.escape(str(selected_alert.get("severity") or "unknown")),
            ),
            unsafe_allow_html=True,
        )

    _incident_top_name = str(scenario.get("title") or alert.get("name") or "Incident")
    st.markdown(
        f"""
        <div style="margin-bottom:10px;">
            <div style="font-size:1.45rem;font-weight:800;color:#0f172a;line-height:1.2;">
                {html.escape(_incident_top_name)}
            </div>
            <div style="font-size:0.82rem;color:#64748b;margin-top:4px;">
                Incident <b style="color:#334155;">{html.escape(str(incident.get('id', '-')))}</b>
                &nbsp;|&nbsp; Service <b style="color:#334155;">{html.escape(str(alert.get('service', 'N/A')))}</b>
                &nbsp;|&nbsp; Severity <b style="color:#334155;">{html.escape(str(metrics.get('severity', 'unknown')).upper())}</b>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    _h_inc = str(incident.get("id", "-"))
    _h_trace = str(gateway_response.get("trace_id", "-"))
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

user_mgmt_account = st.session_state.get("user_mgmt_me", {})
if isinstance(user_mgmt_account, dict):
    user_mgmt_account = user_mgmt_account.get("user", user_mgmt_account)
else:
    user_mgmt_account = {}
user_mgmt_role_name = str(user_mgmt_account.get("role_name") or st.session_state.get("user_mgmt_user", {}).get("role_name") or "").strip()
home_tabs = st.tabs(home_workspace_options)

with home_tabs[0]:
    if workflow:
        # Severity badge class
        _sev = str(metrics.get("severity", alert.get("severity", "unknown"))).lower()
        _sev_class = {"critical": "kaiops-sev-critical", "high": "kaiops-sev-high",
                      "warning": "kaiops-sev-warning", "info": "kaiops-sev-info"}.get(_sev, "kaiops-sev-info")
        _confidence_pct = f"{float(metrics.get('recommendation_confidence', 0)):.0%}"
        _health = "Restored" if metrics.get("health_restored") else "Not Restored"
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

        # Hero incident header
        st.markdown(
            f"""
            <div class="kaiops-summary-hero">
              <div class="kaiops-summary-hero-alert">
                <span class="kaiops-summary-badge {_sev_class}">{_sev.upper()}</span>
                {html.escape(_alert_display_name)}
              </div>
              <div class="kaiops-summary-hero-meta">
                Alert <b style="color:#cbd5e1">{html.escape(_alert_display_id)}</b>
                &nbsp;|&nbsp; Service <b style="color:#cbd5e1">{html.escape(_summary_service)}</b>
                &nbsp;|&nbsp; Environment <b style="color:#cbd5e1">{html.escape(str(alert.get('environment','N/A')))}</b>
                &nbsp;|&nbsp; Type <b style="color:#cbd5e1">{html.escape(_alert_type)}</b>
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
            table_from_dict(
                {
                    "root_cause": recommendation.get("root_cause") or closure.get("root_cause"),
                    "remediation_status": metrics.get("remediation_status"),
                    "runbook_found": "Yes" if _runbook else "No",
                    "dependencies": _deps_str,
                    "recent_changes": len(_changes),
                    "alerts_cleared": "Yes" if metrics.get("alerts_cleared") else "No",
                }
            )

with home_tabs[1]:
    refresh_alert_snapshots()
    render_alerts_quick_docs_view(
        guidance_query=guidance_query,
        guidance_open=guidance_open,
        guidance_matches=guidance_matches,
        recent_alerts=st.session_state.get("recent_alerts_snapshot", []),
        apply_guidance_selection=apply_guidance_selection,
    )

with home_tabs[2]:
    render_agent_flow_view(
        workflow=workflow,
        render_agent_command_center=render_agent_command_center,
        agent_profiles=AGENT_PROFILES,
        fallback_icon_data_uri=_agent_icon_data_uri("AI", "#64748b"),
    )

with home_tabs[3]:
    render_gateway_safety_view(
        gateway_response=gateway_response,
        gateway=gateway,
        fetch_observability_summary=_fetch_observability_summary_cached,
        fetch_observability_recent=_fetch_observability_recent_cached,
    )

with home_tabs[4]:
    render_message_bus_view(workflow=workflow)

with home_tabs[5]:
    render_finops_view(finops=finops)

with home_tabs[6]:
    render_closed_incidents_view(
        closure=closure,
        remediation=remediation,
        fetch_closed_incidents=_fetch_closed_incidents_cached,
    )

with home_tabs[7]:
    st.markdown("## Incident Metadata Explorer")
    st.caption("Filter the incident projection layer across policy, transport, and operational dimensions.")

    metadata_filters = st.columns(4)
    with metadata_filters[0]:
        risk_filter = st.selectbox(
            "Risk Tier",
            options=["all", "high", "medium", "low"],
            index=0,
            key="incident_metadata_risk_filter",
        )
    with metadata_filters[1]:
        mode_filter = st.selectbox(
            "Execution Mode",
            options=["all", "human-approval", "guided-auto", "auto-execute"],
            index=0,
            key="incident_metadata_mode_filter",
        )
    with metadata_filters[2]:
        transport_filter = st.selectbox(
            "Transport",
            options=["all", "kafka", "rabbitmq"],
            index=0,
            key="incident_metadata_transport_filter",
        )
    with metadata_filters[3]:
        status_filter = st.selectbox(
            "Status",
            options=["all", "open", "investigating", "awaiting_approval", "remediating", "validating", "closed", "failed"],
            index=0,
            key="incident_metadata_status_filter",
        )

    service_filter = st.text_input(
        "Service contains",
        value="",
        key="incident_metadata_service_filter",
        placeholder="payments",
    ).strip()

    filtered_metadata = _fetch_incident_metadata_cached(
        limit=250,
        risk_tier=None if risk_filter == "all" else risk_filter,
        execution_mode=None if mode_filter == "all" else mode_filter,
        transport_provider=None if transport_filter == "all" else transport_filter,
        status=None if status_filter == "all" else status_filter,
        service=service_filter or None,
    )

    metric_row(
        [
            ("Rows", len(filtered_metadata)),
            ("Risk", risk_filter.upper()),
            ("Mode", mode_filter.upper()),
            ("Transport", transport_filter.upper()),
        ]
    )

    if filtered_metadata:
        st.dataframe(
            [
                {
                    "Incident": row.get("incident_id", ""),
                    "Service": row.get("service", ""),
                    "Environment": row.get("environment", ""),
                    "Severity": row.get("severity", ""),
                    "Status": row.get("status", ""),
                    "Risk Tier": row.get("risk_tier", ""),
                    "Execution Mode": row.get("execution_mode", ""),
                    "Requires Approval": "YES" if bool(row.get("requires_approval")) else "NO",
                    "Transport": row.get("transport_provider", ""),
                    "Policy Version": row.get("policy_version", ""),
                    "Latest Event": row.get("latest_event_type", ""),
                    "Updated At": row.get("updated_at", ""),
                }
                for row in filtered_metadata
            ],
            hide_index=True,
            width="stretch",
        )
    else:
        st.info("No incident metadata rows matched the current filters.")
