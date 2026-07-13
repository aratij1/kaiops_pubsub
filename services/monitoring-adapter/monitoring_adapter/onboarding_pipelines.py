from __future__ import annotations

import re
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


_SUPPORTED_PLATFORMS = {
    "prometheus",
    "grafana",
    "datadog",
    "dynatrace",
    "new_relic",
    "splunk",
    "elastic",
    "cloudwatch",
    "azure_monitor",
}


class ProjectSeed(BaseModel):
    project_name: str
    description: str = ""
    business_unit: str = ""
    environment: str = "prod"
    criticality: str = "high"
    sla: str = ""
    support_team: str = ""
    business_owner: str = ""
    technical_owner: str = ""
    technology_stack: list[str] = Field(default_factory=list)
    cloud_provider: str = ""
    region: str = ""
    monitoring_platforms: list[str] = Field(default_factory=list)
    notification_platforms: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _normalize(self) -> "ProjectSeed":
        self.project_name = str(self.project_name or "").strip()
        if not self.project_name:
            raise ValueError("project_name is required")
        self.environment = str(self.environment or "prod").strip().lower()
        self.criticality = str(self.criticality or "high").strip().lower()
        self.business_owner = str(self.business_owner or "").strip()
        self.technical_owner = str(self.technical_owner or "").strip()
        self.support_team = str(self.support_team or "").strip()
        self.region = str(self.region or "").strip()
        self.cloud_provider = str(self.cloud_provider or "").strip().lower()
        self.monitoring_platforms = [
            _normalize_platform(item) for item in self.monitoring_platforms if str(item or "").strip()
        ]
        self.notification_platforms = [str(item or "").strip().lower() for item in self.notification_platforms if str(item or "").strip()]
        return self


class ExistingRulePipelineRequest(BaseModel):
    project: ProjectSeed
    platform: str
    mode: Literal["pull", "push", "bidirectional"] = "bidirectional"
    rules_to_push: list[dict[str, Any]] = Field(default_factory=list)
    connection_profile: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _normalize(self) -> "ExistingRulePipelineRequest":
        self.platform = _normalize_platform(self.platform)
        if self.platform not in _SUPPORTED_PLATFORMS:
            raise ValueError("platform is not supported")
        return self


class NewRuleOnboardingRequest(BaseModel):
    project: ProjectSeed
    monitoring_requirements: list[str] = Field(default_factory=list)
    target_platforms: list[str] = Field(default_factory=list)
    discovery_inputs: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _normalize(self) -> "NewRuleOnboardingRequest":
        self.target_platforms = [
            _normalize_platform(item) for item in self.target_platforms if str(item or "").strip()
        ]
        if not self.target_platforms:
            self.target_platforms = self.project.monitoring_platforms or ["prometheus"]
        unsupported = [item for item in self.target_platforms if item not in _SUPPORTED_PLATFORMS]
        if unsupported:
            raise ValueError(f"unsupported target_platforms: {', '.join(unsupported)}")
        if not self.monitoring_requirements:
            raise ValueError("monitoring_requirements must contain at least one requirement")
        self.monitoring_requirements = [str(item or "").strip() for item in self.monitoring_requirements if str(item or "").strip()]
        return self


class MonitoringAdapter(ABC):
    platform: str

    @abstractmethod
    def validate_connection(self, profile: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def pull_rules(self, project: ProjectSeed) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def generate_rule(self, requirement: str, project: ProjectSeed) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def validate_rule(self, rule: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def deploy_rule(self, rule: dict[str, Any], project: ProjectSeed) -> dict[str, Any]:
        raise NotImplementedError


class GenericMonitoringAdapter(MonitoringAdapter):
    def __init__(self, platform: str) -> None:
        self.platform = _normalize_platform(platform)

    def validate_connection(self, profile: dict[str, Any]) -> dict[str, Any]:
        endpoint = str(profile.get("endpoint_url") or profile.get("url") or "").strip()
        return {
            "ok": bool(endpoint) or self.platform in {"prometheus", "grafana"},
            "message": "connection profile accepted" if endpoint else "using default connector profile",
            "platform": self.platform,
        }

    def pull_rules(self, project: ProjectSeed) -> list[dict[str, Any]]:
        base = slugify(project.project_name)
        return [
            {
                "name": f"{base}_cpu_high_{self.platform}",
                "metric": "cpu_usage_percent",
                "threshold": 80,
                "duration": "5m",
                "severity": "high",
                "aggregation": "avg",
                "labels": {"project": project.project_name, "platform": self.platform},
                "platform": self.platform,
                "expression": _expression_for_platform(self.platform, "cpu_usage_percent", 80, "5m", "avg"),
            },
            {
                "name": f"{base}_latency_p95_{self.platform}",
                "metric": "request_latency_ms_p95",
                "threshold": 2000,
                "duration": "5m",
                "severity": "critical",
                "aggregation": "p95",
                "labels": {"project": project.project_name, "platform": self.platform},
                "platform": self.platform,
                "expression": _expression_for_platform(self.platform, "request_latency_ms_p95", 2000, "5m", "p95"),
            },
        ]

    def generate_rule(self, requirement: str, project: ProjectSeed) -> dict[str, Any]:
        parsed = parse_requirement(requirement)
        name = slugify(f"{project.project_name}-{parsed['metric']}-{parsed['severity']}-{self.platform}")
        return {
            "name": name,
            "platform": self.platform,
            "source_requirement": requirement,
            "metric": parsed["metric"],
            "threshold": parsed["threshold"],
            "duration": parsed["duration"],
            "aggregation": parsed["aggregation"],
            "severity": parsed["severity"],
            "labels": {
                "project": project.project_name,
                "environment": project.environment,
                "criticality": project.criticality,
            },
            "expression": _expression_for_platform(
                self.platform,
                parsed["metric"],
                parsed["threshold"],
                parsed["duration"],
                parsed["aggregation"],
            ),
        }

    def validate_rule(self, rule: dict[str, Any]) -> dict[str, Any]:
        errors: list[str] = []
        threshold = rule.get("threshold")
        metric = str(rule.get("metric") or "").strip()
        severity = str(rule.get("severity") or "").strip().lower()
        if not metric:
            errors.append("metric is required")
        if threshold is None or not isinstance(threshold, (int, float)):
            errors.append("threshold must be numeric")
        elif float(threshold) <= 0:
            errors.append("threshold must be > 0")
        if severity not in {"critical", "high", "warning", "info"}:
            errors.append("severity must be one of critical/high/warning/info")
        return {"valid": not errors, "errors": errors, "platform": self.platform}

    def deploy_rule(self, rule: dict[str, Any], project: ProjectSeed) -> dict[str, Any]:
        return {
            "deployed": True,
            "platform": self.platform,
            "rule_name": str(rule.get("name") or ""),
            "project": project.project_name,
            "deployed_at": datetime.now(timezone.utc).isoformat(),
        }


def adapter_registry() -> dict[str, MonitoringAdapter]:
    return {platform: GenericMonitoringAdapter(platform) for platform in sorted(_SUPPORTED_PLATFORMS)}


def capabilities_catalog() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for platform in sorted(_SUPPORTED_PLATFORMS):
        rows.append(
            {
                "platform": platform,
                "can_pull_rules": platform not in {"grafana"},
                "can_push_rules": True,
                "supports_simulation": True,
                "supports_dashboard_refs": platform in {"grafana", "datadog", "dynatrace", "new_relic"},
                "supports_notification_binding": True,
            }
        )
    return rows


def run_existing_rule_pipeline(payload: ExistingRulePipelineRequest) -> dict[str, Any]:
    adapters = adapter_registry()
    adapter = adapters[payload.platform]

    workflow_id = str(uuid4())
    onboarding_id = str(uuid4())
    project_id = slugify(payload.project.project_name)
    trace_id = str(uuid4())

    connection = adapter.validate_connection(payload.connection_profile)

    pulled_rules: list[dict[str, Any]] = []
    if payload.mode in {"pull", "bidirectional"}:
        pulled_rules = adapter.pull_rules(payload.project)

    push_candidates = payload.rules_to_push
    if payload.mode == "bidirectional":
        push_candidates = [*push_candidates, *pulled_rules]

    deduped: dict[str, dict[str, Any]] = {}
    for rule in push_candidates:
        name = str(rule.get("name") or slugify(str(rule.get("metric") or "rule"))).strip().lower()
        if name:
            deduped[name] = rule

    validation_rows: list[dict[str, Any]] = []
    governance_rows: list[dict[str, Any]] = []
    deployed_rows: list[dict[str, Any]] = []

    if payload.mode in {"push", "bidirectional"}:
        for rule in deduped.values():
            validated = adapter.validate_rule(rule)
            governance = governance_check(rule, validated)
            validation_rows.append({"rule": rule.get("name"), **validated})
            governance_rows.append({"rule": rule.get("name"), **governance})
            if validated.get("valid") and governance.get("approved"):
                deployed_rows.append(adapter.deploy_rule(rule, payload.project))

    result = {
        "pipeline": "existing_rule_sync",
        "workflow_id": workflow_id,
        "onboarding_id": onboarding_id,
        "project_id": project_id,
        "trace_id": trace_id,
        "status": "completed",
        "mode": payload.mode,
        "project": payload.project.model_dump(mode="json"),
        "platform": payload.platform,
        "connection": connection,
        "pulled_rules": pulled_rules,
        "rules_considered_for_push": list(deduped.values()),
        "validation": validation_rows,
        "governance": governance_rows,
        "push_results": deployed_rows,
        "summary": {
            "pulled_count": len(pulled_rules),
            "push_candidate_count": len(deduped),
            "pushed_count": len(deployed_rows),
            "validation_failures": len([item for item in validation_rows if not item.get("valid")]),
            "governance_rejections": len([item for item in governance_rows if not item.get("approved")]),
        },
        "event_contract": build_event_contract(
            event_type="OnboardingRulePipelineExistingCompleted",
            workflow_id=workflow_id,
            onboarding_id=onboarding_id,
            project_id=project_id,
            trace_id=trace_id,
            agent_name="Rule Sync Agent",
            payload={"platform": payload.platform, "mode": payload.mode},
            status="ok",
            confidence=0.88,
        ),
    }
    return result


def run_new_rule_pipeline(payload: NewRuleOnboardingRequest) -> dict[str, Any]:
    adapters = adapter_registry()

    workflow_id = str(uuid4())
    onboarding_id = str(uuid4())
    project_id = slugify(payload.project.project_name)
    trace_id = str(uuid4())

    generated_rules: list[dict[str, Any]] = []
    validation_rows: list[dict[str, Any]] = []
    governance_rows: list[dict[str, Any]] = []
    simulation_rows: list[dict[str, Any]] = []
    knowledge_docs: list[dict[str, Any]] = []

    for requirement in payload.monitoring_requirements:
        for platform in payload.target_platforms:
            adapter = adapters[platform]
            rule = adapter.generate_rule(requirement, payload.project)
            generated_rules.append(rule)

            validated = adapter.validate_rule(rule)
            governance = governance_check(rule, validated)
            simulation = simulate_rule(rule)
            knowledge = generate_knowledge_doc(payload.project, rule, simulation)

            validation_rows.append({"rule": rule.get("name"), "platform": platform, **validated})
            governance_rows.append({"rule": rule.get("name"), "platform": platform, **governance})
            simulation_rows.append({"rule": rule.get("name"), "platform": platform, **simulation})
            knowledge_docs.append(knowledge)

    missing_info = detect_missing_info(payload.project)

    approval_package = {
        "project_summary": {
            "project_name": payload.project.project_name,
            "environment": payload.project.environment,
            "criticality": payload.project.criticality,
            "business_unit": payload.project.business_unit,
        },
        "infrastructure_summary": payload.discovery_inputs,
        "generated_rules_count": len(generated_rules),
        "knowledge_docs_count": len(knowledge_docs),
        "simulation": {
            "avg_false_positive_rate": round(
                sum(float(item.get("false_positive_rate", 0.0)) for item in simulation_rows) / max(1, len(simulation_rows)),
                4,
            ),
            "estimated_alerts_per_day": sum(int(item.get("estimated_alerts_per_day", 0)) for item in simulation_rows),
        },
        "risk_assessment": {
            "governance_rejections": len([item for item in governance_rows if not item.get("approved")]),
            "validation_failures": len([item for item in validation_rows if not item.get("valid")]),
        },
        "missing_information": missing_info,
    }

    deployment_plan = [
        {
            "platform": row["platform"],
            "rule": row["rule"],
            "action": "deploy",
            "requires_approval": True,
        }
        for row in governance_rows
        if row.get("approved")
    ]

    status = "needs-input" if missing_info else "ready-for-approval"

    result = {
        "pipeline": "new_rule_onboarding",
        "workflow_id": workflow_id,
        "onboarding_id": onboarding_id,
        "project_id": project_id,
        "trace_id": trace_id,
        "status": status,
        "project": payload.project.model_dump(mode="json"),
        "target_platforms": payload.target_platforms,
        "requirements": payload.monitoring_requirements,
        "generated_rules": generated_rules,
        "validation": validation_rows,
        "governance": governance_rows,
        "simulation": simulation_rows,
        "knowledge_documents": knowledge_docs,
        "missing_information": missing_info,
        "approval_package": approval_package,
        "deployment_plan": deployment_plan,
        "event_contract": build_event_contract(
            event_type="OnboardingRulePipelineNewCompleted",
            workflow_id=workflow_id,
            onboarding_id=onboarding_id,
            project_id=project_id,
            trace_id=trace_id,
            agent_name="Rule Generation Agent",
            payload={"target_platforms": payload.target_platforms, "requirements": len(payload.monitoring_requirements)},
            status=status,
            confidence=0.82,
        ),
    }
    return result


def find_pipeline_rows(rows: list[dict[str, Any]], workflow_id: str) -> list[dict[str, Any]]:
    normalized = str(workflow_id or "").strip()
    if not normalized:
        return []
    matched: list[dict[str, Any]] = []
    for row in rows:
        payload = row.get("connectivity_payload", {}) if isinstance(row.get("connectivity_payload"), dict) else {}
        if str(payload.get("workflow_id") or "").strip() == normalized:
            matched.append(row)
    return matched


def build_event_contract(
    *,
    event_type: str,
    workflow_id: str,
    onboarding_id: str,
    project_id: str,
    trace_id: str,
    agent_name: str,
    payload: dict[str, Any],
    status: str,
    confidence: float,
) -> dict[str, Any]:
    return {
        "event_id": str(uuid4()),
        "event_type": event_type,
        "workflow_id": workflow_id,
        "onboarding_id": onboarding_id,
        "project_id": project_id,
        "trace_id": trace_id,
        "agent_name": agent_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "v1",
        "payload": payload,
        "status": status,
        "confidence": round(float(confidence), 4),
    }


def parse_requirement(requirement: str) -> dict[str, Any]:
    text = str(requirement or "").strip()
    lowered = text.lower()

    metric = "cpu_usage_percent"
    if "latency" in lowered or "response time" in lowered:
        metric = "request_latency_ms_p95"
    elif "memory" in lowered:
        metric = "memory_usage_percent"
    elif "error" in lowered:
        metric = "error_rate_percent"
    elif "disk" in lowered:
        metric = "disk_usage_percent"

    severity = "warning"
    if "critical" in lowered:
        severity = "critical"
    elif "high" in lowered:
        severity = "high"
    elif "info" in lowered:
        severity = "info"

    threshold = 80.0
    threshold_match = re.search(r"(above|over|greater than|>|>=)\s*(\d+(?:\.\d+)?)", lowered)
    if threshold_match:
        threshold = float(threshold_match.group(2))

    duration = "5m"
    duration_match = re.search(r"for\s*(\d+)\s*(minute|minutes|min|m|hour|hours|h)", lowered)
    if duration_match:
        value = int(duration_match.group(1))
        unit = duration_match.group(2)
        duration = f"{value}h" if unit.startswith("h") else f"{value}m"

    aggregation = "avg"
    if "p95" in lowered or "95th" in lowered:
        aggregation = "p95"
    elif "max" in lowered:
        aggregation = "max"
    elif "sum" in lowered:
        aggregation = "sum"

    return {
        "metric": metric,
        "threshold": threshold,
        "duration": duration,
        "aggregation": aggregation,
        "severity": severity,
    }


def governance_check(rule: dict[str, Any], validation: dict[str, Any]) -> dict[str, Any]:
    name = str(rule.get("name") or "").strip()
    labels = rule.get("labels", {}) if isinstance(rule.get("labels"), dict) else {}
    issues: list[str] = []

    if not validation.get("valid"):
        issues.append("rule failed syntax/semantic validation")
    if len(name) < 8:
        issues.append("rule name is too short for enterprise naming standards")
    if "project" not in labels:
        issues.append("required label 'project' is missing")
    if "severity" not in str(rule.get("severity") or "").lower():
        # Severity is present but this catches malformed values like empty strings.
        if not str(rule.get("severity") or "").strip():
            issues.append("severity is missing")

    confidence = 0.95
    confidence -= min(0.75, len(issues) * 0.2)

    return {
        "approved": not issues,
        "confidence": round(max(0.0, confidence), 4),
        "issues": issues,
        "policy_compliant": not issues,
    }


def simulate_rule(rule: dict[str, Any]) -> dict[str, Any]:
    threshold = float(rule.get("threshold") or 0)
    base_noise = 0.25
    if threshold >= 95:
        base_noise = 0.06
    elif threshold >= 90:
        base_noise = 0.1
    elif threshold >= 80:
        base_noise = 0.16

    false_positive_rate = round(base_noise, 4)
    false_negative_rate = round(max(0.02, 0.18 - base_noise / 2), 4)
    estimated_alerts_per_day = max(1, int(24 * base_noise * 1.6))

    return {
        "false_positive_rate": false_positive_rate,
        "false_negative_rate": false_negative_rate,
        "estimated_alerts_per_day": estimated_alerts_per_day,
        "estimated_noise": "high" if false_positive_rate > 0.2 else ("medium" if false_positive_rate > 0.1 else "low"),
        "recommendation": "increase threshold or duration" if false_positive_rate > 0.2 else "configuration looks stable",
    }


def generate_knowledge_doc(project: ProjectSeed, rule: dict[str, Any], simulation: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    title = f"Runbook - {rule.get('name')}"
    return {
        "document_id": str(uuid4()),
        "version": 1,
        "title": title,
        "project": project.project_name,
        "platform": rule.get("platform"),
        "owner": project.technical_owner or project.support_team or "platform-ops",
        "created_at": now,
        "sections": {
            "alert_description": f"Alert on metric {rule.get('metric')} crossing {rule.get('threshold')} for {rule.get('duration')}",
            "possible_causes": [
                "recent deployment regression",
                "upstream dependency saturation",
                "resource contention",
            ],
            "impact": f"Potential impact to {project.project_name} service availability and SLA",
            "troubleshooting_guide": [
                "Check service health endpoint",
                "Inspect recent deploys and config changes",
                "Review dependency latency and error rates",
            ],
            "diagnostic_commands": [
                "kubectl get pods -n <namespace>",
                "kubectl top pods -n <namespace>",
                "curl -s http://<service>/healthz",
            ],
            "resolution_steps": [
                "scale workload",
                "rollback faulty release",
                "throttle noisy callers",
            ],
            "rollback_steps": [
                "restore previous monitor threshold",
                "disable monitor temporarily if approved",
            ],
            "escalation_matrix": {
                "l1": "operations",
                "l2": project.support_team or "sre",
                "l3": project.technical_owner or "engineering-manager",
            },
            "related_dashboards": [f"{project.project_name}-{rule.get('platform')}-overview"],
            "simulation_summary": simulation,
        },
    }


def detect_missing_info(project: ProjectSeed) -> list[dict[str, str]]:
    missing: list[dict[str, str]] = []
    checks = {
        "business_owner": project.business_owner,
        "technical_owner": project.technical_owner,
        "support_team": project.support_team,
        "region": project.region,
        "monitoring_platforms": ",".join(project.monitoring_platforms),
        "notification_platforms": ",".join(project.notification_platforms),
    }
    for field_name, value in checks.items():
        if not str(value or "").strip():
            missing.append(
                {
                    "field": field_name,
                    "question": f"Project is missing {field_name.replace('_', ' ').title()}. Please provide it to continue.",
                }
            )
    return missing


def _normalize_platform(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "azure": "azure_monitor",
        "azuremonitor": "azure_monitor",
        "cloud_watch": "cloudwatch",
        "newrelic": "new_relic",
    }
    return aliases.get(normalized, normalized)


def slugify(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", str(value or "").strip().lower()).strip("-") or "item"


def _expression_for_platform(platform: str, metric: str, threshold: float, duration: str, aggregation: str) -> str:
    platform = _normalize_platform(platform)
    if platform == "prometheus":
        return f"{aggregation}({metric}[{duration}]) > {threshold}"
    if platform == "datadog":
        return f"avg(last_{duration}):avg:{metric}{{*}} > {threshold}"
    if platform == "new_relic":
        return f"SELECT {aggregation}({metric}) FROM Metric WHERE appName = '{{project}}' SINCE {duration} AGO"
    if platform == "dynatrace":
        return f"timeseries {metric}, {aggregation} over {duration}; alert if > {threshold}"
    if platform == "cloudwatch":
        return f"{metric} {aggregation} {duration} > {threshold}"
    if platform == "azure_monitor":
        return f"{metric} | summarize {aggregation}(value) over {duration} | where value > {threshold}"
    return f"{metric} {aggregation} over {duration} > {threshold}"
