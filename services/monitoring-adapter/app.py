from __future__ import annotations
import asyncio
from collections import deque
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from time import perf_counter
from typing import Any, Literal
from urllib.parse import urlparse
from uuid import UUID

from common.config import get_settings
from common.database import create_engine, create_schema, create_session_factory
from common.event_publishers import build_agent_event_contract, build_event_envelope
from common.logging import get_logger
from common.models import (
    Alert,
    AlertSeverity,
    Incident,
    IncidentStatus,
    Approval,
    ApprovalDecision,
    Recommendation,
    RemediationAction,
    RemediationStatus,
    ResolutionReport,
)
from common.repository import IncidentRepository
from common.service import create_app
from common.telemetry import EVENT_CONTRACTS_EMITTED, EVENT_PUBLISH_LATENCY
from common.topics import RAW_ALERTS
from common.prompts import PROMPT_SUMMARIZE_RCA
import httpx
from fastapi import Body, Header, HTTPException
from pydantic import BaseModel, Field, model_validator
from monitoring_adapter.state import (
    FLOW_CATALOG_FILE,
    ONBOARDING_CONNECTIVITY_FILE,
    SCENARIOS,
    SCENARIOS_TEXT_FILE,
    default_flow_catalog_entries,
    ensure_flow_catalog_exists,
    flow_catalog_path,
    list_scenarios,
    load_onboarding_connectivity,
    load_scenarios_from_text_file,
    merged_scenarios,
    onboarding_connectivity_path,
    rag_root_path,
    resolve_flow_id,
    save_onboarding_connectivity,
    scenario_source_rows,
    scenarios_text_path,
    severity_from_string,
    slugify,
)
from monitoring_adapter.onboarding_pipelines import (
    ExistingRulePipelineRequest,
    NewRuleOnboardingRequest,
    build_prometheus_rules_yaml,
    capabilities_catalog,
    find_pipeline_rows,
    run_existing_rule_pipeline,
    run_new_rule_pipeline,
)

ALERT_BODY = Body(...)

settings = get_settings()
settings.service_name = "monitoring-adapter"
logger = get_logger(__name__)
RECENT_ALERTS: deque[dict[str, Any]] = deque(maxlen=200)
# Fallback only for deployments without database-backed workflow state.
PENDING_WORKFLOWS: dict[str, dict[str, Any]] = {}
CLOSED_INCIDENTS: deque[dict[str, Any]] = deque(maxlen=500)
LANDING_PAD_INPUT_DIR = Path(os.getenv("LANDING_PAD_INPUT_DIR", "/app/ingested_alerts/input"))
WORKER_FAILURE_COUNTS: dict[str, int] = {
    "incident_projection_worker": 0,
}
WORKER_FAILURE_THRESHOLD = max(1, int(os.getenv("WORKER_FAILURE_THRESHOLD", "5") or 5))
_ALLOWED_PROJECT_ENVIRONMENTS = {"dev", "staging", "prod"}
_ALLOWED_ONBOARDING_PROVIDERS = {"prometheus", "new_relic", "datadog"}
_ALLOWED_ACTIVE_PROVIDERS = {"prometheus", "new_relic", "datadog", "pubsub"}
_ALLOWED_DEPLOYMENT_MODES = {"on_prem", "gcp_cloud"}
ONBOARDING_RULE_EVENTS = "onboarding-rule-events"


def _persist_alert_to_landing_pad(mapped_payload: dict[str, Any], raw_alert: dict[str, Any]) -> str | None:
    try:
        LANDING_PAD_INPUT_DIR.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        alert_name = slugify(str(mapped_payload.get("name") or "prometheus-alert"))
        labels = mapped_payload.get("labels", {}) if isinstance(mapped_payload.get("labels"), dict) else {}
        fingerprint = str(labels.get("alert_fingerprint") or "no-fingerprint").strip() or "no-fingerprint"
        safe_fingerprint = re.sub(r"[^a-zA-Z0-9_-]", "-", fingerprint)[:24]
        file_name = f"{now.strftime('%Y%m%dT%H%M%S%fZ')}_{alert_name}_{safe_fingerprint}.json"
        out_path = LANDING_PAD_INPUT_DIR / file_name
        payload = {
            "received_at": now.isoformat(),
            "source": "prometheus-alertmanager",
            "alert": mapped_payload,
            "raw": raw_alert,
        }
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return str(out_path)
    except Exception:
        logger.exception("failed to persist alert to landing pad input")
        return None


class OnboardingProviderStatus(BaseModel):
    ok: bool = False
    message: str = ""


class OnboardingProject(BaseModel):
    name: str
    owner_team: str
    environment: str
    region: str

    @model_validator(mode="after")
    def _validate_project(self) -> "OnboardingProject":
        self.name = str(self.name or "").strip()
        self.owner_team = str(self.owner_team or "").strip()
        self.environment = str(self.environment or "").strip().lower()
        self.region = str(self.region or "").strip()
        if not self.name:
            raise ValueError("project.name is required")
        if not self.owner_team:
            raise ValueError("project.owner_team is required")
        if self.environment not in _ALLOWED_PROJECT_ENVIRONMENTS:
            raise ValueError("project.environment must be one of dev, staging, prod")
        if not self.region:
            raise ValueError("project.region is required")
        return self


class OnboardingConnectivityPayload(BaseModel):
    project: OnboardingProject
    deployment_mode: str = "on_prem"
    prometheus_url: str = ""
    new_relic_url: str = ""
    datadog_url: str = ""
    gcp_project_id: str = ""
    gcp_region: str = ""
    pubsub_topic: str = ""
    pubsub_subscription: str = ""
    vertex_model_armor_enabled: bool = False
    vertex_model_armor_template: str = ""
    user_assignments: dict[str, list[str]] = Field(default_factory=dict)
    provider_statuses: dict[str, OnboardingProviderStatus] = Field(default_factory=dict)
    active_provider: str | None = None
    test_status: bool | None = None
    test_message: str | None = None
    tested_at: str | None = None
    updated_at: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_raw_payload(cls, raw: Any) -> Any:
        if not isinstance(raw, dict):
            raise ValueError("Invalid onboarding payload")

        normalized = dict(raw)

        statuses_raw = normalized.get("provider_statuses", {})
        if statuses_raw is None:
            statuses_raw = {}
        if not isinstance(statuses_raw, dict):
            raise ValueError("provider_statuses must be an object")
        provider_statuses: dict[str, Any] = {}
        for provider_name, status in statuses_raw.items():
            provider = str(provider_name or "").strip().lower().replace(" ", "_")
            if provider not in _ALLOWED_ONBOARDING_PROVIDERS:
                continue
            if not isinstance(status, dict):
                raise ValueError(f"provider_statuses.{provider} must be an object")
            provider_statuses[provider] = {
                "ok": bool(status.get("ok", False)),
                "message": str(status.get("message", "")).strip(),
            }
        normalized["provider_statuses"] = provider_statuses

        assignments_raw = normalized.get("user_assignments", {})
        if assignments_raw is None:
            assignments_raw = {}
        if not isinstance(assignments_raw, dict):
            raise ValueError("user_assignments must be an object")
        user_assignments: dict[str, list[str]] = {}
        for username, projects in assignments_raw.items():
            normalized_user = str(username or "").strip()
            if not normalized_user:
                continue
            if not isinstance(projects, list):
                raise ValueError(f"user_assignments.{normalized_user} must be a list")
            normalized_projects = [str(item or "").strip() for item in projects if str(item or "").strip()]
            user_assignments[normalized_user] = list(dict.fromkeys(normalized_projects))
        normalized["user_assignments"] = user_assignments

        deployment_mode = str(normalized.get("deployment_mode", "on_prem")).strip().lower().replace("-", "_")
        normalized["deployment_mode"] = deployment_mode or "on_prem"

        normalized["gcp_project_id"] = str(normalized.get("gcp_project_id", "")).strip()
        normalized["gcp_region"] = str(normalized.get("gcp_region", "")).strip()
        normalized["pubsub_topic"] = str(normalized.get("pubsub_topic", "")).strip()
        normalized["pubsub_subscription"] = str(normalized.get("pubsub_subscription", "")).strip()
        normalized["vertex_model_armor_enabled"] = bool(normalized.get("vertex_model_armor_enabled", False))
        normalized["vertex_model_armor_template"] = str(normalized.get("vertex_model_armor_template", "")).strip()

        active_provider = str(normalized.get("active_provider", "")).strip().lower().replace(" ", "_")
        normalized["active_provider"] = active_provider or None
        return normalized

    @staticmethod
    def _normalize_endpoint(value: str, field_name: str) -> str:
        endpoint = str(value or "").strip()
        if not endpoint:
            return ""
        parsed = urlparse(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"{field_name} must be a valid http(s) URL")
        return endpoint

    @model_validator(mode="after")
    def _validate_payload(self) -> "OnboardingConnectivityPayload":
        self.deployment_mode = str(self.deployment_mode or "on_prem").strip().lower().replace("-", "_")
        if self.deployment_mode not in _ALLOWED_DEPLOYMENT_MODES:
            raise ValueError("deployment_mode must be one of on_prem, gcp_cloud")

        self.prometheus_url = self._normalize_endpoint(self.prometheus_url, "prometheus_url")
        self.new_relic_url = self._normalize_endpoint(self.new_relic_url, "new_relic_url")
        self.datadog_url = self._normalize_endpoint(self.datadog_url, "datadog_url")
        self.gcp_project_id = str(self.gcp_project_id or "").strip()
        self.gcp_region = str(self.gcp_region or "").strip()
        self.pubsub_topic = str(self.pubsub_topic or "").strip()
        self.pubsub_subscription = str(self.pubsub_subscription or "").strip()
        self.vertex_model_armor_template = str(self.vertex_model_armor_template or "").strip()

        if self.deployment_mode == "gcp_cloud":
            if not self.gcp_project_id:
                raise ValueError("gcp_project_id is required for gcp_cloud mode")

        if self.active_provider and self.active_provider not in _ALLOWED_ACTIVE_PROVIDERS:
            raise ValueError("active_provider must be one of prometheus, new_relic, datadog, pubsub")
        self.test_message = str(self.test_message or "").strip() or None
        self.tested_at = str(self.tested_at or "").strip() or None
        self.updated_at = str(self.updated_at or "").strip() or None
        return self


class OnboardingConnectivitySnapshot(BaseModel):
    project: dict[str, Any] = Field(default_factory=dict)
    deployment_mode: str = "on_prem"
    prometheus_url: str = ""
    new_relic_url: str = ""
    datadog_url: str = ""
    gcp_project_id: str = ""
    gcp_region: str = ""
    pubsub_topic: str = ""
    pubsub_subscription: str = ""
    vertex_model_armor_enabled: bool = False
    vertex_model_armor_template: str = ""
    user_assignments: dict[str, list[str]] = Field(default_factory=dict)
    updated_at: str | None = None


class OnboardingConnectivityResponse(BaseModel):
    connectivity: OnboardingConnectivitySnapshot


class OnboardingStateResponse(BaseModel):
    rows: list[dict[str, Any]] = Field(default_factory=list)


class OnboardingCompletePayload(BaseModel):
    connectivity: OnboardingConnectivityPayload
    project_mode: Literal["new", "existing"] = "existing"
    onboarding_path: Literal["existing_monitoring", "setup_monitoring"] = "existing_monitoring"
    start_rules_onboarding: bool = False
    plain_language_requirements: list[str] = Field(default_factory=list)
    selected_monitoring_tool: str | None = None
    generate_documents: bool = True
    include_smoke_test_alert: bool = True

    @model_validator(mode="before")
    @classmethod
    def _normalize_raw_payload(cls, raw: Any) -> Any:
        if not isinstance(raw, dict):
            raise ValueError("Invalid onboarding completion payload")
        normalized = dict(raw)
        requirements_raw = normalized.get("plain_language_requirements", [])
        if isinstance(requirements_raw, str):
            requirements = [line.strip() for line in requirements_raw.splitlines() if line.strip()]
        elif isinstance(requirements_raw, list):
            requirements = [str(item or "").strip() for item in requirements_raw if str(item or "").strip()]
        else:
            raise ValueError("plain_language_requirements must be a list or newline-delimited string")
        normalized["plain_language_requirements"] = requirements
        selected_tool = str(normalized.get("selected_monitoring_tool") or "").strip().lower().replace(" ", "_")
        normalized["selected_monitoring_tool"] = selected_tool or None
        onboarding_path = str(normalized.get("onboarding_path") or "existing_monitoring").strip().lower()
        normalized["onboarding_path"] = onboarding_path or "existing_monitoring"
        normalized["generate_documents"] = bool(normalized.get("generate_documents", True))
        normalized["include_smoke_test_alert"] = bool(normalized.get("include_smoke_test_alert", True))
        return normalized

    @model_validator(mode="after")
    def _validate_payload(self) -> "OnboardingCompletePayload":
        if self.selected_monitoring_tool and self.selected_monitoring_tool not in _ALLOWED_ONBOARDING_PROVIDERS:
            raise ValueError("selected_monitoring_tool must be one of prometheus, new_relic, datadog")
        if self.onboarding_path == "setup_monitoring" and not self.plain_language_requirements:
            raise ValueError("plain_language_requirements are required when start_rules_onboarding is true")
        return self


OnboardingProject.model_rebuild()
OnboardingConnectivityPayload.model_rebuild()
OnboardingConnectivitySnapshot.model_rebuild()
OnboardingConnectivityResponse.model_rebuild()
OnboardingStateResponse.model_rebuild()
OnboardingCompletePayload.model_rebuild()


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _record_worker_failure(worker_name: str, exc: Exception) -> None:
    current = int(WORKER_FAILURE_COUNTS.get(worker_name, 0) or 0)
    WORKER_FAILURE_COUNTS[worker_name] = current + 1
    logger.exception(
        "background_worker_failed",
        extra={"worker": worker_name, "failure_count": WORKER_FAILURE_COUNTS[worker_name], "error": str(exc)},
    )


def _record_worker_success(worker_name: str) -> None:
    WORKER_FAILURE_COUNTS[worker_name] = 0


async def _load_pending_workflow_from_db(incident_id: str) -> dict[str, Any] | None:
    session_factory = getattr(app.state, "session_factory", None)
    if not settings.database_enabled or session_factory is None:
        return PENDING_WORKFLOWS.get(str(incident_id))
    async with session_factory() as session:
        repo = IncidentRepository(session)
        return await repo.get_pending_workflow(incident_id)


async def _save_pending_workflow_to_db(
    *, incident_id: str, recommendation_id: str, flow_id: str, trace_id: str | None, payload: dict[str, Any]
) -> None:
    session_factory = getattr(app.state, "session_factory", None)
    if not settings.database_enabled or session_factory is None:
        PENDING_WORKFLOWS[str(incident_id)] = _json_safe(payload)
        return
    async with session_factory() as session:
        repo = IncidentRepository(session)
        await repo.save_pending_workflow(
            incident_id=incident_id,
            recommendation_id=recommendation_id,
            flow_id=flow_id,
            trace_id=trace_id,
            payload=_json_safe(payload),
        )
        await session.commit()


async def _mark_pending_workflow_completed_in_db(incident_id: str, final_payload: dict[str, Any]) -> None:
    session_factory = getattr(app.state, "session_factory", None)
    if not settings.database_enabled or session_factory is None:
        PENDING_WORKFLOWS.pop(str(incident_id), None)
        return
    async with session_factory() as session:
        repo = IncidentRepository(session)
        await repo.mark_pending_workflow_completed(incident_id, _json_safe(final_payload))
        await session.commit()


def _build_local_metadata_envelope(
    *,
    event_type: str,
    incident: dict[str, Any],
    alert: dict[str, Any],
    decision: dict[str, Any],
    status: str,
    payload: dict[str, Any],
    confidence: float | None = None,
    model_provider: str | None = None,
    model_name: str | None = None,
    fallback_reason: str | None = None,
    transport_provider: str | None = None,
) -> dict[str, Any]:
    incident_id = str(incident.get("id") or "").strip()
    alert_id = str(alert.get("id") or "").strip()
    trace_id = str(incident.get("trace_id") or alert.get("trace_id") or "").strip()
    service = str(incident.get("service") or alert.get("service") or "unknown").strip() or "unknown"
    environment = str(incident.get("environment") or alert.get("environment") or "prod").strip() or "prod"
    severity = str(incident.get("severity") or alert.get("severity") or "warning").strip().lower()
    correlation_id = str(alert.get("correlation_id") or "").strip() or None
    provider = str(transport_provider or decision.get("message_bus_provider") or "rabbitmq").strip().lower() or "rabbitmq"

    return build_event_envelope(
        event_type=event_type,
        identity={
            "incident_id": incident_id,
            "alert_id": alert_id or None,
            "trace_id": trace_id,
            "correlation_id": correlation_id,
            "causation_id": None,
            "parent_event_id": None,
        },
        scope={
            "tenant_id": "default",
            "service": service,
            "environment": environment,
            "region": None,
            "team": None,
        },
        state={
            "severity": severity,
            "status": str(status or "unknown").strip().lower() or "unknown",
            "owner": None,
        },
        policy={
            "risk_tier": str(decision.get("risk_tier") or "unknown").strip().lower(),
            "execution_mode": str(decision.get("execution_mode") or "unknown").strip().lower(),
            "requires_approval": bool(decision.get("requires_approval", False)),
            "policy_version": str(decision.get("policy_version") or "policy-v1"),
            "policy_reason": str(decision.get("policy_reason") or ""),
        },
        ai={
            "confidence": confidence,
            "model_provider": model_provider,
            "model_name": model_name,
            "fallback_reason": fallback_reason,
        },
        transport={
            "provider": provider,
            "channel": "local-workflow",
            "partition": None,
            "offset": None,
            "delivery_tag": None,
        },
        idempotency={
            "idempotency_key": f"{event_type}:{incident_id}",
            "fingerprint": correlation_id,
        },
        payload=payload,
    )

INCIDENT_PROJECTION_WORKER_ENABLED = str(
    os.getenv("INCIDENT_PROJECTION_WORKER_ENABLED", "true")
).strip().lower() in {"1", "true", "yes", "on"}
INCIDENT_PROJECTION_INTERVAL_SECONDS = max(
    5.0,
    float(os.getenv("INCIDENT_PROJECTION_INTERVAL_SECONDS", "15") or 15),
)
async def _incident_projection_worker() -> None:
    stop_event = app.state.monitoring_adapter_stop_event
    while not stop_event.is_set():
        try:
            if settings.database_enabled and getattr(app.state, "session_factory", None) is not None:
                async with app.state.session_factory() as session:
                    repo = IncidentRepository(session)
                    await repo.project_recent_incident_events(limit=800)
                    await session.commit()
            _record_worker_success("incident_projection_worker")
        except Exception as exc:
            _record_worker_failure("incident_projection_worker", exc)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=float(INCIDENT_PROJECTION_INTERVAL_SECONDS))
        except asyncio.TimeoutError:
            continue


async def _on_startup(_: Any) -> None:
    app.state.monitoring_adapter_stop_event = asyncio.Event()
    if INCIDENT_PROJECTION_WORKER_ENABLED:
        app.state.incident_projection_task = asyncio.create_task(_incident_projection_worker())


async def _on_shutdown(_: Any) -> None:
    stop_event = getattr(app.state, "monitoring_adapter_stop_event", None)
    if stop_event is not None:
        stop_event.set()
    projection_task = getattr(app.state, "incident_projection_task", None)
    if projection_task is not None:
        projection_task.cancel()
        try:
            await projection_task
        except asyncio.CancelledError:
            pass


app = create_app(
    title="KaiMS Monitoring Adapter",
    settings=settings,
    startup=_on_startup,
    shutdown=_on_shutdown,
)

def _ensure_workflow_import_paths() -> None:
    services_root = Path(__file__).resolve().parents[1]
    for relative_path in (
        "common",
        "alert-intelligence",
        "context-agent",
        "model-router",
        "orchestrator",
        "resolution-agent",
        "remediation-engine",
        "closure-service",
        "approval-service",
    ):
        candidate = str(services_root / relative_path)
        if candidate not in sys.path:
            sys.path.insert(0, candidate)


def build_sample_alert(flow_id: str = "payment-latency", trace_id: str | None = None) -> Alert:
    scenarios = merged_scenarios()
    scenario = scenarios.get(flow_id, scenarios["payment-latency"])
    return Alert(
        source=scenario["source"],
        name=str(scenario.get("alert_name") or scenario["name"]),
        service=scenario["service"],
        severity=AlertSeverity(severity_from_string(str(scenario["severity"]))),
        description=scenario["description"],
        labels=scenario["labels"],
        annotations=scenario["annotations"],
        trace_id=trace_id,
    )


def build_payment_latency_alert(trace_id: str | None = None) -> Alert:
    return build_sample_alert("payment-latency", trace_id)


def _normalize_project_name(project: dict[str, Any]) -> str:
    project_name = str(project.get("name", "")).strip()
    return project_name or "untitled-project"


def _normalize_provider_name(provider_name: str) -> str:
    return provider_name.strip().lower().replace(" ", "_")


def _select_monitoring_tool(connectivity: OnboardingConnectivityPayload, preferred: str | None = None) -> str:
    preferred_tool = _normalize_provider_name(preferred or "") if preferred else ""
    if preferred_tool in _ALLOWED_ONBOARDING_PROVIDERS:
        return preferred_tool
    active_provider = _normalize_provider_name(str(connectivity.active_provider or ""))
    if active_provider in _ALLOWED_ONBOARDING_PROVIDERS:
        return active_provider
    if connectivity.prometheus_url:
        return "prometheus"
    if connectivity.new_relic_url:
        return "new_relic"
    if connectivity.datadog_url:
        return "datadog"
    return "prometheus"


def _selected_tool_url(connectivity: OnboardingConnectivityPayload, selected_tool: str) -> str:
    if selected_tool == "new_relic":
        return str(connectivity.new_relic_url or "").strip()
    if selected_tool == "datadog":
        return str(connectivity.datadog_url or "").strip()
    return str(connectivity.prometheus_url or "").strip()


def _build_onboarding_rule_seed(connectivity: OnboardingConnectivityPayload, selected_tool: str) -> dict[str, Any]:
    project = connectivity.project
    return {
        "project_name": str(project.name or "").strip(),
        "description": "Monitoring onboarding workflow",
        "business_unit": "",
        "environment": str(project.environment or "prod").strip().lower(),
        "criticality": "high",
        "sla": "",
        "support_team": str(project.owner_team or "").strip(),
        "business_owner": "",
        "technical_owner": "",
        "technology_stack": [],
        "cloud_provider": "gcp" if connectivity.deployment_mode == "gcp_cloud" else "on_prem",
        "region": str(project.region or "").strip(),
        "monitoring_platforms": [selected_tool],
        "notification_platforms": ["slack", "teams", "pagerduty"],
    }


def _build_landing_pad_summary(connectivity: OnboardingConnectivityPayload, selected_tool: str) -> dict[str, Any]:
    project_name = str(connectivity.project.name or "").strip()
    configured_endpoint = _selected_tool_url(connectivity, selected_tool)
    return {
        "ready": True,
        "project_name": project_name,
        "selected_monitoring_tool": selected_tool,
        "configured_monitoring_endpoint": configured_endpoint,
        "landing_pad_endpoint": "/alerts/alertmanager",
        "message": (
            "Send alerts from your monitoring platform to /alerts/alertmanager. "
            "Landing pad ingestion will trigger the downstream KaiMS workflow."
        ),
    }


def _build_onboarding_rag_documents(
    *,
    connectivity: OnboardingConnectivityPayload,
    selected_tool: str,
    workflow_result: dict[str, Any],
    requirements: list[str],
) -> list[dict[str, Any]]:
    project_name = str(connectivity.project.name or "").strip()
    owner_team = str(connectivity.project.owner_team or "").strip() or "platform-ops"
    environment = str(connectivity.project.environment or "prod").strip()
    workflow_id = str(workflow_result.get("workflow_id") or "").strip()
    onboarding_id = str(workflow_result.get("onboarding_id") or "").strip()
    trace_id = str(workflow_result.get("trace_id") or "").strip()
    generated_rules = workflow_result.get("generated_rules", []) if isinstance(workflow_result.get("generated_rules"), list) else []
    rules_summary = "\n".join(
        f"- {item.get('name', 'unnamed-rule')} ({item.get('platform', selected_tool)}): {item.get('expression', '')}" for item in generated_rules[:15]
    ) or "- Rules generated by onboarding pipeline"
    requirements_summary = "\n".join(f"- {line}" for line in requirements) or "- Plain-language requirement provided"
    source_ref = f"workflow:{workflow_id}" if workflow_id else "workflow:new-rule-onboarding"

    shared_metadata = {
        "project_name": project_name,
        "selected_monitoring_tool": selected_tool,
        "workflow_id": workflow_id,
        "onboarding_id": onboarding_id,
        "trace_id": trace_id,
        "owner_team": owner_team,
    }

    incident_doc = {
        "kind": "incident",
        "alert_id": f"{project_name}-rule-onboarding",
        "alert_type": "monitoring-rule-onboarding",
        "severity": "high",
        "title": f"{project_name} Monitoring Rule Onboarding",
        "summary": f"Plain-language monitoring requirements were converted to {selected_tool} rules.",
        "content": (
            f"Project {project_name} onboarding completed in {environment}.\n"
            f"Selected tool: {selected_tool}.\n"
            f"Requirements:\n{requirements_summary}\n\nGenerated rules:\n{rules_summary}"
        ),
        "services": [project_name],
        "deployment": environment,
        "recommended_action": "Review generated rules and approve production deployment.",
        "source_system": "monitoring-adapter",
        "source_ref": source_ref,
        "metadata": {k: str(v or "") for k, v in shared_metadata.items()},
    }

    runbook_doc = {
        "kind": "runbook",
        "alert_id": f"{project_name}-rule-runbook",
        "alert_type": "rule-operations",
        "severity": "high",
        "title": f"{project_name} Rule Monitoring & Resolution Runbook",
        "summary": "Operational runbook for monitoring generated rules, triage, RCA, and resolution.",
        "content": (
            "1. Verify rule expression output for false positives.\n"
            "2. Validate alert routing and escalation channels.\n"
            "3. Run RCA checklist for noisy or missed alerts.\n"
            "4. Apply threshold or duration tuning and redeploy through workflow editor.\n"
            "5. Confirm health restoration and close incident with audit notes."
        ),
        "services": [project_name],
        "deployment": environment,
        "root_cause": "Threshold drift, metric quality, or dependency changes can cause noisy or delayed alerts.",
        "impact": "Delayed detection and unnecessary incidents for production services.",
        "execution_plan": "Tune rule thresholds, re-run simulation, then promote approved rules.",
        "recommended_action": "Use workflow simulation and governance checks before production push.",
        "source_system": "monitoring-adapter",
        "source_ref": source_ref,
        "metadata": {k: str(v or "") for k, v in shared_metadata.items()},
    }

    dependency_doc = {
        "kind": "dependency",
        "alert_id": f"{project_name}-rule-dependencies",
        "alert_type": "dependency-map",
        "severity": "warning",
        "title": f"{project_name} Rule Dependency & RCA Metadata",
        "summary": "Dependency and metadata baseline for rule monitoring, RCA, and resolution workflows.",
        "content": (
            f"Monitoring tool endpoint: {_selected_tool_url(connectivity, selected_tool) or 'not-provided'}.\n"
            f"Deployment mode: {connectivity.deployment_mode}.\n"
            "Track dependencies for data pipeline, scrape/export health, and notification delivery."
        ),
        "services": [project_name],
        "deployment": environment,
        "dependencies": [selected_tool, "notification-platform", "incident-orchestrator"],
        "source_system": "monitoring-adapter",
        "source_ref": source_ref,
        "metadata": {k: str(v or "") for k, v in shared_metadata.items()},
    }

    change_doc = {
        "kind": "change",
        "alert_id": f"{project_name}-rule-change",
        "alert_type": "rules-change-plan",
        "severity": "warning",
        "title": f"{project_name} Rules Change Record",
        "summary": "Change record for generated monitoring rules and rollout governance.",
        "content": (
            "This change introduces LLM-generated monitoring rules from plain-language requirements.\n"
            "Rollout phases: staging validation, simulation review, governance approval, production deployment."
        ),
        "services": [project_name],
        "deployment": environment,
        "change_id": onboarding_id or workflow_id or f"{project_name}-rule-change",
        "execution_plan": "Deploy by environment with rollback guardrails and post-deploy SLO checks.",
        "source_system": "monitoring-adapter",
        "source_ref": source_ref,
        "metadata": {k: str(v or "") for k, v in shared_metadata.items()},
    }

    return [incident_doc, runbook_doc, dependency_doc, change_doc]


def _prometheus_rules_output_path(project_name: str, workflow_id: str) -> Path:
    safe_project = re.sub(r"[^a-zA-Z0-9_-]", "-", str(project_name or "project").strip()) or "project"
    safe_workflow = re.sub(r"[^a-zA-Z0-9_-]", "-", str(workflow_id or "workflow").strip()) or str(uuid.uuid4())
    primary_output_dir = rag_root_path() / "changes" / "prometheus_rules"

    def _ensure_writable_directory(path: Path) -> None:
        # Handle races and stale filesystem entries (including broken symlinks)
        # so onboarding can always write generated rules.
        for _ in range(3):
            try:
                path.mkdir(parents=True, exist_ok=True)
                return
            except FileExistsError:
                if path.exists() and path.is_dir():
                    return

                if os.path.lexists(path):
                    try:
                        path.unlink()
                    except IsADirectoryError:
                        # Another request may have completed directory creation.
                        if path.exists() and path.is_dir():
                            return
                        raise

                parent = path.parent
                try:
                    parent.mkdir(parents=True, exist_ok=True)
                except FileExistsError:
                    if parent.exists() and parent.is_dir():
                        continue
                    if os.path.lexists(parent):
                        try:
                            parent.unlink()
                        except IsADirectoryError:
                            if parent.exists() and parent.is_dir():
                                continue
                            raise

        # Final attempt after cleanup/retry loop.
        path.mkdir(parents=True, exist_ok=True)

    output_dir = primary_output_dir
    try:
        _ensure_writable_directory(primary_output_dir)
    except Exception:
        logger.exception(
            "prometheus_rules_output_dir_unavailable",
            extra={"primary_output_dir": str(primary_output_dir)},
        )
        fallback_output_dir = Path("/tmp/kaiops/prometheus_rules")
        _ensure_writable_directory(fallback_output_dir)
        output_dir = fallback_output_dir

    return output_dir / f"{safe_project}-{safe_workflow}.yml"


async def _generate_upload_and_test_prometheus_rules(
    *,
    endpoint_url: str,
    project_name: str,
    workflow_id: str,
    generated_rules: list[dict[str, Any]],
    include_smoke_test_alert: bool,
) -> dict[str, Any]:
    yaml_content = build_prometheus_rules_yaml(
        project_name,
        generated_rules,
        include_smoke_test_alert=include_smoke_test_alert,
    )
    output_path = _prometheus_rules_output_path(project_name, workflow_id)
    output_path.write_text(yaml_content, encoding="utf-8")
    expected_group_name = f"{re.sub(r'[^a-zA-Z0-9]+', '-', str(project_name or '').strip().lower()).strip('-') or 'project'}-generated-rules"

    details: dict[str, Any] = {
        "yaml_generated": True,
        "yaml_path": str(output_path),
        "yaml": yaml_content,
        "upload": {
            "attempted": False,
            "ok": False,
            "message": "Prometheus push API is not available; rules are written to local changes directory.",
            "reload_requested": False,
            "reload_ok": False,
        },
        "test": {
            "attempted": False,
            "ok": False,
            "message": "Prometheus endpoint not provided.",
            "loaded_rule_groups": 0,
            "loaded_rules": 0,
            "active_alerts": 0,
        },
        "smoke_test_alert_enabled": include_smoke_test_alert,
    }

    normalized_endpoint = str(endpoint_url or "").strip().rstrip("/")
    if not normalized_endpoint:
        return details

    async with httpx.AsyncClient(timeout=12.0) as client:
        reload_url = f"{normalized_endpoint}/-/reload"
        rules_url = f"{normalized_endpoint}/api/v1/rules"
        alerts_url = f"{normalized_endpoint}/api/v1/alerts"
        details["upload"]["attempted"] = True
        details["upload"]["reload_requested"] = True
        try:
            reload_response = await client.post(reload_url)
            details["upload"]["reload_ok"] = reload_response.status_code < 400
            details["upload"]["message"] = f"Reload endpoint returned HTTP {reload_response.status_code}."
        except Exception as exc:
            details["upload"]["message"] = f"Reload request failed: {exc}"

        details["test"]["attempted"] = True
        try:
            rules_response = await client.get(rules_url)
            body = rules_response.json() if "application/json" in str(rules_response.headers.get("content-type", "")).lower() else {}
            api_status = str(body.get("status") or "").strip().lower() if isinstance(body, dict) else ""
            loaded_group_count = 0
            loaded_rule_count = 0
            if isinstance(body, dict):
                data = body.get("data", {}) if isinstance(body.get("data"), dict) else {}
                groups = data.get("groups", []) if isinstance(data.get("groups"), list) else []
                matching_groups = [
                    group for group in groups
                    if str(group.get("name") or "").strip() == expected_group_name
                ]
                loaded_group_count = len(matching_groups)
                loaded_rule_count = sum(len(group.get("rules", []) or []) for group in matching_groups)

            active_alert_count = 0
            try:
                alerts_response = await client.get(alerts_url)
                alerts_body = alerts_response.json() if "application/json" in str(alerts_response.headers.get("content-type", "")).lower() else {}
                if isinstance(alerts_body, dict):
                    alerts_data = alerts_body.get("data", {}) if isinstance(alerts_body.get("data"), dict) else {}
                    alerts = alerts_data.get("alerts", []) if isinstance(alerts_data.get("alerts"), list) else []
                    active_alert_count = len(
                        [
                            alert
                            for alert in alerts
                            if str((alert.get("labels") or {}).get("project") or "").strip() == expected_group_name.removesuffix("-generated-rules")
                        ]
                    )
            except Exception:
                active_alert_count = 0

            details["test"]["loaded_rule_groups"] = loaded_group_count
            details["test"]["loaded_rules"] = loaded_rule_count
            details["test"]["active_alerts"] = active_alert_count

            rules_api_ok = rules_response.status_code < 400 and api_status in {"", "success"}
            loaded_ok = loaded_rule_count > 0
            details["test"]["ok"] = bool(rules_api_ok and loaded_ok)
            details["upload"]["ok"] = bool(details["upload"].get("reload_ok") and loaded_ok)
            details["test"]["message"] = (
                f"Rules API HTTP {rules_response.status_code}; loaded_groups={loaded_group_count}; "
                f"loaded_rules={loaded_rule_count}; active_alerts={active_alert_count}."
            )
        except Exception as exc:
            details["test"]["message"] = f"Prometheus test request failed: {exc}"
            details["upload"]["ok"] = bool(details["upload"].get("reload_ok", False))

    return details


def _build_onboarding_steps_response(
    *,
    onboarding_path: str,
    project_mode: str,
    start_rules_onboarding: bool,
    requirements: list[str],
    rules_result: dict[str, Any] | None,
    prometheus_result: dict[str, Any] | None,
    rag_documents: list[dict[str, Any]],
    landing_pad_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    uses_setup_flow = str(onboarding_path or "").strip().lower() == "setup_monitoring"
    step_one = {
        "step": 1,
        "title": "Create/Update Project",
        "status": "completed",
        "details": {"project_mode": project_mode},
    }
    step_two = {
        "step": 2,
        "title": "Select Onboarding Path",
        "status": "completed",
        "details": {
            "path": "setup_monitoring" if uses_setup_flow else "existing_monitoring",
            "summary": (
                "Create monitoring rules and configure Prometheus"
                if uses_setup_flow
                else "Use existing monitoring and ingest alerts into landing pad"
            ),
        },
    }
    step_three = {
        "step": 3,
        "title": "Capture Rules In Plain English" if uses_setup_flow else "Configure Landing Pad Ingestion",
        "status": (
            "completed" if (uses_setup_flow and start_rules_onboarding and requirements) else
            ("completed" if not uses_setup_flow else "skipped")
        ),
        "details": {
            "requirements_count": len(requirements) if uses_setup_flow else 0,
            "requirements": requirements if uses_setup_flow else [],
            "landing_pad": landing_pad_summary if not uses_setup_flow else {},
        },
    }
    step_four_status = "skipped"
    step_four_title = "Convert To YAML, Upload In Prometheus, Test" if uses_setup_flow else "Ingest Alerts and Trigger Workflow"
    step_four_details: dict[str, Any] = {
        "message": (
            "Rule conversion and Prometheus upload were skipped."
            if uses_setup_flow
            else "Alert ingestion via landing pad is ready; incoming alerts will trigger downstream workflow."
        ),
        "landing_pad": landing_pad_summary if not uses_setup_flow else {},
    }
    if uses_setup_flow and start_rules_onboarding and rules_result:
        step_four_status = "completed"
        step_four_details = {
            "workflow_id": rules_result.get("workflow_id"),
            "rule_conversion": "completed",
            "prometheus": prometheus_result or {"message": "Prometheus deployment not attempted."},
        }
    if not uses_setup_flow:
        step_four_status = "completed"

    step_five = {
        "step": 5,
        "title": "Generate Monitoring/Troubleshooting/Resolution Docs",
        "status": "completed" if rag_documents else "skipped",
        "details": {
            "generated_document_count": len(rag_documents),
            "documents": rag_documents,
        },
    }
    return [step_one, step_two, step_three, {"step": 4, "title": step_four_title, "status": step_four_status, "details": step_four_details}, step_five]


async def persist_onboarding_connectivity(payload: dict[str, Any]) -> None:
    session_factory = getattr(app.state, "session_factory", None)
    if not settings.database_enabled or session_factory is None:
        return

    project = payload.get("project", {}) if isinstance(payload.get("project"), dict) else {}
    if not isinstance(project, dict):
        project = {}

    project_name = _normalize_project_name(project)
    provider_statuses = payload.get("provider_statuses", {}) if isinstance(payload.get("provider_statuses"), dict) else {}
    connectivity_payload = {
        "deployment_mode": str(payload.get("deployment_mode", "on_prem")).strip().lower().replace("-", "_"),
        "prometheus_url": str(payload.get("prometheus_url", "")).strip(),
        "new_relic_url": str(payload.get("new_relic_url", "")).strip(),
        "datadog_url": str(payload.get("datadog_url", "")).strip(),
        "gcp_project_id": str(payload.get("gcp_project_id", "")).strip(),
        "gcp_region": str(payload.get("gcp_region", "")).strip(),
        "pubsub_topic": str(payload.get("pubsub_topic", "")).strip(),
        "pubsub_subscription": str(payload.get("pubsub_subscription", "")).strip(),
        "vertex_model_armor_enabled": bool(payload.get("vertex_model_armor_enabled", False)),
        "vertex_model_armor_template": str(payload.get("vertex_model_armor_template", "")).strip(),
        "user_assignments": payload.get("user_assignments", {}) if isinstance(payload.get("user_assignments"), dict) else {},
        "updated_at": payload.get("updated_at"),
        "active_provider": _normalize_provider_name(str(payload.get("active_provider", ""))) if payload.get("active_provider") else None,
    }
    selected_provider = _normalize_provider_name(str(payload.get("active_provider", "project")))
    now = datetime.now(timezone.utc)

    async with session_factory() as session:
        repo = IncidentRepository(session)
        await repo.save_onboarding_state(
            project_name=project_name,
            provider_name="project",
            owner_team=str(project.get("owner_team", "")).strip() or None,
            environment=str(project.get("environment", "")).strip() or None,
            region=str(project.get("region", "")).strip() or None,
            endpoint_url=None,
            test_status="saved",
            test_message="Project configuration saved",
            project_payload=project,
            connectivity_payload=connectivity_payload,
            last_tested_at=None,
        )

        for provider_name, endpoint_key in (("prometheus", "prometheus_url"), ("new_relic", "new_relic_url"), ("datadog", "datadog_url")):
            provider_state = provider_statuses.get(provider_name, {}) if isinstance(provider_statuses, dict) else {}
            has_test_result = isinstance(provider_state, dict) and ("ok" in provider_state or "message" in provider_state)
            ok = bool(provider_state.get("ok", False)) if has_test_result else False
            message = None
            if has_test_result:
                message = str(provider_state.get("message", "")).strip() or None
            await repo.save_onboarding_state(
                project_name=project_name,
                provider_name=provider_name,
                owner_team=str(project.get("owner_team", "")).strip() or None,
                environment=str(project.get("environment", "")).strip() or None,
                region=str(project.get("region", "")).strip() or None,
                endpoint_url=str(payload.get(endpoint_key, "")).strip() or None,
                test_status="connected" if ok else ("failed" if has_test_result else None),
                test_message=message,
                project_payload=project,
                connectivity_payload={
                    "provider": provider_name,
                    "endpoint_url": str(payload.get(endpoint_key, "")).strip(),
                    "state": provider_state,
                    "selected_provider": selected_provider,
                    "updated_at": payload.get("updated_at"),
                },
                last_tested_at=now if has_test_result else None,
            )

        await session.commit()


async def persist_onboarding_pipeline_result(result: dict[str, Any]) -> None:
    session_factory = getattr(app.state, "session_factory", None)
    if not settings.database_enabled or session_factory is None:
        return

    project = result.get("project", {}) if isinstance(result.get("project"), dict) else {}
    project_name = _normalize_project_name({"name": project.get("project_name")})
    provider_name = str(result.get("pipeline") or "onboarding_pipeline").strip().lower()

    payload = {
        "workflow_id": result.get("workflow_id"),
        "onboarding_id": result.get("onboarding_id"),
        "project_id": result.get("project_id"),
        "trace_id": result.get("trace_id"),
        "status": result.get("status"),
        "pipeline": result.get("pipeline"),
        "summary": result.get("summary") or result.get("approval_package") or {},
        "event_contract": result.get("event_contract") or {},
        "result": result,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    async with session_factory() as session:
        repo = IncidentRepository(session)
        await repo.save_onboarding_state(
            project_name=project_name,
            provider_name=provider_name,
            owner_team=str(project.get("support_team", "")).strip() or None,
            environment=str(project.get("environment", "")).strip() or None,
            region=str(project.get("region", "")).strip() or None,
            endpoint_url=None,
            test_status=str(result.get("status", "completed")),
            test_message=f"{provider_name} workflow persisted",
            project_payload=project,
            connectivity_payload=payload,
            last_tested_at=datetime.now(timezone.utc),
        )
        await session.commit()


async def publish_onboarding_pipeline_event(result: dict[str, Any]) -> None:
    contract = result.get("event_contract", {}) if isinstance(result.get("event_contract"), dict) else {}
    if not contract:
        return
    try:
        started = perf_counter()
        await app.state.producer.publish(
            ONBOARDING_RULE_EVENTS,
            contract,
            key=str(contract.get("project_id") or "onboarding"),
        )
        EVENT_PUBLISH_LATENCY.labels(settings.service_name, ONBOARDING_RULE_EVENTS, "monitoring-adapter").observe(
            max(0.0, perf_counter() - started)
        )
    except Exception:
        logger.exception("failed to publish onboarding pipeline event")


async def run_local_payment_workflow(
    trace_id: str | None = None,
    flow_id: str = "payment-latency",
    model_router: Any | None = None,
    run_comparison: bool = True,
    auto_approve: bool = True,
) -> dict[str, Any]:
    """Run the agent workflow in-process for local demos with Kafka disabled."""
    _ensure_workflow_import_paths()
    from alert_intelligence import AlertIntelligenceAgent
    from closure_service import ClosureValidationAgent
    from context_agent import ContextIntelligenceAgent
    from model_router import ModelRouter, ModelTask
    from orchestrator import OrchestratorAgent
    from remediation_engine import RemediationEngine
    from resolution_agent import ResolutionIntelligenceAgent

    agent_order = [
        "Alert Intelligence Agent",
        "Orchestrator Agent",
        "Context Intelligence Agent",
        "Resolution Intelligence Agent",
        "Human Approval Layer",
        "Remediation Automation Engine",
        "Closure & Validation",
    ]

    async def persist_step(*operations: Any) -> None:
        session_factory = getattr(app.state, "session_factory", None)
        engine = None
        if not settings.database_enabled:
            return
        if session_factory is None:
            engine = create_engine(settings)
            session_factory = create_session_factory(engine)
            await create_schema(engine)
        try:
            async with session_factory() as session:
                repo = IncidentRepository(session)
                for operation in operations:
                    await operation(repo)
                await session.commit()
        finally:
            if engine is not None:
                await engine.dispose()

    def track_agent_work_operation(
        *,
        incident_id: Any,
        agent_name: str,
        work_item: str,
        status: str,
        sequence: int,
        trace_id: str | None,
        ticket_id: str | None,
        details: dict[str, Any] | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
    ):
        async def _operation(repo: IncidentRepository) -> None:
            await repo.save_agent_work_item(
                incident_id=incident_id,
                agent_name=agent_name,
                work_item=work_item,
                status=status,
                sequence=sequence,
                trace_id=trace_id,
                ticket_id=ticket_id,
                details=_json_safe(details or {}),
                started_at=started_at,
                completed_at=completed_at,
            )

        return _operation

    def track_metadata_event_operation(envelope: dict[str, Any]):
        async def _operation(repo: IncidentRepository) -> None:
            await repo.save_incident_event(_json_safe(envelope))

        return _operation

    scenarios = merged_scenarios()
    resolved_flow_id = resolve_flow_id(flow_id, scenarios)
    scenario = scenarios[resolved_flow_id]
    router = model_router or ModelRouter()
    alert = build_sample_alert(resolved_flow_id, trace_id=trace_id)
    enriched_alert, incident = await AlertIntelligenceAgent().process(alert)
    incident.trace_id = trace_id
    await persist_step(lambda repo: repo.save_alert(enriched_alert), lambda repo: repo.save_incident(incident))
    now = datetime.now(timezone.utc)
    await persist_step(
        *[
            track_agent_work_operation(
                incident_id=incident.id,
                agent_name=agent_name,
                work_item="Assigned to incident workflow",
                status="pending",
                sequence=index,
                trace_id=trace_id,
                ticket_id=incident.ticket_id,
                details={"assigned_by": "orchestrator", "flow_id": flow_id},
                started_at=now,
                completed_at=None,
            )
            for index, agent_name in enumerate(agent_order, start=1)
        ]
    )
    alert_event = {
        "sequence": 1,
        "agent": "Alert Intelligence Agent",
        "action": "Deduplicated, correlated, classified, and enriched alert",
        "input": {
            "flow_id": flow_id,
            "source": alert.source,
            "name": alert.name,
            "service": alert.service,
            "severity": alert.severity.value,
            "description": alert.description,
            "labels": alert.labels,
            "annotations": alert.annotations,
        },
        "decision": f"Severity classified as {enriched_alert.severity}; correlation ID {enriched_alert.correlation_id}",
        "output": "Created incident and enriched alert event",
        "communicates_to": "Orchestrator Agent via enriched-alerts",
        "metrics": {
            "deduplicated_count": enriched_alert.deduplicated_count,
            "metadata_fields": len(enriched_alert.metadata),
        },
    }
    await persist_step(
        track_agent_work_operation(
            incident_id=incident.id,
            agent_name="Alert Intelligence Agent",
            work_item="Deduplicate, correlate, classify, and enrich alert",
            status="completed",
            sequence=1,
            trace_id=trace_id,
            ticket_id=incident.ticket_id,
            details={
                "action": alert_event["action"],
                "input": alert_event["input"],
                "decision": alert_event["decision"],
                "output": alert_event["output"],
                "communicates_to": alert_event["communicates_to"],
                "metrics": alert_event["metrics"],
            },
            started_at=now,
            completed_at=datetime.now(timezone.utc),
        )
    )
    context_task = asyncio.create_task(ContextIntelligenceAgent().collect(enriched_alert, incident))
    decision_task = asyncio.create_task(OrchestratorAgent().decide_workflow_async(enriched_alert, incident))
    context, decision = await asyncio.gather(context_task, decision_task)
    context.trace_id = trace_id
    orchestrator_event = {
        "sequence": 2,
        "agent": "Orchestrator Agent",
        "action": "Selected incident workflow and downstream agents",
        "input": {
            "incident_id": incident.id,
            "service": incident.service,
            "severity": incident.severity.value,
            "title": incident.title,
            "workflow": decision.workflow,
        },
        "decision": decision.__dict__,
        "workflow": decision.workflow,
        "output": (
            f"Workflow {decision.workflow}; next action: {decision.next_action}; "
            f"approval required: {decision.requires_approval}; message bus: {decision.message_bus_provider}"
        ),
        "communicates_to": ", ".join(decision.downstream_agents),
        "metrics": {
            "downstream_agents": len(decision.downstream_agents),
            "requires_approval": decision.requires_approval,
            "message_bus_provider": decision.message_bus_provider,
            "stream_count": decision.stream_count,
            "stream_threshold": decision.stream_threshold,
        },
    }
    await persist_step(
        track_agent_work_operation(
            incident_id=incident.id,
            agent_name="Orchestrator Agent",
            work_item="Select workflow and downstream agents",
            status="completed",
            sequence=2,
            trace_id=trace_id,
            ticket_id=incident.ticket_id,
            details={
                "action": orchestrator_event["action"],
                "input": orchestrator_event["input"],
                "decision": orchestrator_event["decision"],
                "output": orchestrator_event["output"],
                "communicates_to": orchestrator_event["communicates_to"],
                "metrics": orchestrator_event["metrics"],
            },
            started_at=now,
            completed_at=datetime.now(timezone.utc),
        )
    )
    orchestration_envelope = _build_local_metadata_envelope(
        event_type="incident.workflow.selected",
        incident=incident.model_dump(mode="json"),
        alert=enriched_alert.model_dump(mode="json"),
        decision=decision.__dict__,
        status="investigating",
        payload={
            "workflow": decision.workflow,
            "next_action": decision.next_action,
            "downstream_agents": decision.downstream_agents,
        },
        transport_provider=decision.message_bus_provider,
    )
    await persist_step(track_metadata_event_operation(orchestration_envelope))
    context_event = {
        "sequence": 3,
        "agent": "Context Intelligence Agent",
        "action": "Collected operational context and RAG evidence",
        "input": {
            "incident_id": incident.id,
            "alert_service": enriched_alert.service,
            "alert_severity": enriched_alert.severity.value,
            "deployment_label": enriched_alert.labels.get("deployment"),
            "workflow": decision.workflow,
            "trace_id": trace_id,
        },
        "decision": f"Most relevant deployment: {context.deployment}",
        "output": "Context object with runbook, related incidents, dependencies, metrics, and changes",
        "communicates_to": "Resolution Intelligence Agent via context-events",
        "metrics": {
            "related_incidents": len(context.related_incidents),
            "dependency_services": len(context.dependency_services),
            "recent_changes": len(context.recent_changes),
            "runbook_found": bool(context.runbook),
        },
    }
    await persist_step(
        track_agent_work_operation(
            incident_id=incident.id,
            agent_name="Context Intelligence Agent",
            work_item="Collect context and RAG evidence",
            status="completed",
            sequence=3,
            trace_id=trace_id,
            ticket_id=incident.ticket_id,
            details={
                "action": context_event["action"],
                "input": context_event["input"],
                "decision": context_event["decision"],
                "output": context_event["output"],
                "communicates_to": context_event["communicates_to"],
                "metrics": context_event["metrics"],
            },
            started_at=now,
            completed_at=datetime.now(timezone.utc),
        )
    )
    model_errors: list[dict[str, str]] = []
    try:
        recommendation = await ResolutionIntelligenceAgent(model_router=router).resolve(context)
    except Exception as exc:
        recommendation = Recommendation(
            incident_id=incident.id,
            root_cause=scenario["root_cause"],
            confidence=0.72,
            impact=scenario["impact"],
            recommended_action=scenario["recommended_action"],
            severity=enriched_alert.severity,
            rationale=(
                "RCA model route failed; recommendation is based on retrieved RAG context "
                "and scenario evidence. See FinOps errors for provider details."
            ),
            commands=[],
            risk="high" if enriched_alert.severity == AlertSeverity.CRITICAL else "medium",
        )
        model_errors.append(
            {
                "provider": "router",
                "task": "resolution",
                "prompt": "Resolution Intelligence Agent LangGraph workflow",
                "payload": str({"alert": enriched_alert.description, "context": context.metadata}),
                "error": str(exc),
            }
        )
    recommendation.root_cause = scenario["root_cause"]
    recommendation.impact = scenario["impact"]
    recommendation.recommended_action = scenario["recommended_action"]
    recommendation.rationale = (
        f"Scenario evidence links {scenario['root_cause']} to {scenario['impact']}; "
        f"recommended action is {scenario['recommended_action']}."
    )
    recommendation.trace_id = trace_id
    recommendation.metadata["policy_version"] = decision.policy_version
    recommendation.metadata["policy_reason"] = decision.policy_reason
    recommendation.metadata["orchestration_decision"] = {
        "workflow": decision.workflow,
        "requires_approval": decision.requires_approval,
        "risk_tier": decision.risk_tier,
        "execution_mode": decision.execution_mode,
        "policy_version": decision.policy_version,
        "policy_reason": decision.policy_reason,
        "message_bus_provider": decision.message_bus_provider,
        "stream_count": decision.stream_count,
        "stream_threshold": decision.stream_threshold,
    }
    await persist_step(lambda repo: repo.save_recommendation_as_audit(recommendation))
    model_usage = list(recommendation.metadata.get("model_usage", []))
    model_calls = list(recommendation.metadata.get("model_calls", []))
    if run_comparison:
        comparison_payload = {
            "service": enriched_alert.service,
            "incident": incident.title,
            "root_cause": scenario["root_cause"],
            "recommended_action": scenario["recommended_action"],
        }
        comparison_prompt = PROMPT_SUMMARIZE_RCA
        comparison_candidates = ["gpt-5", "gpt-4o"]
        if settings.local_llm_enabled:
            comparison_candidates.append("local-llama")

        comparison_calls = [
            (provider_name, ModelTask.SUMMARIZATION, comparison_prompt)
            for provider_name in comparison_candidates
            if provider_name in router.providers
        ]
        comparison_results = await asyncio.gather(
            *[
                router.route_provider(
                    provider_name=provider_name,
                    task=task,
                    prompt=prompt,
                    payload=comparison_payload,
                )
                for provider_name, task, prompt in comparison_calls
            ],
            return_exceptions=True,
        )
        for (provider_name, task, _), result in zip(comparison_calls, comparison_results, strict=True):
            try:
                if isinstance(result, BaseException):
                    raise result
                if not isinstance(result, dict):
                    raise TypeError("Unexpected comparison result payload")

                usage = result.get("usage")
                content = result.get("content")
                if not isinstance(usage, dict):
                    raise TypeError("Comparison result missing usage payload")

                model_usage.append(usage)
                selected_prompt = next(prompt for name, _, prompt in comparison_calls if name == provider_name)
                model_calls.append(
                    {
                        "task": task.value,
                        "provider": provider_name,
                        "model": usage.get("model"),
                        "prompt": selected_prompt,
                        "payload": comparison_payload,
                        "response": {
                            "text": content,
                            "parameters": {
                                "provider": provider_name,
                                "model": usage.get("model"),
                                "task": task.value,
                            },
                        },
                        "usage": usage,
                    }
                )
            except Exception as exc:
                model_errors.append(
                    {
                        "provider": provider_name,
                        "task": task.value,
                        "prompt": next(prompt for name, _, prompt in comparison_calls if name == provider_name),
                        "payload": str(comparison_payload),
                        "error": str(exc),
                    }
                )
    resolution_event = {
        "sequence": 4,
        "agent": "Resolution Intelligence Agent",
        "action": "Ran LangGraph RCA workflow",
        "input": {
            "incident_id": incident.id,
            "severity": enriched_alert.severity.value,
            "deployment": context.deployment,
            "related_incidents": len(context.related_incidents),
            "workflow": decision.workflow,
        },
        "decision": f"Root cause: {recommendation.root_cause}; action: {recommendation.recommended_action}",
        "output": "Recommendation with impact, rationale, commands, confidence, and risk",
        "communicates_to": "Human Approval Layer via resolution-events",
        "metrics": {
            "confidence": recommendation.confidence,
            "commands": len(recommendation.commands),
            "risk": recommendation.risk,
        },
        "llm_calls": model_calls,
        "llm_errors": model_errors,
    }
    await persist_step(
        track_agent_work_operation(
            incident_id=incident.id,
            agent_name="Resolution Intelligence Agent",
            work_item="Run RCA and produce recommendation",
            status="completed",
            sequence=4,
            trace_id=trace_id,
            ticket_id=incident.ticket_id,
            details={
                "action": resolution_event["action"],
                "input": resolution_event["input"],
                "decision": resolution_event["decision"],
                "output": resolution_event["output"],
                "communicates_to": resolution_event["communicates_to"],
                "metrics": resolution_event["metrics"],
                "llm_calls": resolution_event.get("llm_calls", []),
                "llm_errors": resolution_event.get("llm_errors", []),
            },
            started_at=now,
            completed_at=datetime.now(timezone.utc),
        )
    )
    requires_human_approval = enriched_alert.severity in {AlertSeverity.HIGH, AlertSeverity.CRITICAL}
    recommendation_envelope = _build_local_metadata_envelope(
        event_type="incident.recommendation.generated",
        incident=incident.model_dump(mode="json"),
        alert=enriched_alert.model_dump(mode="json"),
        decision=decision.__dict__,
        status="awaiting_approval" if (requires_human_approval and not auto_approve) else "remediating",
        payload={
            "recommendation_id": str(recommendation.id),
            "flow_id": str(getattr(decision, "flow_id", "") or ""),
            "trace_id": str(trace_id or ""),
            "recommended_action": recommendation.recommended_action,
            "root_cause": recommendation.root_cause,
            "impact": recommendation.impact,
            "risk": recommendation.risk,
        },
        confidence=float(recommendation.confidence),
        model_provider=(model_usage[0].get("provider") if model_usage else None),
        model_name=(model_usage[0].get("model") if model_usage else None),
        fallback_reason=(model_errors[0].get("error") if model_errors else None),
        transport_provider=decision.message_bus_provider,
    )
    await persist_step(track_metadata_event_operation(recommendation_envelope))
    finops = build_finops_summary(model_usage, model_errors)

    if requires_human_approval and not auto_approve:
        pending_approval = Approval(
            incident_id=incident.id,
            recommendation_id=recommendation.id,
            decision=ApprovalDecision.PENDING,
            approver=None,
            channel="web",
            comment=scenario["remediation_comment"],
            trace_id=trace_id,
            metadata={
                "policy_version": decision.policy_version,
                "policy_reason": decision.policy_reason,
                "orchestration_decision": recommendation.metadata.get("orchestration_decision", {}),
            },
        )
        approval_event = {
            "sequence": 5,
            "agent": "Human Approval Layer",
            "action": "Paused workflow for user approval",
            "input": {
                "incident_id": incident.id,
                "recommendation_id": recommendation.id,
                "recommended_action": recommendation.recommended_action,
                "channel": pending_approval.channel,
                "workflow": decision.workflow,
            },
            "decision": pending_approval.decision.value,
            "output": "Awaiting explicit user decision in Approval Workbench",
            "communicates_to": "Approval Workbench",
            "metrics": {"approval_required": True, "channel": pending_approval.channel},
        }
        await persist_step(
            lambda repo: repo.save_approval(pending_approval),
            track_agent_work_operation(
                incident_id=incident.id,
                agent_name="Human Approval Layer",
                work_item="Await user approval decision",
                status="pending",
                sequence=5,
                trace_id=trace_id,
                ticket_id=incident.ticket_id,
                details={
                    "action": approval_event["action"],
                    "input": approval_event["input"],
                    "decision": approval_event["decision"],
                    "output": approval_event["output"],
                    "communicates_to": approval_event["communicates_to"],
                    "metrics": approval_event["metrics"],
                },
                started_at=now,
                completed_at=None,
            ),
        )

        metrics = {
            "alerts_processed": 1,
            "deduplicated_count": enriched_alert.deduplicated_count,
            "severity": enriched_alert.severity.value,
            "related_incidents": len(context.related_incidents),
            "dependency_services": len(context.dependency_services),
            "recent_changes": len(context.recent_changes),
            "recommendation_confidence": recommendation.confidence,
            "agent_handoffs": 4,
            "approval_required": True,
            "remediation_status": "pending_approval",
            "health_restored": False,
            "alerts_cleared": False,
        }

        base_events = [alert_event, orchestrator_event, context_event, resolution_event]
        pending_payload = {
            "flow_id": flow_id,
            "trace_id": trace_id,
            "scenario": {
                "id": flow_id,
                "title": scenario["title"],
                "recommended_action": scenario["recommended_action"],
            },
            "alert": enriched_alert.model_dump(mode="json"),
            "incident": incident.model_dump(mode="json"),
            "decision": decision.__dict__,
            "context": context.model_dump(mode="json"),
            "recommendation": recommendation.model_dump(mode="json"),
            "events_base": base_events,
            "metrics_base": {
                "alerts_processed": 1,
                "deduplicated_count": enriched_alert.deduplicated_count,
                "severity": enriched_alert.severity.value,
                "related_incidents": len(context.related_incidents),
                "dependency_services": len(context.dependency_services),
                "recent_changes": len(context.recent_changes),
                "recommendation_confidence": recommendation.confidence,
                "approval_required": True,
            },
            "finops": finops,
            "ticket_id": incident.ticket_id,
            "service": incident.service,
        }
        incident_id_str = str(incident.id)
        recommendation_id_str = str(recommendation.id)
        safe_pending_payload = _json_safe(pending_payload)
        await _save_pending_workflow_to_db(
            incident_id=incident_id_str,
            recommendation_id=recommendation_id_str,
            flow_id=flow_id,
            trace_id=trace_id,
            payload=safe_pending_payload,
        )

        return {
            "mode": "local-no-kafka",
            "scenario": {
                "id": flow_id,
                "title": scenario["title"],
                "recommended_action": scenario["recommended_action"],
            },
            "alert": enriched_alert.model_dump(mode="json"),
            "incident": incident.model_dump(mode="json"),
            "decision": decision.__dict__,
            "context": context.model_dump(mode="json"),
            "recommendation": recommendation.model_dump(mode="json"),
            "approval": pending_approval.model_dump(mode="json"),
            "remediation_action": {},
            "closure_report": {},
            "metrics": metrics,
            "finops": finops,
            "events": base_events + [approval_event],
            "next_step": "Awaiting user approval for high-risk action. Approve in Approval tab to continue workflow.",
        }

    approval = Approval(
        incident_id=incident.id,
        recommendation_id=recommendation.id,
        decision=ApprovalDecision.APPROVED,
        approver="kaiops-demo",
        channel="web",
        comment=scenario["remediation_comment"],
        trace_id=trace_id,
        metadata={
            "policy_version": decision.policy_version,
            "policy_reason": decision.policy_reason,
            "orchestration_decision": recommendation.metadata.get("orchestration_decision", {}),
        },
    )
    await persist_step(lambda repo: repo.save_approval(approval))
    approval_event = {
        "sequence": 5,
        "agent": "Human Approval Layer",
        "action": "Auto-approved low-risk recommendation",
        "input": {
            "incident_id": incident.id,
            "recommendation_id": recommendation.id,
            "recommended_action": recommendation.recommended_action,
            "channel": approval.channel,
            "workflow": decision.workflow,
        },
        "decision": approval.decision.value,
        "output": f"Approved by {approval.approver} on {approval.channel}",
        "communicates_to": "Remediation Automation Engine via approval-events",
        "metrics": {"approval_required": False, "channel": approval.channel},
    }
    await persist_step(
        track_agent_work_operation(
            incident_id=incident.id,
            agent_name="Human Approval Layer",
            work_item="Review and approve recommendation",
            status="completed",
            sequence=5,
            trace_id=trace_id,
            ticket_id=incident.ticket_id,
            details={
                "action": approval_event["action"],
                "input": approval_event["input"],
                "decision": approval_event["decision"],
                "output": approval_event["output"],
                "communicates_to": approval_event["communicates_to"],
                "metrics": approval_event["metrics"],
            },
            started_at=now,
            completed_at=datetime.now(timezone.utc),
        )
    )
    engine = RemediationEngine()
    action = engine.build_action(approval)
    action.parameters.update({"root_cause": recommendation.root_cause, "impact": recommendation.impact})
    action = await engine.execute(action)
    action.trace_id = trace_id
    await persist_step(
        lambda repo: repo.save_action(action),
        lambda repo: repo.save_action_audit(action),
    )
    remediation_event = {
        "sequence": 6,
        "agent": "Remediation Automation Engine",
        "action": "Executed remediation strategy plugin",
        "input": {
            "approval_id": approval.id,
            "comment": approval.comment,
            "action_type": action.action_type,
            "target": action.target,
        },
        "decision": f"Selected plugin action {action.action_type}",
        "output": action.output,
        "communicates_to": "Closure & Validation via remediation-events",
        "metrics": {"status": action.status.value, "target": action.target},
    }
    await persist_step(
        track_agent_work_operation(
            incident_id=incident.id,
            agent_name="Remediation Automation Engine",
            work_item="Execute remediation strategy",
            status="completed" if action.status.value == "succeeded" else action.status.value,
            sequence=6,
            trace_id=trace_id,
            ticket_id=incident.ticket_id,
            details={
                "action": remediation_event["action"],
                "input": remediation_event["input"],
                "decision": remediation_event["decision"],
                "output": remediation_event["output"],
                "communicates_to": remediation_event["communicates_to"],
                "metrics": remediation_event["metrics"],
            },
            started_at=now,
            completed_at=datetime.now(timezone.utc),
        )
    )
    closure_report = await ClosureValidationAgent().validate(action)
    closure_report.trace_id = trace_id
    await persist_step(
        lambda repo: repo.save_report(closure_report),
        lambda repo: repo.save_knowledge_base(closure_report, service=incident.service),
    )
    closure_event = {
        "sequence": 7,
        "agent": "Closure & Validation",
        "action": "Validated health and generated closure report",
        "input": {
            "remediation_action_id": action.id,
            "status": action.status.value,
            "output": action.output,
        },
        "decision": "Health restored" if closure_report.health_restored else "Health not restored",
        "output": closure_report.knowledge_base_entry,
        "communicates_to": "Knowledge Base and audit log",
        "metrics": {
            "alerts_cleared": closure_report.alerts_cleared,
            "health_restored": closure_report.health_restored,
        },
    }
    await persist_step(
        track_agent_work_operation(
            incident_id=incident.id,
            agent_name="Closure & Validation",
            work_item="Validate recovery and close incident",
            status="completed" if closure_report.health_restored else "failed",
            sequence=7,
            trace_id=trace_id,
            ticket_id=incident.ticket_id,
            details={
                "action": closure_event["action"],
                "input": closure_event["input"],
                "decision": closure_event["decision"],
                "output": closure_event["output"],
                "communicates_to": closure_event["communicates_to"],
                "metrics": closure_event["metrics"],
            },
            started_at=now,
            completed_at=datetime.now(timezone.utc),
        )
    )
    metrics = {
        "alerts_processed": 1,
        "deduplicated_count": enriched_alert.deduplicated_count,
        "severity": enriched_alert.severity.value,
        "related_incidents": len(context.related_incidents),
        "dependency_services": len(context.dependency_services),
        "recent_changes": len(context.recent_changes),
        "recommendation_confidence": recommendation.confidence,
        "agent_handoffs": 6,
        "approval_required": False,
        "remediation_status": action.status.value,
        "health_restored": closure_report.health_restored,
        "alerts_cleared": closure_report.alerts_cleared,
    }

    final_payload = {
        "mode": "local-no-kafka",
        "scenario": {
            "id": flow_id,
            "title": scenario["title"],
            "recommended_action": scenario["recommended_action"],
        },
        "alert": enriched_alert.model_dump(mode="json"),
        "incident": incident.model_dump(mode="json"),
        "decision": decision.__dict__,
        "context": context.model_dump(mode="json"),
        "recommendation": recommendation.model_dump(mode="json"),
        "approval": approval.model_dump(mode="json"),
        "remediation_action": action.model_dump(mode="json"),
        "closure_report": closure_report.model_dump(mode="json"),
        "metrics": metrics,
        "finops": finops,
        "events": [
            alert_event,
            orchestrator_event,
            context_event,
            resolution_event,
            approval_event,
            remediation_event,
            closure_event,
        ],
        "next_step": "Incident closed in local demo. Review closure report and lessons learned.",
    }
    _record_closed_incident(
        scenario=final_payload.get("scenario", {}),
        incident=final_payload.get("incident", {}),
        recommendation=final_payload.get("recommendation", {}),
        remediation_action=final_payload.get("remediation_action", {}),
        closure_report=final_payload.get("closure_report", {}),
        metrics=final_payload.get("metrics", {}),
        trace_id=trace_id,
    )
    closure_envelope = _build_local_metadata_envelope(
        event_type="incident.closed",
        incident=final_payload.get("incident", {}),
        alert=final_payload.get("alert", {}),
        decision=final_payload.get("decision", {}),
        status="closed" if bool(closure_report.health_restored) else "failed",
        payload={
            "action_type": action.action_type,
            "action_status": action.status.value,
            "health_restored": bool(closure_report.health_restored),
            "alerts_cleared": bool(closure_report.alerts_cleared),
        },
        confidence=float(recommendation.confidence),
        model_provider=(model_usage[0].get("provider") if model_usage else None),
        model_name=(model_usage[0].get("model") if model_usage else None),
        transport_provider=decision.message_bus_provider,
    )
    await persist_step(track_metadata_event_operation(closure_envelope))
    return final_payload


async def continue_pending_workflow(
    *,
    flow_id: str,
    incident_id: str,
    recommendation_id: str,
    decision_token: str,
    approver: str | None,
    channel: str | None,
    comment: str | None,
    modified_action: str | None,
    trace_id: str | None,
) -> dict[str, Any]:
    from closure_service import ClosureValidationAgent
    from remediation_engine import RemediationEngine

    incident_key = str(incident_id)
    persisted = await _load_pending_workflow_from_db(incident_key)
    pending: dict[str, Any] | None = None
    if persisted and str(persisted.get("status") or "").strip().lower() == "completed":
        completed_payload = persisted.get("completed_payload") if isinstance(persisted.get("completed_payload"), dict) else None
        if completed_payload:
            return completed_payload
    if persisted and isinstance(persisted.get("payload"), dict):
        pending = persisted.get("payload", {})

    if not pending:
        raise HTTPException(status_code=404, detail="No pending workflow found for incident")

    if str(pending.get("flow_id")) != str(flow_id):
        raise HTTPException(status_code=400, detail="Flow ID does not match pending workflow")

    recommendation_data = pending.get("recommendation", {})
    if str(recommendation_data.get("id", "")) != str(recommendation_id):
        raise HTTPException(status_code=400, detail="Recommendation ID does not match pending workflow")

    token = str(decision_token or "").strip().lower()
    decision_map = {
        "approve": ApprovalDecision.APPROVED,
        "approved": ApprovalDecision.APPROVED,
        "reject": ApprovalDecision.REJECTED,
        "rejected": ApprovalDecision.REJECTED,
        "modify": ApprovalDecision.MODIFIED,
        "modified": ApprovalDecision.MODIFIED,
    }
    approval_decision = decision_map.get(token)
    if approval_decision is None:
        raise HTTPException(status_code=400, detail="Invalid approval decision")

    approval_trace_id = trace_id or str(pending.get("trace_id") or "") or None
    incident_uuid = UUID(str(incident_id))
    recommendation_uuid = UUID(str(recommendation_id))

    async def persist_step(*operations: Any) -> None:
        session_factory = getattr(app.state, "session_factory", None)
        engine = None
        if not settings.database_enabled:
            return
        if session_factory is None:
            engine = create_engine(settings)
            session_factory = create_session_factory(engine)
            await create_schema(engine)
        try:
            async with session_factory() as session:
                repo = IncidentRepository(session)
                for operation in operations:
                    await operation(repo)
                await session.commit()
        finally:
            if engine is not None:
                await engine.dispose()

    def track_agent_work_operation(
        *,
        incident_id_value: Any,
        agent_name: str,
        work_item: str,
        status: str,
        sequence: int,
        trace_id_value: str | None,
        ticket_id: str | None,
        details: dict[str, Any] | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
    ):
        async def _operation(repo: IncidentRepository) -> None:
            await repo.save_agent_work_item(
                incident_id=incident_id_value,
                agent_name=agent_name,
                work_item=work_item,
                status=status,
                sequence=sequence,
                trace_id=trace_id_value,
                ticket_id=ticket_id,
                details=details or {},
                started_at=started_at,
                completed_at=completed_at,
            )

        return _operation

    approval = Approval(
        incident_id=incident_uuid,
        recommendation_id=recommendation_uuid,
        decision=approval_decision,
        approver=(approver or "sre@example.com").strip() or "sre@example.com",
        channel=(channel or "web").strip() or "web",
        comment=(comment or "").strip() or None,
        modified_action=(modified_action or "").strip() or None,
        trace_id=approval_trace_id,
    )

    now = datetime.now(timezone.utc)
    await persist_step(
        lambda repo: repo.save_approval(approval),
        track_agent_work_operation(
            incident_id_value=incident_uuid,
            agent_name="Human Approval Layer",
            work_item="Review and approve recommendation",
            status="completed",
            sequence=5,
            trace_id_value=approval_trace_id,
            ticket_id=str(pending.get("ticket_id") or "") or None,
            details={"decision": approval.decision.value, "channel": approval.channel},
            started_at=now,
            completed_at=datetime.now(timezone.utc),
        ),
    )

    incident_data = pending.get("incident", {}) if isinstance(pending.get("incident"), dict) else {}
    service_name = str(incident_data.get("service") or pending.get("service") or "unknown")

    if approval.decision == ApprovalDecision.REJECTED:
        action = RemediationAction(
            incident_id=incident_uuid,
            approval_id=approval.id,
            action_type="manual-review",
            target=service_name,
            status=RemediationStatus.SKIPPED,
            output="Remediation skipped because approval was rejected.",
            trace_id=approval_trace_id,
        )
        closure_report = ResolutionReport(
            incident_id=incident_uuid,
            recommendation_id=recommendation_uuid,
            remediation_action_id=action.id,
            root_cause=str(recommendation_data.get("root_cause", "N/A")),
            impact=str(recommendation_data.get("impact", "N/A")),
            action_taken="Approval rejected",
            validation={"approval_rejected": True},
            alerts_cleared=False,
            health_restored=False,
            knowledge_base_entry="Workflow halted: recommendation rejected during approval.",
            lessons_learned=["High-risk action requires explicit approval before remediation."],
            trace_id=approval_trace_id,
        )
    else:
        engine = RemediationEngine()
        action = engine.build_action(approval)
        action.parameters.update(
            {
                "root_cause": str(recommendation_data.get("root_cause", "N/A")),
                "impact": str(recommendation_data.get("impact", "N/A")),
            }
        )
        if approval.decision == ApprovalDecision.MODIFIED and approval.modified_action:
            action.action_type = approval.modified_action
        action = await engine.execute(action)
        action.trace_id = approval_trace_id

        closure_report = await ClosureValidationAgent().validate(action)
        closure_report.trace_id = approval_trace_id

    await persist_step(
        lambda repo: repo.save_action(action),
        lambda repo: repo.save_report(closure_report),
        lambda repo: repo.save_knowledge_base(closure_report, service=service_name),
    )

    remediation_status = "completed" if action.status.value == "succeeded" else action.status.value
    await persist_step(
        track_agent_work_operation(
            incident_id_value=incident_uuid,
            agent_name="Remediation Automation Engine",
            work_item="Execute remediation strategy",
            status=remediation_status,
            sequence=6,
            trace_id_value=approval_trace_id,
            ticket_id=str(pending.get("ticket_id") or "") or None,
            details={"status": action.status.value, "target": action.target},
            started_at=now,
            completed_at=datetime.now(timezone.utc),
        ),
        track_agent_work_operation(
            incident_id_value=incident_uuid,
            agent_name="Closure & Validation",
            work_item="Validate recovery and close incident",
            status="completed" if closure_report.health_restored else "failed",
            sequence=7,
            trace_id_value=approval_trace_id,
            ticket_id=str(pending.get("ticket_id") or "") or None,
            details={
                "health_restored": closure_report.health_restored,
                "alerts_cleared": closure_report.alerts_cleared,
            },
            started_at=now,
            completed_at=datetime.now(timezone.utc),
        ),
    )

    approval_event = {
        "sequence": 5,
        "agent": "Human Approval Layer",
        "action": "User decision submitted from Approval Workbench",
        "input": {
            "incident_id": incident_id,
            "recommendation_id": recommendation_id,
            "channel": approval.channel,
            "comment": approval.comment,
        },
        "decision": approval.decision.value,
        "output": f"Decision by {approval.approver}",
        "communicates_to": "Remediation Automation Engine",
        "metrics": {"approval_required": True, "channel": approval.channel},
    }
    remediation_event = {
        "sequence": 6,
        "agent": "Remediation Automation Engine",
        "action": "Executed remediation strategy plugin",
        "input": {
            "approval_id": str(approval.id),
            "action_type": action.action_type,
            "target": action.target,
        },
        "decision": f"Selected plugin action {action.action_type}",
        "output": action.output,
        "communicates_to": "Closure & Validation via remediation-events",
        "metrics": {"status": action.status.value, "target": action.target},
    }
    closure_event = {
        "sequence": 7,
        "agent": "Closure & Validation",
        "action": "Validated health and generated closure report",
        "input": {
            "remediation_action_id": str(action.id),
            "status": action.status.value,
            "output": action.output,
        },
        "decision": "Health restored" if closure_report.health_restored else "Health not restored",
        "output": closure_report.knowledge_base_entry,
        "communicates_to": "Knowledge Base and audit log",
        "metrics": {
            "alerts_cleared": closure_report.alerts_cleared,
            "health_restored": closure_report.health_restored,
        },
    }

    metrics_base = pending.get("metrics_base", {}) if isinstance(pending.get("metrics_base"), dict) else {}
    final_incident_status = IncidentStatus.CLOSED if closure_report.health_restored else IncidentStatus.FAILED
    final_incident_payload = {
        **incident_data,
        "status": final_incident_status.value,
        "closed_at": datetime.now(timezone.utc).isoformat() if closure_report.health_restored else incident_data.get("closed_at"),
    }
    final_incident = Incident.model_validate(final_incident_payload)
    metrics = {
        **metrics_base,
        "agent_handoffs": 6,
        "approval_required": True,
        "remediation_status": action.status.value,
        "health_restored": closure_report.health_restored,
        "alerts_cleared": closure_report.alerts_cleared,
    }

    events_base = pending.get("events_base", []) if isinstance(pending.get("events_base"), list) else []
    final_payload = {
        "mode": "local-no-kafka",
        "scenario": pending.get("scenario", {}),
        "alert": pending.get("alert", {}),
        "incident": final_incident.model_dump(mode="json"),
        "decision": pending.get("decision", {}),
        "context": pending.get("context", {}),
        "recommendation": recommendation_data,
        "approval": approval.model_dump(mode="json"),
        "remediation_action": action.model_dump(mode="json"),
        "closure_report": closure_report.model_dump(mode="json"),
        "metrics": metrics,
        "finops": pending.get("finops", {}),
        "events": events_base + [approval_event, remediation_event, closure_event],
        "next_step": "Incident closed after user approval.",
    }
    _record_closed_incident(
        scenario=final_payload.get("scenario", {}),
        incident=final_payload.get("incident", {}),
        recommendation=final_payload.get("recommendation", {}),
        remediation_action=final_payload.get("remediation_action", {}),
        closure_report=final_payload.get("closure_report", {}),
        metrics=final_payload.get("metrics", {}),
        trace_id=approval_trace_id,
    )
    await persist_step(
        lambda repo: repo.save_incident(final_incident),
        lambda repo: repo.save_incident_event(
            _json_safe(
                _build_local_metadata_envelope(
                    event_type="incident.closed",
                    incident=final_payload.get("incident", {}),
                    alert=final_payload.get("alert", {}),
                    decision=final_payload.get("decision", {}),
                    status="closed" if bool(closure_report.health_restored) else "failed",
                    payload={
                        "approval_decision": approval.decision.value,
                        "action_type": action.action_type,
                        "action_status": action.status.value,
                        "health_restored": bool(closure_report.health_restored),
                        "alerts_cleared": bool(closure_report.alerts_cleared),
                    },
                    confidence=float(recommendation_data.get("confidence", 0.0) or 0.0),
                    transport_provider=str(final_payload.get("decision", {}).get("message_bus_provider") or "rabbitmq"),
                )
            )
        )
    )
    await _mark_pending_workflow_completed_in_db(incident_key, final_payload)
    return final_payload


def build_finops_summary(model_usage: list[dict[str, Any]], model_errors: list[dict[str, str]]) -> dict[str, Any]:
    totals = {
        "input_tokens": sum(int(item.get("input_tokens", 0)) for item in model_usage),
        "output_tokens": sum(int(item.get("output_tokens", 0)) for item in model_usage),
        "total_tokens": sum(int(item.get("total_tokens", 0)) for item in model_usage),
        "total_cost_usd": round(sum(float(item.get("total_cost_usd", 0.0)) for item in model_usage), 8),
        "calls": len(model_usage),
        "failed_calls": len(model_errors),
    }
    by_provider: dict[str, dict[str, Any]] = {}
    for item in model_usage:
        provider = str(item.get("provider", "unknown"))
        row = by_provider.setdefault(
            provider,
            {"provider": provider, "calls": 0, "total_tokens": 0, "total_cost_usd": 0.0},
        )
        row["calls"] += 1
        row["total_tokens"] += int(item.get("total_tokens", 0))
        row["total_cost_usd"] = round(float(row["total_cost_usd"]) + float(item.get("total_cost_usd", 0.0)), 8)
    return {
        "totals": totals,
        "by_provider": list(by_provider.values()),
        "calls": model_usage,
        "errors": model_errors,
        "currency": "USD",
    }


def _record_closed_incident(
    *,
    scenario: dict[str, Any],
    incident: dict[str, Any],
    recommendation: dict[str, Any],
    remediation_action: dict[str, Any],
    closure_report: dict[str, Any],
    metrics: dict[str, Any],
    trace_id: str | None,
) -> None:
    recommendation_metadata = recommendation.get("metadata", {}) if isinstance(recommendation.get("metadata"), dict) else {}
    orchestration_decision = (
        recommendation_metadata.get("orchestration_decision", {})
        if isinstance(recommendation_metadata.get("orchestration_decision"), dict)
        else {}
    )
    CLOSED_INCIDENTS.appendleft(
        {
            "incident_id": str(closure_report.get("incident_id") or incident.get("id") or ""),
            "flow_id": str(scenario.get("id") or ""),
            "title": str(scenario.get("title") or incident.get("title") or "Incident"),
            "service": str(incident.get("service") or "unknown"),
            "severity": str(metrics.get("severity") or incident.get("severity") or "unknown").upper(),
            "risk": str(recommendation.get("risk") or "unknown").upper(),
            "risk_tier": str(orchestration_decision.get("risk_tier") or "unknown").upper(),
            "execution_mode": str(orchestration_decision.get("execution_mode") or "unknown").lower(),
            "transport_provider": str(orchestration_decision.get("message_bus_provider") or "unknown").lower(),
            "status": "closed" if bool(closure_report.get("health_restored")) else "failed",
            "decision": str(recommendation.get("recommended_action") or "N/A"),
            "action_type": str(remediation_action.get("action_type") or "N/A"),
            "action_status": str(remediation_action.get("status") or "N/A"),
            "health_restored": bool(closure_report.get("health_restored")),
            "alerts_cleared": bool(closure_report.get("alerts_cleared")),
            "root_cause": str(closure_report.get("root_cause") or "N/A"),
            "impact": str(closure_report.get("impact") or "N/A"),
            "trace_id": str(trace_id or closure_report.get("trace_id") or ""),
            "closed_at": datetime.now(timezone.utc).isoformat(),
        }
    )


def _build_alert_from_payload(payload: dict[str, Any], trace_id: str | None = None) -> Alert:
    labels = payload.get("labels", {}) if isinstance(payload.get("labels"), dict) else {}
    annotations = payload.get("annotations", {}) if isinstance(payload.get("annotations"), dict) else {}
    severity_value = severity_from_string(
        str(payload.get("severity", labels.get("severity", "warning")))
    )
    return Alert(
        source=payload.get("source", payload.get("generatorURL", "unknown")),
        name=payload.get("name", payload.get("alertname", labels.get("alertname", "unknown-alert"))),
        service=payload.get("service", labels.get("service", labels.get("job", "unknown"))),
        environment=payload.get("environment", labels.get("env", labels.get("environment", "prod"))),
        severity=AlertSeverity(severity_value),
        description=payload.get("description", annotations.get("summary", "")),
        labels=labels,
        annotations=annotations,
        trace_id=trace_id,
    )


async def _publish_ingested_alert(alert: Alert) -> None:
    payload = _build_raw_alert_event_payload(alert)
    started = perf_counter()
    await app.state.producer.publish(RAW_ALERTS, payload, key=alert.service)
    EVENT_PUBLISH_LATENCY.labels(settings.service_name, RAW_ALERTS, "monitoring-adapter").observe(
        max(0.0, perf_counter() - started)
    )
    EVENT_CONTRACTS_EMITTED.labels(settings.service_name, RAW_ALERTS, "monitoring-adapter", "v1").inc()
    RECENT_ALERTS.appendleft(
        {
            "id": str(alert.id),
            "trace_id": alert.trace_id,
            "source": alert.source,
            "name": alert.name,
            "service": alert.service,
            "environment": alert.environment,
            "severity": alert.severity.value,
            "description": alert.description,
            "labels": alert.labels,
            "annotations": alert.annotations,
            "created_at": alert.created_at.isoformat(),
        }
    )


def _build_raw_alert_event_payload(alert: Alert) -> dict[str, Any]:
    incident_hint = str(alert.id)
    event_contract = build_agent_event_contract(
        flow_id=incident_hint,
        incident_id=incident_hint,
        trace_id=str(alert.trace_id or ""),
        correlation_id=str(alert.correlation_id or "") or None,
        agent="monitoring-adapter",
        payload={
            "source": alert.source,
            "name": alert.name,
            "service": alert.service,
            "severity": alert.severity.value,
            "topic": RAW_ALERTS,
        },
        metadata={
            "environment": alert.environment,
        },
        confidence=1.0,
        reasoning="raw alert accepted by monitoring adapter ingestion endpoint",
        citations=[f"alert://{alert.id}"],
        evidence_ids=[f"alert:{alert.id}"],
    )
    return {
        "alert": alert,
        "event_contract": event_contract,
    }


@app.post("/alerts", response_model=Alert)
async def ingest_alert(payload: dict = ALERT_BODY, x_trace_id: str | None = Header(default=None)) -> Alert:
    alert = _build_alert_from_payload(payload, trace_id=x_trace_id)
    await _publish_ingested_alert(alert)
    return alert


@app.post("/alerts/alertmanager")
async def ingest_alertmanager_webhook(payload: dict = ALERT_BODY, x_trace_id: str | None = Header(default=None)) -> dict[str, Any]:
    alerts_payload = payload.get("alerts", []) if isinstance(payload, dict) else []
    if not isinstance(alerts_payload, list):
        raise HTTPException(status_code=400, detail="alertmanager payload must contain an alerts array")

    common_labels = payload.get("commonLabels", {}) if isinstance(payload.get("commonLabels"), dict) else {}
    common_annotations = payload.get("commonAnnotations", {}) if isinstance(payload.get("commonAnnotations"), dict) else {}

    received = len(alerts_payload)
    ingested_rows: list[dict[str, Any]] = []
    skipped_rows: list[dict[str, Any]] = []

    for item in alerts_payload:
        if not isinstance(item, dict):
            skipped_rows.append({"reason": "non-object alert item"})
            continue

        status = str(item.get("status") or payload.get("status") or "firing").strip().lower()
        labels = item.get("labels", {}) if isinstance(item.get("labels"), dict) else {}
        annotations = item.get("annotations", {}) if isinstance(item.get("annotations"), dict) else {}
        merged_labels = {**common_labels, **labels}
        merged_annotations = {**common_annotations, **annotations}

        if status != "firing":
            skipped_rows.append(
                {
                    "status": status,
                    "alertname": str(merged_labels.get("alertname") or "unknown-alert"),
                    "service": str(merged_labels.get("service") or merged_labels.get("job") or "unknown"),
                    "reason": "Only firing alerts are sent to landing pad",
                }
            )
            continue

        mapped_payload = {
            "source": "prometheus-alertmanager",
            "name": str(merged_labels.get("alertname") or "prometheus-alert"),
            "service": str(merged_labels.get("service") or merged_labels.get("job") or merged_labels.get("instance") or "kaiops-platform"),
            "environment": str(merged_labels.get("environment") or merged_labels.get("env") or "prod"),
            "severity": str(merged_labels.get("severity") or "warning").lower(),
            "description": str(merged_annotations.get("description") or merged_annotations.get("summary") or merged_labels.get("alertname") or "Prometheus alert"),
            "labels": {
                **merged_labels,
                "alert_status": status,
                "alert_fingerprint": str(item.get("fingerprint") or ""),
            },
            "annotations": {
                **merged_annotations,
                "startsAt": str(item.get("startsAt") or ""),
                "endsAt": str(item.get("endsAt") or ""),
                "generatorURL": str(item.get("generatorURL") or ""),
            },
        }

        alert = _build_alert_from_payload(mapped_payload, trace_id=x_trace_id)
        await _publish_ingested_alert(alert)
        landing_pad_file = _persist_alert_to_landing_pad(mapped_payload, item)
        ingested_rows.append(
            {
                "alert_id": str(alert.id),
                "name": alert.name,
                "service": alert.service,
                "severity": alert.severity.value,
                "status": status,
                "landing_pad_file": landing_pad_file,
            }
        )

    return {
        "received": received,
        "ingested": len(ingested_rows),
        "skipped": len(skipped_rows),
        "alerts": ingested_rows,
        "skipped_rows": skipped_rows,
    }


@app.get("/alerts")
async def alerts_help() -> dict[str, Any]:
    return {
        "message": "Use POST /alerts to submit alerts. GET /alerts is informational.",
        "example": {
            "method": "POST",
            "path": "/alerts",
            "payload": {
                "source": "monitoring-adapter",
                "name": "DatabaseReplicaLag",
                "service": "orders-db",
                "severity": "critical",
                "description": "Database replica lag exceeded threshold",
            },
        },
    }


@app.get("/alerts/recent")
async def get_recent_alerts(limit: int = 50) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit), 200))
    session_factory = getattr(app.state, "session_factory", None)
    if settings.database_enabled and session_factory is not None:
        async with session_factory() as session:
            repo = IncidentRepository(session)
            rows = await repo.list_alerts(limit=safe_limit)
        return {"rows": rows, "count": len(rows)}

    rows = list(RECENT_ALERTS)[:safe_limit]
    return {"rows": rows, "count": len(rows)}


@app.get("/alerts/all")
async def get_all_alerts(limit: int = 500) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit), 5000))
    session_factory = getattr(app.state, "session_factory", None)
    if settings.database_enabled and session_factory is not None:
        async with session_factory() as session:
            repo = IncidentRepository(session)
            rows = await repo.list_alerts(limit=safe_limit)
        return {"rows": rows, "count": len(rows)}

    rows = list(RECENT_ALERTS)[:safe_limit]
    return {"rows": rows, "count": len(rows)}


@app.get("/alerts/{alert_id}/processed-result")
async def get_processed_result(alert_id: str) -> dict[str, Any]:
    session_factory = getattr(app.state, "session_factory", None)
    if not settings.database_enabled or session_factory is None:
        raise HTTPException(status_code=503, detail="Database is not enabled for processed results")

    async with session_factory() as session:
        repo = IncidentRepository(session)
        result = await repo.get_processed_result_by_alert_id(alert_id)

    if not result:
        raise HTTPException(status_code=404, detail="No processed result found for alert")
    return result


@app.post("/sample/payment-latency", response_model=Alert)
async def sample_payment_latency(x_trace_id: str | None = Header(default=None)) -> Alert:
    alert = build_payment_latency_alert(trace_id=x_trace_id)
    payload = _build_raw_alert_event_payload(alert)
    started = perf_counter()
    await app.state.producer.publish(RAW_ALERTS, payload, key=alert.service)
    EVENT_PUBLISH_LATENCY.labels(settings.service_name, RAW_ALERTS, "monitoring-adapter").observe(
        max(0.0, perf_counter() - started)
    )
    EVENT_CONTRACTS_EMITTED.labels(settings.service_name, RAW_ALERTS, "monitoring-adapter", "v1").inc()
    return alert


@app.get("/sample/flows")
async def sample_flows() -> dict[str, Any]:
    return {"flows": list_scenarios()}


@app.get("/sample/scenarios/source")
async def sample_scenarios_source() -> dict[str, Any]:
    rows = scenario_source_rows()
    return {
        "rows": rows,
        "count": len(rows),
        "sources": {
            "hardcoded": "SCENARIOS",
            "text_file": str(scenarios_text_path()),
            "flow_catalog": f"{flow_catalog_path()} (informational only; not merged)",
        },
    }


@app.get("/onboarding/connectivity", response_model=OnboardingConnectivityResponse)
async def get_onboarding_connectivity() -> OnboardingConnectivityResponse:
    connectivity = load_onboarding_connectivity()
    snapshot = OnboardingConnectivitySnapshot.model_validate(connectivity if isinstance(connectivity, dict) else {})
    return OnboardingConnectivityResponse(connectivity=snapshot)


@app.get("/onboarding/state", response_model=OnboardingStateResponse)
async def get_onboarding_state() -> OnboardingStateResponse:
    session_factory = getattr(app.state, "session_factory", None)
    if not settings.database_enabled or session_factory is None:
        return OnboardingStateResponse(rows=[])

    async with session_factory() as session:
        repo = IncidentRepository(session)
        rows = await repo.list_onboarding_state()
    return OnboardingStateResponse(rows=rows)


@app.delete("/onboarding/state/{project_name}")
async def delete_onboarding_state(project_name: str, provider_name: str | None = None) -> dict[str, Any]:
    session_factory = getattr(app.state, "session_factory", None)
    if not settings.database_enabled or session_factory is None:
        raise HTTPException(status_code=503, detail="Database is not enabled for onboarding state deletion")

    normalized_project = str(project_name or "").strip()
    if not normalized_project:
        raise HTTPException(status_code=400, detail="project_name is required")

    normalized_provider = str(provider_name or "").strip().lower() or None
    async with session_factory() as session:
        repo = IncidentRepository(session)
        deleted = await repo.delete_onboarding_state(normalized_project, normalized_provider)
        await session.commit()

    # Keep delete idempotent for admin UX: deleting an already-absent row should not be treated as an API error.
    return {
        "deleted": deleted,
        "project_name": normalized_project,
        "provider_name": normalized_provider,
        "message": "Onboarding state deleted" if deleted > 0 else "Onboarding state row not found (already deleted)",
    }


@app.get("/landing-pad/recent")
async def get_landing_pad_recent(limit: int = 20) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit), 200))
    input_dir = LANDING_PAD_INPUT_DIR
    input_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(
        [path for path in input_dir.glob("*.json") if path.is_file()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )[:safe_limit]

    rows: list[dict[str, Any]] = []
    for path in files:
        entry: dict[str, Any] = {
            "file": path.name,
            "path": str(path),
            "modified_at": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
            "size_bytes": int(path.stat().st_size),
        }
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            alert = payload.get("alert", {}) if isinstance(payload, dict) else {}
            labels = alert.get("labels", {}) if isinstance(alert.get("labels"), dict) else {}
            annotations = alert.get("annotations", {}) if isinstance(alert.get("annotations"), dict) else {}
            entry.update(
                {
                    "received_at": payload.get("received_at") if isinstance(payload, dict) else None,
                    "name": alert.get("name") if isinstance(alert, dict) else None,
                    "service": alert.get("service") if isinstance(alert, dict) else None,
                    "severity": alert.get("severity") if isinstance(alert, dict) else None,
                    "alert_status": labels.get("alert_status") if isinstance(labels, dict) else None,
                    "alertname": labels.get("alertname") if isinstance(labels, dict) else None,
                    "summary": annotations.get("summary") if isinstance(annotations, dict) else None,
                }
            )
        except Exception:
            entry["parse_error"] = "invalid_json"
        rows.append(entry)

    return {
        "input_dir": str(input_dir),
        "rows": rows,
        "count": len(rows),
    }


@app.get("/agent-work/items")
async def get_agent_work_items(limit: int = 100) -> dict[str, Any]:
    session_factory = getattr(app.state, "session_factory", None)
    if not settings.database_enabled or session_factory is None:
        return {"rows": []}

    async with session_factory() as session:
        repo = IncidentRepository(session)
        rows = await repo.list_agent_work_items(limit=limit)
    return {"rows": rows}


@app.get("/incidents/closed")
async def get_closed_incidents(limit: int = 100) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit), 500))
    session_factory = getattr(app.state, "session_factory", None)
    if settings.database_enabled and session_factory is not None:
        async with session_factory() as session:
            repo = IncidentRepository(session)
            rows = await repo.list_closed_incidents(limit=safe_limit)
        return {"rows": rows, "count": len(rows)}

    rows = list(CLOSED_INCIDENTS)[:safe_limit]
    return {"rows": rows, "count": len(rows)}


@app.get("/incidents/metadata")
async def get_incident_metadata(
    limit: int = 100,
    tenant_id: str = "default",
    incident_id: str | None = None,
    risk_tier: str | None = None,
    execution_mode: str | None = None,
    transport_provider: str | None = None,
    status: str | None = None,
    service: str | None = None,
) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit), 1000))
    session_factory = getattr(app.state, "session_factory", None)
    if settings.database_enabled and session_factory is not None:
        async with session_factory() as session:
            repo = IncidentRepository(session)
            rows = await repo.list_incident_projections(
                limit=safe_limit,
                tenant_id=tenant_id,
                incident_id=incident_id,
                risk_tier=risk_tier,
                execution_mode=execution_mode,
                transport_provider=transport_provider,
                status=status,
                service=service,
            )
        return {"rows": rows, "count": len(rows)}

    rows = list(CLOSED_INCIDENTS)
    if incident_id:
        normalized_incident_id = str(incident_id).strip().lower()
        rows = [row for row in rows if str(row.get("incident_id") or row.get("id") or "").strip().lower() == normalized_incident_id]
    if risk_tier:
        rows = [row for row in rows if str(row.get("risk") or "").strip().lower() == str(risk_tier).strip().lower()]
    if execution_mode:
        rows = [
            row
            for row in rows
            if str(row.get("execution_mode") or "").strip().lower() == str(execution_mode).strip().lower()
        ]
    if transport_provider:
        rows = [
            row
            for row in rows
            if str(row.get("transport_provider") or "").strip().lower() == str(transport_provider).strip().lower()
        ]
    if status:
        rows = [row for row in rows if str(row.get("status") or "").strip().lower() == str(status).strip().lower()]
    if service:
        rows = [row for row in rows if str(row.get("service") or "").strip() == str(service).strip()]
    rows = rows[:safe_limit]
    return {"rows": rows, "count": len(rows)}


@app.get("/incidents/{incident_id}/stage-completeness")
async def get_incident_stage_completeness(incident_id: str) -> dict[str, Any]:
    session_factory = getattr(app.state, "session_factory", None)
    if not settings.database_enabled or session_factory is None:
        raise HTTPException(status_code=503, detail="Database is not enabled for incident stage completeness")

    async with session_factory() as session:
        repo = IncidentRepository(session)
        result = await repo.get_incident_stage_completeness(incident_id)

    if not result:
        raise HTTPException(status_code=404, detail="No incident stage completeness found for incident")
    return result


@app.post("/onboarding/connectivity", response_model=OnboardingConnectivityResponse)
async def post_onboarding_connectivity(
    payload: OnboardingConnectivityPayload = Body(...),
) -> OnboardingConnectivityResponse:
    if isinstance(payload, dict):
        payload = OnboardingConnectivityPayload.model_validate(payload)
    validated_payload = payload.model_dump(mode="json")
    sanitized = save_onboarding_connectivity(validated_payload)
    await persist_onboarding_connectivity(validated_payload)
    snapshot = OnboardingConnectivitySnapshot.model_validate(sanitized if isinstance(sanitized, dict) else {})
    return OnboardingConnectivityResponse(connectivity=snapshot)


@app.post("/onboarding/complete")
async def post_onboarding_complete(payload: OnboardingCompletePayload = Body(...)) -> dict[str, Any]:
    if isinstance(payload, dict):
        payload = OnboardingCompletePayload.model_validate(payload)

    connectivity = payload.connectivity
    connectivity_payload = connectivity.model_dump(mode="json")
    selected_tool = _select_monitoring_tool(connectivity, payload.selected_monitoring_tool)
    landing_pad_summary = _build_landing_pad_summary(connectivity, selected_tool)
    should_start_rules_onboarding = bool(payload.onboarding_path == "setup_monitoring" and payload.start_rules_onboarding)

    sanitized_connectivity = save_onboarding_connectivity(connectivity_payload)
    await persist_onboarding_connectivity(connectivity_payload)
    connectivity_snapshot = OnboardingConnectivitySnapshot.model_validate(
        sanitized_connectivity if isinstance(sanitized_connectivity, dict) else {}
    )

    response: dict[str, Any] = {
        "project_mode": payload.project_mode,
        "onboarding_path": payload.onboarding_path,
        "connectivity": connectivity_snapshot.model_dump(mode="json"),
        "landing_pad_ingestion": landing_pad_summary,
        "rules_onboarding": {
            "started": False,
            "status": "not-required" if payload.onboarding_path == "existing_monitoring" else "not-requested",
        },
        "rag_documents": [],
        "workflow_steps": _build_onboarding_steps_response(
            onboarding_path=payload.onboarding_path,
            project_mode=payload.project_mode,
            start_rules_onboarding=should_start_rules_onboarding,
            requirements=[],
            rules_result=None,
            prometheus_result=None,
            rag_documents=[],
            landing_pad_summary=landing_pad_summary,
        ),
    }

    if not should_start_rules_onboarding:
        return response

    requirements = [item for item in payload.plain_language_requirements if str(item or "").strip()]
    endpoint_url = _selected_tool_url(connectivity, selected_tool)

    project_seed = _build_onboarding_rule_seed(connectivity, selected_tool)
    new_rule_payload = NewRuleOnboardingRequest.model_validate(
        {
            "project": project_seed,
            "monitoring_requirements": requirements,
            "target_platforms": [selected_tool],
            "discovery_inputs": {
                "endpoint_url": endpoint_url,
                "deployment_mode": str(connectivity.deployment_mode or "on_prem").strip(),
                "environment": str(connectivity.project.environment or "prod").strip(),
                "region": str(connectivity.project.region or "").strip(),
                "selected_monitoring_tool": selected_tool,
                "generated_from_plain_language": True,
            },
        }
    )

    workflow_result = run_new_rule_pipeline(new_rule_payload)
    await persist_onboarding_pipeline_result(workflow_result)
    await publish_onboarding_pipeline_event(workflow_result)

    prometheus_upload_result: dict[str, Any] | None = None
    if selected_tool == "prometheus":
        prometheus_upload_result = await _generate_upload_and_test_prometheus_rules(
            endpoint_url=endpoint_url,
            project_name=str(connectivity.project.name or "").strip(),
            workflow_id=str(workflow_result.get("workflow_id") or "").strip(),
            generated_rules=workflow_result.get("generated_rules", []) if isinstance(workflow_result.get("generated_rules"), list) else [],
            include_smoke_test_alert=payload.include_smoke_test_alert,
        )

    response["rules_onboarding"] = {
        "started": True,
        "status": str(workflow_result.get("status") or "completed"),
        "workflow_id": str(workflow_result.get("workflow_id") or "").strip(),
        "result": workflow_result,
    }
    if payload.generate_documents:
        response["rag_documents"] = _build_onboarding_rag_documents(
            connectivity=connectivity,
            selected_tool=selected_tool,
            workflow_result=workflow_result,
            requirements=requirements,
        )
    response["workflow_steps"] = _build_onboarding_steps_response(
        onboarding_path=payload.onboarding_path,
        project_mode=payload.project_mode,
        start_rules_onboarding=should_start_rules_onboarding,
        requirements=requirements,
        rules_result=workflow_result,
        prometheus_result=prometheus_upload_result,
        rag_documents=response.get("rag_documents", []),
        landing_pad_summary=landing_pad_summary,
    )
    return response


@app.get("/onboarding/rules/capabilities")
async def get_onboarding_rule_capabilities() -> dict[str, Any]:
    rows = capabilities_catalog()
    return {"rows": rows, "count": len(rows)}


@app.post("/onboarding/rules/pipeline/existing")
async def onboarding_rules_pipeline_existing(payload: ExistingRulePipelineRequest = Body(...)) -> dict[str, Any]:
    result = run_existing_rule_pipeline(payload)
    await persist_onboarding_pipeline_result(result)
    await publish_onboarding_pipeline_event(result)
    return result


@app.post("/onboarding/rules/pipeline/new")
async def onboarding_rules_pipeline_new(payload: NewRuleOnboardingRequest = Body(...)) -> dict[str, Any]:
    result = run_new_rule_pipeline(payload)
    await persist_onboarding_pipeline_result(result)
    await publish_onboarding_pipeline_event(result)
    return result


@app.post("/onboarding/rules/pipeline/create")
async def onboarding_rules_pipeline_new_alias(payload: NewRuleOnboardingRequest = Body(...)) -> dict[str, Any]:
    # Backward-compatible alias for older callers.
    result = run_new_rule_pipeline(payload)
    await persist_onboarding_pipeline_result(result)
    await publish_onboarding_pipeline_event(result)
    return result


@app.get("/onboarding/rules/pipeline/{workflow_id}")
async def get_onboarding_rules_pipeline(workflow_id: str) -> dict[str, Any]:
    session_factory = getattr(app.state, "session_factory", None)
    if not settings.database_enabled or session_factory is None:
        raise HTTPException(status_code=503, detail="Database is not enabled for onboarding workflow lookup")

    async with session_factory() as session:
        repo = IncidentRepository(session)
        rows = await repo.list_onboarding_state()

    matched = find_pipeline_rows(rows, workflow_id)
    if not matched:
        raise HTTPException(status_code=404, detail="Onboarding rule workflow not found")

    latest = matched[-1]
    payload = latest.get("connectivity_payload", {}) if isinstance(latest.get("connectivity_payload"), dict) else {}
    return {
        "workflow_id": workflow_id,
        "status": payload.get("status"),
        "pipeline": payload.get("pipeline"),
        "project_name": latest.get("project_name"),
        "updated_at": latest.get("updated_at"),
        "result": payload.get("result") if isinstance(payload.get("result"), dict) else {},
    }


@app.put("/onboarding/rules/pipeline/{workflow_id}")
async def update_onboarding_rules_pipeline(workflow_id: str, payload: dict[str, Any] = ALERT_BODY) -> dict[str, Any]:
    session_factory = getattr(app.state, "session_factory", None)
    if not settings.database_enabled or session_factory is None:
        raise HTTPException(status_code=503, detail="Database is not enabled for onboarding workflow update")

    async with session_factory() as session:
        repo = IncidentRepository(session)
        rows = await repo.list_onboarding_state()
        matched = find_pipeline_rows(rows, workflow_id)
        if not matched:
            raise HTTPException(status_code=404, detail="Onboarding rule workflow not found")

        latest = matched[-1]
        connectivity_payload = (
            dict(latest.get("connectivity_payload", {}))
            if isinstance(latest.get("connectivity_payload"), dict)
            else {}
        )
        previous_result = connectivity_payload.get("result", {}) if isinstance(connectivity_payload.get("result"), dict) else {}
        incoming_result = payload.get("result", {}) if isinstance(payload.get("result"), dict) else {}
        merged_result = {**previous_result, **incoming_result}

        target_project_name = str(payload.get("project_name") or latest.get("project_name") or "").strip()
        if not target_project_name:
            raise HTTPException(status_code=400, detail="project_name is required")

        project_payload = latest.get("project_payload", {}) if isinstance(latest.get("project_payload"), dict) else {}
        if isinstance(payload.get("project"), dict):
            project_payload = {**project_payload, **payload.get("project", {})}

        connectivity_payload.update(
            {
                "workflow_id": workflow_id,
                "status": str(payload.get("status") or connectivity_payload.get("status") or merged_result.get("status") or "updated"),
                "pipeline": str(connectivity_payload.get("pipeline") or latest.get("provider_name") or "onboarding_pipeline"),
                "summary": payload.get("summary") if isinstance(payload.get("summary"), dict) else connectivity_payload.get("summary", {}),
                "result": merged_result,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )

        await repo.save_onboarding_state(
            project_name=target_project_name,
            provider_name=str(latest.get("provider_name") or "onboarding_pipeline").strip().lower(),
            owner_team=str(payload.get("owner_team") or latest.get("owner_team") or "").strip() or None,
            environment=str(payload.get("environment") or latest.get("environment") or "").strip() or None,
            region=str(payload.get("region") or latest.get("region") or "").strip() or None,
            endpoint_url=str(payload.get("endpoint_url") or latest.get("endpoint_url") or "").strip() or None,
            test_status=str(connectivity_payload.get("status") or latest.get("test_status") or "updated"),
            test_message=str(payload.get("test_message") or latest.get("test_message") or "Workflow updated by admin"),
            project_payload=project_payload,
            connectivity_payload=connectivity_payload,
            last_tested_at=datetime.now(timezone.utc),
        )
        await session.commit()

    return {
        "workflow_id": workflow_id,
        "status": connectivity_payload.get("status"),
        "pipeline": connectivity_payload.get("pipeline"),
        "project_name": target_project_name,
        "updated_at": connectivity_payload.get("updated_at"),
        "result": connectivity_payload.get("result", {}),
    }


@app.delete("/onboarding/rules/pipeline/{workflow_id}")
async def delete_onboarding_rules_pipeline(workflow_id: str) -> dict[str, Any]:
    session_factory = getattr(app.state, "session_factory", None)
    if not settings.database_enabled or session_factory is None:
        raise HTTPException(status_code=503, detail="Database is not enabled for onboarding workflow delete")

    async with session_factory() as session:
        repo = IncidentRepository(session)
        rows = await repo.list_onboarding_state()
        matched = find_pipeline_rows(rows, workflow_id)
        if not matched:
            raise HTTPException(status_code=404, detail="Onboarding rule workflow not found")

        deleted_total = 0
        for row in matched:
            deleted_total += await repo.delete_onboarding_state(
                str(row.get("project_name") or "").strip(),
                str(row.get("provider_name") or "").strip().lower() or None,
            )
        await session.commit()

    return {"workflow_id": workflow_id, "deleted": deleted_total}


@app.post("/sample/payment-latency/workflow")
async def sample_payment_latency_workflow(
    fast_mode: bool = False,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await run_local_payment_workflow(trace_id=x_trace_id, run_comparison=not fast_mode, auto_approve=False)


@app.post("/sample/{flow_id}/workflow")
async def sample_flow_workflow(
    flow_id: str,
    fast_mode: bool = False,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await run_local_payment_workflow(
        trace_id=x_trace_id,
        flow_id=flow_id,
        run_comparison=not fast_mode,
        auto_approve=False,
    )


@app.post("/sample/{flow_id}/workflow/continue")
async def continue_flow_workflow(
    flow_id: str,
    payload: dict[str, Any] = ALERT_BODY,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return await continue_pending_workflow(
        flow_id=flow_id,
        incident_id=str(payload.get("incident_id") or ""),
        recommendation_id=str(payload.get("recommendation_id") or ""),
        decision_token=str(payload.get("decision") or ""),
        approver=str(payload.get("approver") or "").strip() or None,
        channel=str(payload.get("channel") or "").strip() or None,
        comment=str(payload.get("comment") or "").strip() or None,
        modified_action=str(payload.get("modified_action") or "").strip() or None,
        trace_id=x_trace_id,
    )
