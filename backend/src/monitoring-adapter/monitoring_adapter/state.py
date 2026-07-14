from __future__ import annotations

import json
import re
import time as _time
from collections import OrderedDict
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import HTTPException

FLOW_CATALOG_FILE = "flows.json"
SCENARIOS_TEXT_FILE = "scenarios.txt"
ONBOARDING_CONNECTIVITY_FILE = "onboarding/connectivity.json"

# Hardcoded scenarios are intentionally empty for now; the text file is the source of truth.
SCENARIOS: dict[str, dict[str, Any]] = {}

# ---------------------------------------------------------------------------
# In-process TTL caches
# ---------------------------------------------------------------------------
_SCENARIOS_CACHE_TTL: float = 60.0
_ONBOARDING_CACHE_TTL: float = 30.0
_scenarios_cache: dict[str, Any] = {}
_scenarios_cache_ts: float = 0.0
_onboarding_cache: dict[str, Any] = {}
_onboarding_cache_ts: float = 0.0


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "flow"


@lru_cache(maxsize=1)
def rag_root_path() -> Path:
    here = Path(__file__).resolve()
    candidates = [here.parents[3] / "rag", Path.cwd() / "backend" / "rag", Path("/app/rag")]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    fallback = candidates[0]
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


@lru_cache(maxsize=1)
def flow_catalog_path() -> Path:
    return rag_root_path() / FLOW_CATALOG_FILE


@lru_cache(maxsize=1)
def scenarios_text_path() -> Path:
    return rag_root_path() / SCENARIOS_TEXT_FILE


@lru_cache(maxsize=1)
def onboarding_connectivity_path() -> Path:
    return rag_root_path() / ONBOARDING_CONNECTIVITY_FILE


def load_onboarding_connectivity() -> dict[str, Any]:
    global _onboarding_cache, _onboarding_cache_ts
    now = _time.monotonic()
    if _onboarding_cache and now - _onboarding_cache_ts < _ONBOARDING_CACHE_TTL:
        return dict(_onboarding_cache)
    path = onboarding_connectivity_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            _onboarding_cache = dict(payload)
            _onboarding_cache_ts = now
            return dict(payload)
    except (OSError, json.JSONDecodeError):
        return {}
    return {}


def save_onboarding_connectivity(payload: dict[str, Any]) -> dict[str, Any]:
    global _onboarding_cache, _onboarding_cache_ts
    path = onboarding_connectivity_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    sanitized = {
        "project": payload.get("project", {}),
        "deployment_mode": payload.get("deployment_mode", "on_prem"),
        "prometheus_url": payload.get("prometheus_url", ""),
        "new_relic_url": payload.get("new_relic_url", ""),
        "datadog_url": payload.get("datadog_url", ""),
        "gcp_project_id": payload.get("gcp_project_id", ""),
        "gcp_region": payload.get("gcp_region", ""),
        "pubsub_topic": payload.get("pubsub_topic", ""),
        "pubsub_subscription": payload.get("pubsub_subscription", ""),
        "vertex_model_armor_enabled": payload.get("vertex_model_armor_enabled", False),
        "vertex_model_armor_template": payload.get("vertex_model_armor_template", ""),
        "user_assignments": payload.get("user_assignments", {}),
        "updated_at": payload.get("updated_at"),
    }
    path.write_text(json.dumps(sanitized, indent=2), encoding="utf-8")
    _onboarding_cache = dict(sanitized)
    _onboarding_cache_ts = _time.monotonic()
    return sanitized


def severity_from_string(value: str | None) -> str:
    normalized = (value or "HIGH").strip().upper()
    mapping = {"CRITICAL": "critical", "HIGH": "high", "WARNING": "warning", "INFO": "info"}
    return mapping.get(normalized, "HIGH")


def default_flow_catalog_entries() -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for scenario_id, scenario in SCENARIOS.items():
        entries.append(
            {
                "id": scenario_id,
                "alert_id": str(scenario.get("alert_id", "")).upper() or scenario_id.upper(),
                "alert_name": str(scenario.get("alert_name", scenario.get("title", ""))),
                "alert_type": str(scenario.get("alert_type", "")),
                "title": str(scenario.get("title", "")),
                "service": str(scenario.get("service", "")),
                "severity": str(scenario.get("severity", "HIGH")).upper(),
                "recommended_action": str(scenario.get("recommended_action", "")),
                "description": str(scenario.get("description", "")),
                "root_cause": str(scenario.get("root_cause", "")),
                "impact": str(scenario.get("impact", "")),
            }
        )
    return entries


def ensure_flow_catalog_exists() -> list[dict[str, str]]:
    path = flow_catalog_path()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return [item for item in data if isinstance(item, dict)]
        except (OSError, json.JSONDecodeError):
            pass
    entries = default_flow_catalog_entries()
    path.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    return entries


def load_scenarios_from_text_file() -> dict[str, dict[str, Any]]:
    """Load additional alert scenarios from rag/scenarios.txt.

    Expected format (pipe-delimited):
    id|title|source|service|severity|description|root_cause|impact|recommended_action
    """

    path = scenarios_text_path()
    if not path.exists():
        return {}

    scenarios: dict[str, dict[str, Any]] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}

    for line in lines:
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue

        parts = [part.strip() for part in raw.split("|")]
        if len(parts) < 9:
            continue

        if parts[0].lower() in {"id", "flow_id"} and parts[1].lower() == "title":
            continue

        flow_id = slugify(parts[0] or parts[1])
        title = parts[1]
        source = parts[2] or "text-file"
        service = parts[3] or "unknown"
        severity = severity_from_string(parts[4])
        description = parts[5] or f"Observed issue for service {service}"
        root_cause = parts[6] or "Operational change"
        impact = parts[7] or title
        recommended_action = parts[8] or "Investigate issue"

        scenarios[flow_id] = {
            "alert_id": flow_id.upper(),
            "alert_name": title,
            "alert_type": "",
            "title": title,
            "source": source,
            "name": f"{flow_id.replace('-', ' ').title().replace(' ', '')}Alert",
            "service": service,
            "severity": severity,
            "description": description,
            "labels": {
                "cluster": "prod-us-east-1",
                "deployment": service,
                "team": f"{service}-sre",
            },
            "annotations": {"summary": title},
            "root_cause": root_cause,
            "impact": impact,
            "recommended_action": recommended_action,
            "remediation_comment": recommended_action,
        }

    return scenarios


def merged_scenarios() -> dict[str, dict[str, Any]]:
    global _scenarios_cache, _scenarios_cache_ts
    now = _time.monotonic()
    if _scenarios_cache and now - _scenarios_cache_ts < _SCENARIOS_CACHE_TTL:
        return dict(_scenarios_cache)
    scenarios: dict[str, dict[str, Any]] = dict(SCENARIOS)
    scenarios.update(load_scenarios_from_text_file())
    _scenarios_cache.clear()
    _scenarios_cache.update(scenarios)
    _scenarios_cache_ts = _time.monotonic()
    return dict(scenarios)


def list_scenarios() -> list[dict[str, str]]:
    scenarios = merged_scenarios()
    rows = [
        {
            "id": scenario_id,
            "alert_id": scenario.get("alert_id", scenario_id.upper()),
            "alert_name": scenario.get("alert_name", scenario.get("title", "")),
            "alert_type": scenario.get("alert_type", ""),
            "title": scenario.get("title", ""),
            "service": scenario.get("service", ""),
            "severity": str(scenario.get("severity", "HIGH")).upper(),
            "recommended_action": scenario.get("recommended_action", ""),
        }
        for scenario_id, scenario in scenarios.items()
    ]
    return sorted(rows, key=lambda item: (str(item.get("service", "")).lower(), str(item.get("title", "")).lower()))


def scenario_source_rows() -> list[dict[str, str]]:
    """Return each merged scenario with an origin marker.

    Merge precedence is text file > hardcoded defaults.
    """

    hardcoded_ids = set(SCENARIOS.keys())
    text_ids = set(load_scenarios_from_text_file().keys())

    rows: list[dict[str, str]] = []
    for scenario_id, scenario in sorted(merged_scenarios().items(), key=lambda kv: kv[0]):
        if scenario_id in text_ids:
            origin = "text-file"
        elif scenario_id in hardcoded_ids:
            origin = "hardcoded"
        else:
            origin = "derived"
        rows.append(
            {
                "scenario_id": scenario_id,
                "title": str(scenario.get("title", "")),
                "service": str(scenario.get("service", "")),
                "origin": origin,
                "severity": str(scenario.get("severity", "HIGH")).upper(),
                "recommended_action": str(scenario.get("recommended_action", "")),
            }
        )
    return rows


def resolve_flow_id(flow_id: str, scenarios: dict[str, dict[str, Any]]) -> str:
    if flow_id in scenarios:
        return flow_id
    if "payment-latency" in scenarios:
        return "payment-latency"
    if scenarios:
        return next(iter(scenarios))
    raise HTTPException(status_code=500, detail="No alert scenarios configured. Add entries to rag/scenarios.txt")
