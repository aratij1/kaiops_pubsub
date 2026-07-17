from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from time import perf_counter
from typing import Any, TypedDict
from urllib.parse import urlparse
from uuid import UUID, uuid4

import httpx
from langgraph.graph import END, StateGraph

from common.logging import get_logger
from common.models import (
    ApplicationDiscoveryResult,
    ApplicationRegistration,
    GrafanaDashboardResult,
    MetricsValidationResult,
    MonitoringValidationResult,
    PrometheusRuleSpec,
    RecordingRuleSpec,
    RulesGeneratedResult,
    ScrapeConfigSpec,
)

logger = get_logger(__name__)


def application_from_row(row: dict[str, Any]) -> ApplicationRegistration:
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    return ApplicationRegistration.model_validate(
        {
            "id": row.get("id") or payload.get("id"),
            "created_at": row.get("created_at") or payload.get("created_at"),
            "trace_id": payload.get("trace_id"),
            "metadata": payload.get("metadata") or {},
            "tenant_id": row.get("tenant_id") or payload.get("tenant_id"),
            "name": row.get("name") or payload.get("name"),
            "owner_team": row.get("owner_team") or payload.get("owner_team"),
            "owner_email": row.get("owner_email") or payload.get("owner_email"),
            "environment": row.get("environment") or payload.get("environment"),
            "namespace": row.get("namespace") or payload.get("namespace"),
            "region": row.get("region") or payload.get("region"),
            "technology": row.get("technology") or payload.get("technology"),
            "monitoring_platform": row.get("monitoring_platform") or payload.get("monitoring_platform"),
            "metrics_endpoint": row.get("metrics_endpoint") or payload.get("metrics_endpoint"),
            "labels": payload.get("labels") or {},
            "status": row.get("status") or payload.get("status"),
        }
    )


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", str(value or "").strip().lower()).strip("-") or "application"


def _metric_prefix(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_]+", "_", str(value or "").strip().lower()).strip("_") or "application"
    if cleaned[0].isdigit():
        return f"app_{cleaned}"
    return cleaned


def onboarding_root() -> Path:
    candidates = [
        Path("/app/rag/changes"),
        Path(__file__).resolve().parents[5] / "backend" / "rag" / "changes",
        Path(__file__).resolve().parents[5] / "rag" / "changes",
    ]
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except Exception:
            continue
    fallback = Path("/tmp/kaiops/changes")
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def _build_metrics_candidates(endpoint: str) -> list[str]:
    raw = str(endpoint or "").strip().rstrip("/")
    if not raw:
        return []
    parsed = urlparse(raw)
    if parsed.path.endswith("/metrics") or parsed.path.endswith("/actuator/prometheus"):
        return [raw]
    return [f"{raw}/metrics", f"{raw}/actuator/prometheus", raw]


class _DiscoveryState(TypedDict, total=False):
    application: dict[str, Any]
    resources: list[dict[str, Any]]
    labels: dict[str, str]
    metrics_endpoint: str
    technology: str
    resource_kind: str


class DiscoveryAgent:
    def __init__(self) -> None:
        graph = StateGraph(_DiscoveryState)
        graph.add_node("inventory", self._inventory)
        graph.add_node("metrics", self._metrics)
        graph.add_node("classify", self._classify)
        graph.set_entry_point("inventory")
        graph.add_edge("inventory", "metrics")
        graph.add_edge("metrics", "classify")
        graph.add_edge("classify", END)
        self._graph = graph.compile()

    def _inventory(self, state: _DiscoveryState) -> _DiscoveryState:
        application = state.get("application", {})
        labels = dict(application.get("labels") or {})
        resources = [
            {
                "kind": labels.get("workload_kind", "Deployment"),
                "name": application.get("name"),
                "namespace": application.get("namespace"),
                "environment": application.get("environment"),
            },
            {
                "kind": "Service",
                "name": f"{application.get('name')}-svc",
                "namespace": application.get("namespace"),
            },
        ]
        return {"resources": resources, "labels": labels}

    def _metrics(self, state: _DiscoveryState) -> _DiscoveryState:
        application = state.get("application", {})
        endpoint = str(application.get("metrics_endpoint") or "").strip()
        return {"metrics_endpoint": endpoint or f"http://{application.get('name')}:{application.get('labels', {}).get('metrics_port', '8000')}"}

    def _classify(self, state: _DiscoveryState) -> _DiscoveryState:
        application = state.get("application", {})
        technology = str(application.get("technology") or "").strip().lower()
        resource_kind = str((state.get("labels") or {}).get("workload_kind") or "Deployment")
        return {"technology": technology or "python-fastapi", "resource_kind": resource_kind.lower()}

    async def run(self, application: ApplicationRegistration) -> ApplicationDiscoveryResult:
        state = await self._graph.ainvoke({"application": application.model_dump(mode="json")})
        return ApplicationDiscoveryResult(
            application_id=application.id,
            tenant_id=application.tenant_id,
            name=application.name,
            environment=application.environment,
            namespace=application.namespace,
            technology=str(state.get("technology") or application.technology),
            resource_kind=str(state.get("resource_kind") or "deployment"),
            discovered_resources=list(state.get("resources") or []),
            metrics_endpoint=str(state.get("metrics_endpoint") or application.metrics_endpoint),
            labels={**application.labels, **dict(state.get("labels") or {})},
        )


class _ValidationState(TypedDict, total=False):
    discovery: dict[str, Any]
    metrics_available: bool
    exporter: str
    technology: str
    metric_families: list[str]
    sample_metrics: list[str]


class ValidationAgent:
    def __init__(self) -> None:
        graph = StateGraph(_ValidationState)
        graph.add_node("probe", self._probe)
        graph.add_node("infer", self._infer)
        graph.set_entry_point("probe")
        graph.add_edge("probe", "infer")
        graph.add_edge("infer", END)
        self._graph = graph.compile()

    async def _probe(self, state: _ValidationState) -> _ValidationState:
        discovery = state.get("discovery", {})
        candidates = _build_metrics_candidates(str(discovery.get("metrics_endpoint") or ""))
        metric_families: list[str] = []
        sample_metrics: list[str] = []
        metrics_available = False
        async with httpx.AsyncClient(timeout=5.0) as client:
            for candidate in candidates:
                try:
                    response = await client.get(candidate)
                except Exception:
                    continue
                if response.status_code >= 400:
                    continue
                body = response.text
                lines = [line.strip() for line in body.splitlines() if line.strip() and not line.startswith("#")]
                if lines:
                    metrics_available = True
                    sample_metrics = lines[:12]
                    metric_families = sorted({line.split("{", 1)[0].split(" ", 1)[0] for line in lines[:120]})
                    break
        return {
            "metrics_available": metrics_available,
            "metric_families": metric_families,
            "sample_metrics": sample_metrics,
        }

    def _infer(self, state: _ValidationState) -> _ValidationState:
        families = [str(item) for item in state.get("metric_families") or []]
        exporter = "custom"
        technology = "unknown"
        if any(name.startswith("jvm_") for name in families):
            technology = "java-spring"
            exporter = "micrometer"
        elif any(name.startswith("http_server_requests") for name in families):
            technology = "spring-boot"
            exporter = "actuator"
        elif any(name.startswith("process_") or name.startswith("python_") for name in families):
            technology = "python-fastapi"
            exporter = "prometheus-client"
        elif any(name.startswith("go_") for name in families):
            technology = "go-service"
            exporter = "promhttp"
        elif any(name.startswith("rabbitmq_") for name in families):
            technology = "rabbitmq"
            exporter = "rabbitmq-exporter"
        elif any(name.startswith("mysql_") for name in families):
            technology = "mysql"
            exporter = "mysqld-exporter"
        return {"technology": technology, "exporter": exporter}

    async def run(self, discovery: ApplicationDiscoveryResult) -> MetricsValidationResult:
        state = await self._graph.ainvoke({"discovery": discovery.model_dump(mode="json")})
        return MetricsValidationResult(
            application_id=discovery.application_id,
            tenant_id=discovery.tenant_id,
            metrics_endpoint=discovery.metrics_endpoint,
            metrics_available=bool(state.get("metrics_available", False)),
            technology=str(state.get("technology") or discovery.technology),
            exporter=str(state.get("exporter") or "custom"),
            labels=discovery.labels,
            metric_families=list(state.get("metric_families") or []),
            sample_metrics=list(state.get("sample_metrics") or []),
        )


def _pick_metric(families: list[str], candidates: list[str], fallback: str) -> str:
    for candidate in candidates:
        if candidate in families:
            return candidate
    return fallback


class RuleGenerationAgent:
    async def run(
        self,
        application: ApplicationRegistration,
        discovery: ApplicationDiscoveryResult,
        validation: MetricsValidationResult,
    ) -> RulesGeneratedResult:
        families = validation.metric_families
        slug = _slug(application.name)
        parsed_endpoint = urlparse(validation.metrics_endpoint)
        target = parsed_endpoint.netloc or parsed_endpoint.path
        metrics_path = parsed_endpoint.path or "/metrics"
        scrape_config = ScrapeConfigSpec(
            job_name=slug,
            targets=[target],
            metrics_path=metrics_path,
            scheme=parsed_endpoint.scheme or "http",
            labels={
                "application": application.name,
                "tenant": application.tenant_id,
                "environment": application.environment,
                "namespace": application.namespace,
            },
        )

        cpu_metric = _pick_metric(families, ["process_cpu_seconds_total", "container_cpu_usage_seconds_total"], "up")
        mem_metric = _pick_metric(families, ["process_resident_memory_bytes", "container_memory_working_set_bytes"], "up")
        latency_metric = _pick_metric(families, ["http_server_requests_seconds_bucket", "request_latency_ms_p95"], "")
        five_xx_metric = _pick_metric(families, ["http_requests_total", "http_server_requests_seconds_count"], "")
        restart_metric = _pick_metric(families, ["kube_pod_container_status_restarts_total"], "")

        alert_rules = [
            PrometheusRuleSpec(
                name=f"{slug}-target-down",
                expr=f'up{{job="{slug}"}} == 0',
                duration="2m",
                severity="critical",
                labels={"team": application.owner_team, "namespace": application.namespace},
                annotations={"summary": f"{application.name} target is down", "description": "Prometheus cannot scrape the application target."},
            ),
            PrometheusRuleSpec(
                name=f"{slug}-cpu-high",
                expr=(f'rate({cpu_metric}[5m]) > 0.85' if cpu_metric != "up" else f'up{{job="{slug}"}} == 0'),
                duration="5m",
                severity="warning",
                labels={"team": application.owner_team},
                annotations={"summary": f"{application.name} CPU usage high", "description": "Sustained CPU saturation detected."},
            ),
            PrometheusRuleSpec(
                name=f"{slug}-memory-high",
                expr=(f'{mem_metric} > 5e+08' if mem_metric != "up" else f'up{{job="{slug}"}} == 0'),
                duration="10m",
                severity="warning",
                labels={"team": application.owner_team},
                annotations={"summary": f"{application.name} memory usage high", "description": "Sustained memory growth detected."},
            ),
        ]
        if latency_metric:
            alert_rules.append(
                PrometheusRuleSpec(
                    name=f"{slug}-latency-p95-high",
                    expr=f'histogram_quantile(0.95, sum(rate({latency_metric}[5m])) by (le)) > 1',
                    duration="5m",
                    severity="critical",
                    labels={"team": application.owner_team},
                    annotations={"summary": f"{application.name} latency elevated", "description": "95th percentile latency exceeded threshold."},
                )
            )
        if five_xx_metric:
            alert_rules.append(
                PrometheusRuleSpec(
                    name=f"{slug}-http-5xx-rate",
                    expr=f'sum(rate({five_xx_metric}{{status=~"5.."}}[5m])) > 0.05',
                    duration="5m",
                    severity="critical",
                    labels={"team": application.owner_team},
                    annotations={"summary": f"{application.name} HTTP 5xx rate high", "description": "Server error rate exceeded threshold."},
                )
            )
        if restart_metric:
            alert_rules.append(
                PrometheusRuleSpec(
                    name=f"{slug}-pod-restarts",
                    expr=f'increase({restart_metric}[10m]) > 0',
                    duration="0m",
                    severity="warning",
                    labels={"team": application.owner_team},
                    annotations={"summary": f"{application.name} pod restarted", "description": "Container or pod restart detected."},
                )
            )

        metric_prefix = _metric_prefix(application.name)
        recording_rules = [
            RecordingRuleSpec(name=f"{metric_prefix}:availability:ratio", expr=f'avg_over_time(up{{job="{slug}"}}[5m])', labels={"application": application.name}),
            RecordingRuleSpec(name=f"{metric_prefix}:request_rate:sum", expr=f'sum(rate(http_requests_total{{job="{slug}"}}[5m]))', labels={"application": application.name}),
            RecordingRuleSpec(name=f"{metric_prefix}:error_rate:sum", expr=f'sum(rate(http_requests_total{{job="{slug}",status=~"5.."}}[5m]))', labels={"application": application.name}),
        ]

        governance_issues: list[str] = []
        if not application.owner_team:
            governance_issues.append("team ownership missing")
        if not application.namespace:
            governance_issues.append("namespace missing")
        if len({rule.name for rule in alert_rules}) != len(alert_rules):
            governance_issues.append("duplicate alert rule names detected")
        governance = {
            "decision": "approved" if not governance_issues else "requires_approval",
            "issues": governance_issues,
            "naming_convention_ok": all(rule.name.startswith(slug) for rule in alert_rules),
            "duplicate_jobs": False,
            "security_labels": bool(application.labels.get("security") or application.labels.get("compliance")),
        }

        return RulesGeneratedResult(
            application_id=application.id,
            tenant_id=application.tenant_id,
            scrape_config=scrape_config,
            alert_rules=alert_rules,
            recording_rules=recording_rules,
            governance=governance,
        )


def render_prometheus_rule_groups(group_name: str, alert_rules: list[PrometheusRuleSpec], recording_rules: list[RecordingRuleSpec]) -> tuple[str, str]:
    def _indent(lines: list[str], depth: int = 0) -> str:
        prefix = "  " * depth
        return "\n".join(f"{prefix}{line}" for line in lines)

    alert_lines = ["groups:", f"- name: {group_name}-alerts", "  rules:"]
    for rule in alert_rules:
        alert_lines.extend([
            f"  - alert: {rule.name}",
            f"    expr: {rule.expr}",
            f"    for: {rule.duration}",
            "    labels:",
            _indent([f"{key}: {value}" for key, value in {**rule.labels, 'severity': rule.severity}.items()], 3),
            "    annotations:",
            _indent([f"{key}: {json.dumps(value)}" for key, value in rule.annotations.items()], 3),
        ])

    recording_lines = ["groups:", f"- name: {group_name}-recording", "  rules:"]
    for rule in recording_rules:
        recording_lines.extend([
            f"  - record: {rule.name}",
            f"    expr: {rule.expr}",
            "    labels:",
            _indent([f"{key}: {value}" for key, value in rule.labels.items()], 3),
        ])
    return "\n".join(alert_lines) + "\n", "\n".join(recording_lines) + "\n"


def write_prometheus_artifacts(application: ApplicationRegistration, rules: RulesGeneratedResult) -> tuple[dict[str, str], dict[str, str]]:
    root = onboarding_root()
    rules_dir = root / "prometheus_rules"
    targets_dir = root / "prometheus_targets"
    rules_dir.mkdir(parents=True, exist_ok=True)
    targets_dir.mkdir(parents=True, exist_ok=True)
    slug = _slug(application.name)
    alert_yaml, recording_yaml = render_prometheus_rule_groups(slug, rules.alert_rules, rules.recording_rules)
    target_payload = [
        {
            "targets": rules.scrape_config.targets,
            "labels": {
                "job": rules.scrape_config.job_name,
                "application": application.name,
                "tenant": application.tenant_id,
                "environment": application.environment,
                "namespace": application.namespace,
                "__metrics_path__": rules.scrape_config.metrics_path,
                "__scheme__": rules.scrape_config.scheme,
            },
        }
    ]
    alert_file = rules_dir / f"{slug}-alerts.yml"
    recording_file = rules_dir / f"{slug}-recording.yml"
    target_file = targets_dir / f"{slug}.json"
    alert_file.write_text(alert_yaml, encoding="utf-8")
    recording_file.write_text(recording_yaml, encoding="utf-8")
    target_file.write_text(json.dumps(target_payload, indent=2), encoding="utf-8")
    return (
        {
            "alert_rules": str(alert_file),
            "recording_rules": str(recording_file),
            "scrape_config": str(target_file),
        },
        {
            "alert_rules": alert_yaml,
            "recording_rules": recording_yaml,
            "scrape_config": json.dumps(target_payload, indent=2),
        },
    )


async def reload_prometheus(prometheus_url: str) -> dict[str, Any]:
    normalized = str(prometheus_url or "").strip().rstrip("/")
    response_payload: dict[str, Any] = {"reload_ok": False, "status_code": None, "message": "prometheus url not configured"}
    if not normalized:
        return response_payload
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.post(f"{normalized}/-/reload")
            response_payload.update({"reload_ok": response.status_code < 400, "status_code": response.status_code, "message": f"reload returned HTTP {response.status_code}"})
        except Exception as exc:
            response_payload.update({"message": f"reload request failed: {exc}"})
    return response_payload


async def validate_prometheus_application(prometheus_url: str, application: ApplicationRegistration) -> MonitoringValidationResult:
    normalized = str(prometheus_url or "").strip().rstrip("/")
    slug = _slug(application.name)
    target_up = False
    alerts_loaded = False
    recording_rules_loaded = False
    service_discovery_ok = False
    details: dict[str, Any] = {"attempts": 0}
    async with httpx.AsyncClient(timeout=10.0) as client:
        if normalized:
            for attempt in range(1, 7):
                details["attempts"] = attempt
                try:
                    targets_response = await client.get(f"{normalized}/api/v1/targets")
                    targets_payload = targets_response.json() if targets_response.headers.get("content-type", "").startswith("application/json") else {}
                    active_targets = ((targets_payload.get("data") or {}).get("activeTargets") or []) if isinstance(targets_payload, dict) else []
                    for target in active_targets:
                        labels = target.get("labels") or {}
                        if str(labels.get("job") or "") == slug:
                            service_discovery_ok = True
                            target_up = str(target.get("health") or "").lower() == "up"
                            break
                    details["targets_checked"] = len(active_targets)
                except Exception as exc:
                    details["targets_error"] = str(exc)
                try:
                    rules_response = await client.get(f"{normalized}/api/v1/rules")
                    rules_payload = rules_response.json() if rules_response.headers.get("content-type", "").startswith("application/json") else {}
                    groups = ((rules_payload.get("data") or {}).get("groups") or []) if isinstance(rules_payload, dict) else []
                    for group in groups:
                        name = str(group.get("name") or "")
                        if name == f"{slug}-alerts":
                            alerts_loaded = True
                        if name == f"{slug}-recording":
                            recording_rules_loaded = True
                    details["rule_groups_checked"] = len(groups)
                except Exception as exc:
                    details["rules_error"] = str(exc)

                if service_discovery_ok and target_up and alerts_loaded and recording_rules_loaded:
                    break
                if attempt < 6:
                    await asyncio.sleep(1)
    return MonitoringValidationResult(
        application_id=application.id,
        tenant_id=application.tenant_id,
        target_up=target_up,
        metrics_available=target_up,
        alerts_loaded=alerts_loaded,
        recording_rules_loaded=recording_rules_loaded,
        service_discovery_ok=service_discovery_ok,
        details=details,
    )


def build_dashboard(application: ApplicationRegistration, validation: MonitoringValidationResult) -> GrafanaDashboardResult:
    slug = _slug(application.name)
    dashboard_uid = f"{slug}-{str(uuid4())[:8]}"
    panels = [
        {"title": "CPU", "type": "timeseries", "expr": f'rate(process_cpu_seconds_total{{job="{slug}"}}[5m])'},
        {"title": "Memory", "type": "timeseries", "expr": f'process_resident_memory_bytes{{job="{slug}"}}'},
        {"title": "Availability", "type": "stat", "expr": f'avg_over_time(up{{job="{slug}"}}[5m])'},
        {"title": "Error Rate", "type": "timeseries", "expr": f'sum(rate(http_requests_total{{job="{slug}",status=~"5.."}}[5m]))'},
        {"title": "Latency", "type": "timeseries", "expr": f'histogram_quantile(0.95, sum(rate(http_server_requests_seconds_bucket{{job="{slug}"}}[5m])) by (le))'},
        {"title": "Restarts", "type": "timeseries", "expr": f'increase(kube_pod_container_status_restarts_total{{namespace="{application.namespace}"}}[10m])'},
    ]
    dashboard = {
        "uid": dashboard_uid,
        "title": f"KaiOps - {application.name}",
        "tags": [application.environment, application.namespace, application.technology],
        "templating": {"list": []},
        "panels": panels,
        "annotations": {"list": []},
        "metadata": validation.model_dump(mode="json"),
    }
    return GrafanaDashboardResult(
        application_id=application.id,
        tenant_id=application.tenant_id,
        dashboard_uid=dashboard_uid,
        title=f"KaiOps - {application.name}",
        url=f"/grafana/d/{dashboard_uid}",
        dashboard=dashboard,
    )