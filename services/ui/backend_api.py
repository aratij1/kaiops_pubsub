from __future__ import annotations

import os
import time
from typing import Any

import httpx
import streamlit as st

GATEWAY_BASE = os.getenv("API_GATEWAY_URL", "http://localhost:8010")
MONITORING_ADAPTER_BASE = os.getenv("MONITORING_ADAPTER_URL", "http://localhost:8001")
UI_REQUEST_TIMEOUT_SECONDS = float(os.getenv("UI_REQUEST_TIMEOUT_SECONDS", "240"))
HIDE_LEGACY_MYSQL_ALERTS = os.getenv("HIDE_LEGACY_MYSQL_ALERTS", "false").strip().lower() in {"1", "true", "yes", "on"}


def _is_legacy_mysql_alert(row: dict[str, Any]) -> bool:
    source = str(row.get("source") or "").strip().lower()
    service = str(row.get("service") or "").strip().lower()
    name = str(row.get("name") or row.get("alert_name") or row.get("title") or "").strip().lower()

    if "mysql-monitor" in source or source == "mysql":
        return True
    if service == "mysql":
        return True
    if name.startswith("mysql"):
        return True
    return False


def _filter_legacy_mysql_alerts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not HIDE_LEGACY_MYSQL_ALERTS:
        return [row for row in rows if isinstance(row, dict)]
    return [row for row in rows if isinstance(row, dict) and not _is_legacy_mysql_alert(row)]


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


def data_from_gateway(response: dict[str, Any]) -> dict[str, Any]:
    return response.get("data", response)


@st.cache_data(ttl=300, show_spinner="Loading alert catalog…")
def _fetch_flows_cached() -> list[dict[str, Any]]:
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
        typed_rows = [row for row in rows if isinstance(row, dict)]
        return _filter_legacy_mysql_alerts(typed_rows)
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
        typed_rows = [row for row in rows if isinstance(row, dict)]
        return _filter_legacy_mysql_alerts(typed_rows)
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


@st.cache_data(ttl=15, show_spinner=False)
def _fetch_observability_summary_cached() -> dict[str, Any]:
    try:
        with httpx.Client(timeout=8.0) as client:
            resp = client.get(f"{GATEWAY_BASE}/observability/summary")
            resp.raise_for_status()
            return resp.json()
    except Exception:
        return {}


@st.cache_data(ttl=10, show_spinner=False)
def _fetch_observability_recent_cached() -> dict[str, Any]:
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


@st.cache_data(ttl=12, show_spinner=False)
def _fetch_incident_metadata_cached(
    limit: int = 200,
    risk_tier: str | None = None,
    execution_mode: str | None = None,
    transport_provider: str | None = None,
    status: str | None = None,
    service: str | None = None,
) -> list[dict[str, Any]]:
    params: dict[str, str] = {"limit": str(max(1, int(limit)))}
    if risk_tier:
        params["risk_tier"] = str(risk_tier)
    if execution_mode:
        params["execution_mode"] = str(execution_mode)
    if transport_provider:
        params["transport_provider"] = str(transport_provider)
    if status:
        params["status"] = str(status)
    if service:
        params["service"] = str(service)

    try:
        with httpx.Client(timeout=8.0) as client:
            resp = client.get(f"{GATEWAY_BASE}/incidents/metadata", params=params)
            resp.raise_for_status()
            payload = resp.json()
        inner = payload.get("data", payload)
        rows = inner.get("rows", []) if isinstance(inner, dict) else []
        return [row for row in rows if isinstance(row, dict)]
    except Exception:
        return []
