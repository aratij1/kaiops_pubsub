from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator

from common.models import Alert, Incident

EvidenceCategory = Literal[
    "metrics",
    "logs",
    "traces",
    "topology",
    "deployment",
    "change",
    "source_code",
    "database",
    "ticket",
    "runbook",
    "ownership",
    "business_impact",
    "validation",
]
RequirementStatus = Literal[
    "identified",
    "scheduled",
    "collecting",
    "collected",
    "blocked",
    "human_requested",
    "answered",
    "expired",
    "cancelled",
]


class EvidenceRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_id: UUID
    tenant_id: str = Field(min_length=1, max_length=128)
    incident_id: UUID
    rca_version: int = Field(ge=1)
    category: EvidenceCategory
    question: str = Field(min_length=1, max_length=2000)
    reason: str = Field(min_length=1, max_length=4000)
    priority: Literal["critical", "high", "medium", "low"]
    collection_mode: Literal["automatic", "connector_required", "human_required"]
    candidate_connectors: list[str] = Field(default_factory=list)
    status: RequirementStatus = "identified"
    retry_count: int = Field(default=0, ge=0)
    retry_after: datetime | None = None
    assigned_to: str | None = None
    jira_issue_key: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class EnrichmentPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    maximum_attempts: int = Field(default=4, ge=1, le=20)
    maximum_duration_seconds: int = Field(default=1800, ge=30, le=86400)
    source_timeout_seconds: int = Field(default=20, ge=1, le=300)
    retry_backoff_seconds: list[int] = Field(default_factory=lambda: [15, 60, 300])
    freshness_refresh_seconds: int = Field(default=300, ge=30, le=86400)
    stop_when_conclusive: bool = True


class EnrichmentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scheduled_requirement_ids: list[UUID] = Field(default_factory=list)
    human_requirement_ids: list[UUID] = Field(default_factory=list)
    blocked_requirement_ids: list[UUID] = Field(default_factory=list)
    idempotency_keys: dict[UUID, str] = Field(default_factory=dict)


class EnrichmentValidationResult(BaseModel):
    accepted: bool
    accepted_evidence: list[dict[str, Any]] = Field(default_factory=list)
    rejected_evidence: list[dict[str, Any]] = Field(default_factory=list)
    rejection_reasons: list[str] = Field(default_factory=list)
    category: EvidenceCategory
    freshness_status: str


_SECRET_KEYS = {"password", "secret", "token", "authorization", "api_key", "apikey", "credential"}
_CATEGORY_MARKERS: dict[str, set[str]] = {
    "metrics": {"metric", "metrics", "prometheus"},
    "logs": {"log", "logs", "opensearch"},
    "traces": {"trace", "traces", "span", "jaeger"},
    "topology": {"topology", "dependency", "cmdb"},
    "deployment": {"deployment", "release", "jenkins", "kubernetes"},
    "change": {"change", "commit"},
    "source_code": {"source_code", "code", "github"},
    "database": {"database", "mysql", "query"},
    "ticket": {"ticket", "jira", "issue"},
    "runbook": {"runbook", "knowledge"},
    "ownership": {"ownership", "owner"},
    "business_impact": {"business_impact", "impact"},
    "validation": {"validation", "health"},
}


def _redact_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if str(key).lower() in _SECRET_KEYS else _redact_secrets(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_secrets(item) for item in value]
    return value


def validate_enrichment_observation(
    requirement: EvidenceRequirement,
    connector_id: str,
    observation: dict[str, Any],
    incident: Incident,
    alert: Alert,
    now: datetime,
) -> EnrichmentValidationResult:
    """Accept only attributable, fresh evidence for the exact declared category."""
    category = requirement.category
    rows: list[dict[str, Any]] = []
    for key in (
        "evidence",
        "records",
        "series",
        "matches",
        "spans",
        "logs",
        "recent_deployments",
        "recent_commits",
        "change_records",
        "dependencies",
    ):
        value = observation.get(key)
        if isinstance(value, list):
            rows.extend(dict(item) for item in value if isinstance(item, dict))
    if not rows and isinstance(observation, dict):
        rows = [dict(observation)]
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    reasons: list[str] = []
    expected_markers = _CATEGORY_MARKERS[category]
    for raw in rows:
        item = _redact_secrets(raw)
        marker = str(
            item.get("category") or item.get("kind") or item.get("source_type") or item.get("source") or connector_id
        ).lower()
        searchable_markers = {marker}
        if not any(expected in token for expected in expected_markers for token in searchable_markers):
            rejected.append(item)
            reasons.append(f"evidence category does not match {category}")
            continue
        tenant = str(item.get("tenant_id") or alert.tenant_id or "")
        service = str(item.get("service") or item.get("resource") or alert.service or "")
        if tenant != requirement.tenant_id or (alert.service and service != str(alert.service)):
            rejected.append(item)
            reasons.append("evidence tenant or service identity does not match")
            continue
        collected_raw = item.get("collected_at") or item.get("timestamp") or item.get("observed_at")
        try:
            collected_at = datetime.fromisoformat(str(collected_raw).replace("Z", "+00:00")) if collected_raw else now
            collected_at = (
                collected_at.replace(tzinfo=UTC) if collected_at.tzinfo is None else collected_at.astimezone(UTC)
            )
        except ValueError:
            rejected.append(item)
            reasons.append("evidence timestamp is invalid")
            continue
        if abs((now.astimezone(UTC) - collected_at).total_seconds()) > 86400:
            rejected.append(item)
            reasons.append("evidence is stale")
            continue
        required = {
            "metrics": bool(item.get("metric_name") or item.get("query"))
            and bool(item.get("value") is not None or item.get("values") or item.get("samples")),
            "logs": bool(item.get("message") or item.get("log") or item.get("records")),
            "traces": bool(item.get("trace_id") or item.get("span_id") or item.get("spans")),
            "runbook": bool(item.get("approved") is True and (item.get("version") or item.get("document_version"))),
        }.get(
            category,
            any(
                value not in (None, "", [], {})
                for key, value in item.items()
                if key not in {"provenance", "_source_status"}
            ),
        )
        if not required:
            rejected.append(item)
            reasons.append(f"{category} evidence is missing required factual fields")
            continue
        normalized = {
            **item,
            "category": category,
            "connector_id": connector_id,
            "tenant_id": requirement.tenant_id,
            "incident_id": str(incident.id),
            "service": service,
            "collected_at": collected_at.isoformat(),
            "source_reference": item.get("source_uri")
            or item.get("uri")
            or item.get("source_reference")
            or item.get("authoritative_source"),
        }
        if not normalized["source_reference"]:
            rejected.append(item)
            reasons.append("authoritative source reference is missing")
            continue
        normalized["evidence_id"] = str(
            item.get("evidence_id") or uuid5(NAMESPACE_URL, json.dumps(normalized, sort_keys=True, default=str))
        )
        normalized["integrity"] = {
            "sha256": hashlib.sha256(json.dumps(normalized, sort_keys=True, default=str).encode()).hexdigest()
        }
        normalized["provenance"] = {
            **(item.get("provenance") if isinstance(item.get("provenance"), dict) else {}),
            "connector_id": connector_id,
        }
        accepted.append(normalized)
    return EnrichmentValidationResult(
        accepted=bool(accepted),
        accepted_evidence=accepted,
        rejected_evidence=rejected,
        rejection_reasons=list(dict.fromkeys(reasons)),
        category=category,
        freshness_status="fresh" if accepted else "rejected",
    )


class HitlRoutingConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_approver_group: str
    l2_group: str
    l3_group: str
    service_owner: str
    escalation_manager: str | None = None
    timezone: str
    business_hours: dict
    severity_sla_minutes: dict[str, int]
    jira_project_key: str
    jira_issue_type: str
    jira_transition_mapping: dict[str, str]
    fallback_assignment_group: str

    @field_validator(
        "default_approver_group",
        "l2_group",
        "l3_group",
        "service_owner",
        "fallback_assignment_group",
    )
    @classmethod
    def reject_placeholder_assignees(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized or normalized.lower() in {"admin", "operator", "unknown"}:
            raise ValueError("HITL assignees must be explicit governed identities")
        return normalized


class HitlAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    incident_id: UUID
    assignee: str
    assignment_type: Literal["user", "group"]
    source: Literal[
        "service_owner",
        "environment_support",
        "application_support",
        "on_call",
        "tenant_fallback",
    ]
    approval_type: str
    due_at: datetime


class TicketClosurePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ownership: Literal["kaims", "human", "external"]
    kaims_may_close: bool
    requires_validation: bool = True
    requires_human_confirmation: bool = False
    reopen_on_regression: bool = True
    stability_window_seconds: int = Field(default=300, ge=0, le=604800)


class HumanEvidenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    response: str = Field(min_length=1, max_length=10000)
    responder_id: str = Field(min_length=1, max_length=255)
    source_reference: str | None = Field(default=None, max_length=1536)
    responded_at: datetime


_REQUIREMENT_CONNECTORS: dict[str, list[str]] = {
    "metrics": ["prometheus"],
    "logs": ["opensearch", "discovery-mcp"],
    "traces": ["jaeger", "discovery-mcp"],
    "topology": ["discovery-mcp", "cmdb"],
    "deployment": ["jenkins", "kubernetes"],
    "change": ["jira", "github"],
    "source_code": ["github"],
    "database": ["discovery-mcp"],
    "ticket": ["jira"],
    "runbook": ["vector-db"],
    "validation": ["prometheus"],
}
_HUMAN_CATEGORIES = {"ownership", "business_impact"}
_CATEGORY_ALIASES = {
    "metric": "metrics",
    "telemetry": "metrics",
    "prometheus": "metrics",
    "log": "logs",
    "opensearch": "logs",
    "trace": "traces",
    "jaeger": "traces",
    "deployments": "deployment",
    "changes": "change",
    "code": "source_code",
    "tickets": "ticket",
    "jira": "ticket",
    "rag": "runbook",
    "knowledge": "runbook",
}


def build_evidence_requirements(
    *,
    tenant_id: str,
    incident_id: UUID | str,
    rca_version: int,
    missing_evidence: list[object],
    now: datetime,
) -> list[EvidenceRequirement]:
    """Create deterministic work items from an RCA's declared evidence gaps.

    This lives in the shared contract package so the resolution service that
    discovers a gap and the context service that fulfils it cannot drift.
    """
    tenant = str(tenant_id or "").strip()
    if not tenant:
        raise ValueError("tenant_id is required to plan evidence")
    incident = UUID(str(incident_id))
    version = max(1, int(rca_version or 1))
    requirements: list[EvidenceRequirement] = []
    seen_requirement_ids: set[UUID] = set()
    valid_categories = set(EvidenceCategory.__args__)
    for raw in missing_evidence or []:
        gap = raw if isinstance(raw, dict) else {}
        token = str(gap.get("category") if gap else raw).strip().lower()
        category = _CATEGORY_ALIASES.get(token, token)
        if category not in valid_categories:
            continue
        connectors = list(gap.get("candidate_connectors") or _REQUIREMENT_CONNECTORS.get(category, []))
        mode = (
            "human_required" if category in _HUMAN_CATEGORIES else ("automatic" if connectors else "connector_required")
        )
        question = str(gap.get("question") or f"Collect {category} evidence for this incident.")
        identity = f"{tenant}:{incident}:{version}:{category}:{question}"
        requirement_id = uuid5(NAMESPACE_URL, identity)
        if requirement_id in seen_requirement_ids:
            continue
        seen_requirement_ids.add(requirement_id)
        requirements.append(
            EvidenceRequirement(
                requirement_id=requirement_id,
                tenant_id=tenant,
                incident_id=incident,
                rca_version=version,
                category=category,
                question=question,
                reason=str(gap.get("reason") or "Required to test the current RCA hypothesis."),
                priority=str(gap.get("priority") or "high"),
                collection_mode=mode,
                candidate_connectors=connectors,
                status="identified",
                created_at=now,
                updated_at=now,
            )
        )
    return requirements


class HitlJiraRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    incident_id: UUID
    service: str
    environment: str
    severity: str
    approval_type: str
    summary: str
    recommendation_id: UUID
    rca_version: int = Field(ge=1)
    context_snapshot_id: UUID
    context_fingerprint: str = Field(min_length=64, max_length=64)
    resolution_selection_id: UUID
    execution_plan_id: UUID
    plan_fingerprint: str = Field(min_length=64, max_length=71)
    risk: str
    rollback_plan: str
    approval_expires_at: datetime
    evidence_summary_url: str
    routing: HitlRoutingConfiguration
    closure_policy: TicketClosurePolicy


class JiraClosureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    incident_id: UUID
    jira_issue_key: str
    transition_id: str
    expected_jira_status: str
    remediation_status: str
    validation_status: str
    required_validators_complete: bool
    alerts_cleared: bool
    stability_window_passed: bool
    rollback_not_active: bool
    critical_contradictions: list[str] = Field(default_factory=list)
    current_plan_matches_approved_plan: bool
    human_confirmation: bool = False


class JiraRegressionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    incident_id: UUID
    jira_issue_key: str
    transition_id: str
    regression_evidence_ids: list[str] = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=2000)
