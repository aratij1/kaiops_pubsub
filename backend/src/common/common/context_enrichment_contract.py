from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
CanonicalEvidenceCategory = Literal[
    "metrics", "logs", "traces", "topology", "changes", "source_code", "knowledge", "tickets",
]


def authorized_enrichment_connectors(
    *, alert_metadata: dict[str, Any], context_payload: dict[str, Any]
) -> set[str]:
    """Return tenant-resolved or canonically proven connectors for gap collection."""

    authorized = {"discovery-mcp", "local-evidence", "vector-db"}
    resolved = alert_metadata.get("resolved_context_connectors", [])
    if isinstance(resolved, list):
        authorized.update(
            str(item.get("provider") or "").strip().lower()
            for item in resolved
            if isinstance(item, dict) and str(item.get("provider") or "").strip()
        )

    metadata = context_payload.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    graph = metadata.get("context_graph")
    graph = graph if isinstance(graph, dict) else {}
    connectors = graph.get("connectors")
    connectors = connectors if isinstance(connectors, dict) else {}
    authorized.update(
        str(name).strip().lower()
        for name, state in connectors.items()
        if str(name).strip()
        and isinstance(state, dict)
        and str(state.get("status") or "").strip().lower() == "completed"
    )
    return authorized


def next_authorized_enrichment_connector(
    *, candidate_connectors: list[str], authorized_connectors: set[str],
    attempted_connectors: set[str] | None = None,
) -> str | None:
    attempted = {str(name).strip().lower() for name in (attempted_connectors or set())}
    authorized = {str(name).strip().lower() for name in authorized_connectors}
    return next(
        (
            name for name in candidate_connectors
            if str(name).strip().lower() in authorized
            and str(name).strip().lower() not in attempted
        ),
        None,
    )


class EvidenceRecord(BaseModel):
    """Canonical governed evidence shared by collection, context, RCA, and APIs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_id: str = Field(min_length=1)
    requirement_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    incident_id: str = Field(min_length=1)
    category: CanonicalEvidenceCategory
    source_id: str = Field(min_length=1)
    connector: str = Field(min_length=1)
    source_reference: str = Field(min_length=1)
    service: str | None = None
    resource: str | None = None
    project_id: str | None = None
    observed_at: datetime
    collected_at: datetime
    observation_window_start: datetime | None = None
    observation_window_end: datetime | None = None
    freshness: Literal["fresh", "cached", "stale"]
    content: dict[str, Any]
    provenance: dict[str, Any]
    current_observation: bool
    contradiction_status: str | None = None

    @model_validator(mode="after")
    def validate_binding(self) -> EvidenceRecord:
        UUID(self.incident_id)
        UUID(self.requirement_id)
        if self.observation_window_start and self.observation_window_end:
            if self.observation_window_end < self.observation_window_start:
                raise ValueError("observation window end precedes start")
        return self


class ConnectorNormalization(BaseModel):
    model_config = ConfigDict(extra="forbid")

    records: list[EvidenceRecord]
    metadata: dict[str, Any]
    rejected: list[dict[str, Any]] = Field(default_factory=list)


_CANONICAL_CATEGORY = {
    "metrics": "metrics", "logs": "logs", "traces": "traces",
    "topology": "topology",
    "deployment": "changes", "change": "changes", "source_code": "source_code",
    "runbook": "knowledge", "ticket": "tickets",
}


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=UTC)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _stable_evidence_id(
    *, requirement: EvidenceRequirement, connector: str, source_reference: str,
    observation_identity: Any, content: dict[str, Any],
) -> str:
    material = json.dumps({
        "tenant_id": requirement.tenant_id,
        "incident_id": str(requirement.incident_id),
        "requirement_id": str(requirement.requirement_id),
        "connector": connector,
        "source_reference": source_reference,
        "observation_identity": observation_identity,
        "content_digest": hashlib.sha256(
            json.dumps(content, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest(),
    }, sort_keys=True, separators=(",", ":"), default=str)
    return f"EVD-{hashlib.sha256(material.encode()).hexdigest()}"


def normalize_connector_response(
    *, raw_response: dict[str, Any], requirement: EvidenceRequirement,
    incident: Incident, connector: str, collected_at: datetime,
) -> ConnectorNormalization:
    """Normalize a raw connector wrapper without discarding wrapper provenance."""
    now = collected_at if collected_at.tzinfo else collected_at.replace(tzinfo=UTC)
    wrapper = _redact_secrets(dict(raw_response))
    provenance = dict(wrapper.get("provenance") or {})
    query = str(wrapper.get("query") or provenance.get("query") or "").strip()
    endpoint = str(
        wrapper.get("endpoint") or wrapper.get("endpoint_identity")
        or provenance.get("endpoint") or connector
    ).strip()
    window_start_raw = wrapper.get("observation_window_start") or provenance.get("observation_window_start")
    window_end_raw = wrapper.get("observation_window_end") or provenance.get("observation_window_end")
    window_start = _parse_timestamp(window_start_raw) if window_start_raw is not None else None
    window_end = _parse_timestamp(window_end_raw) if window_end_raw is not None else None
    category = _CANONICAL_CATEGORY.get(requirement.category)
    if category is None:
        return ConnectorNormalization(
            records=[], metadata={"connector": connector, "endpoint": endpoint, "query": query},
            rejected=[{"code": "UNSUPPORTED_EVIDENCE_CATEGORY", "category": requirement.category}],
        )
    if requirement.tenant_id != incident.tenant_id or requirement.incident_id != incident.id:
        return ConnectorNormalization(
            records=[], metadata={"connector": connector, "endpoint": endpoint, "query": query},
            rejected=[{"code": "EVIDENCE_BINDING_MISMATCH"}],
        )
    raw_records = (
        wrapper.get("series") or wrapper.get("records") or wrapper.get("evidence")
        or wrapper.get("matches") or []
    )
    if not isinstance(raw_records, list):
        raw_records = []
    if category == "topology" and not raw_records and any(
        wrapper.get(field) not in (None, "", [], {})
        for field in ("dependencies", "owner_team", "tier", "service", "resource")
    ):
        # CMDB connectors commonly return one service-inventory document
        # rather than a records envelope. Preserve that attributable response
        # as a single topology observation.
        raw_records = [wrapper]
    normalized: list[EvidenceRecord] = []
    rejected: list[dict[str, Any]] = []
    if category == "metrics":
        source_reference = f"prometheus://{endpoint}/query?expr={query}"
        for index, raw in enumerate(raw_records):
            if not isinstance(raw, dict):
                rejected.append({"code": "INVALID_RECORD_TYPE", "record_index": index})
                continue
            labels = raw.get("metric") if isinstance(raw.get("metric"), dict) else {}
            metric_name = str(labels.get("__name__") or "").strip()
            samples_raw = raw.get("values") if isinstance(raw.get("values"), list) else []
            if not samples_raw and isinstance(raw.get("value"), list):
                samples_raw = [raw["value"]]
            samples: list[dict[str, Any]] = []
            for sample_index, sample in enumerate(samples_raw):
                if not isinstance(sample, (list, tuple)) or len(sample) != 2:
                    rejected.append({"code": "INVALID_PROMETHEUS_SAMPLE", "record_index": index,
                                     "sample_index": sample_index})
                    continue
                try:
                    observed = _parse_timestamp(sample[0])
                except (TypeError, ValueError, OSError):
                    rejected.append({"code": "INVALID_OBSERVATION_TIMESTAMP", "record_index": index,
                                     "sample_index": sample_index})
                    continue
                samples.append({"timestamp": observed.isoformat(), "value": str(sample[1])})
            if not metric_name or not samples:
                rejected.append({"code": "PROMETHEUS_SERIES_INCOMPLETE", "record_index": index})
                continue
            content = {"metric_name": metric_name, "labels": dict(labels), "samples": samples,
                       "result_type": "matrix" if "values" in raw else "vector"}
            observed_at = max(_parse_timestamp(sample["timestamp"]) for sample in samples)
            evidence_id = _stable_evidence_id(
                requirement=requirement, connector=connector, source_reference=source_reference,
                observation_identity={"labels": labels, "samples": samples}, content=content,
            )
            normalized.append(EvidenceRecord(
                evidence_id=evidence_id, requirement_id=str(requirement.requirement_id),
                tenant_id=requirement.tenant_id, incident_id=str(incident.id), category="metrics",
                source_id=endpoint, connector=connector, source_reference=source_reference,
                service=str(labels.get("service") or incident.service or "") or None,
                resource=str(labels.get("instance") or "") or None,
                project_id=str(labels.get("project_id") or "") or None,
                observed_at=observed_at, collected_at=now,
                observation_window_start=window_start, observation_window_end=window_end,
                freshness="fresh" if abs((now - observed_at).total_seconds()) <= 900 else "stale",
                content=content,
                provenance={**provenance, "query": query, "endpoint": endpoint,
                            "raw_result_type": "matrix" if "values" in raw else "vector"},
                current_observation=True, contradiction_status=None,
            ))
    else:
        required_fields = {
            "logs": ("message", "log"),
            "traces": ("trace_id", "span_id", "spans"),
            "topology": ("dependencies", "owner_team", "tier", "service", "resource"),
            "changes": ("change_id", "deployment_id", "commit_sha"),
            "source_code": ("commit_sha", "path", "repository"),
            "knowledge": ("document_id", "version"),
            "tickets": ("issue_key", "comment_id"),
        }
        for index, raw in enumerate(raw_records):
            if not isinstance(raw, dict):
                rejected.append({"code": "INVALID_RECORD_TYPE", "record_index": index})
                continue
            if category == "knowledge":
                raw = {
                    **raw,
                    "version": raw.get("version") or raw.get("document_version") or raw.get("content_version"),
                    "approved": raw.get("approved") is True
                    or str(raw.get("review_status") or "").strip().lower() == "approved",
                    "source_reference": raw.get("source_reference") or raw.get("source_ref"),
                }
            if not any(raw.get(field) not in (None, "", [], {}) for field in required_fields[category]):
                rejected.append({"code": "EVIDENCE_REQUIRED_FIELD_MISSING", "record_index": index,
                                 "category": category})
                continue
            if category == "knowledge" and raw.get("approved") is not True:
                rejected.append({"code": "KNOWLEDGE_NOT_APPROVED", "record_index": index})
                continue
            source_reference = str(
                raw.get("source_reference") or raw.get("url") or raw.get("uri")
                or raw.get("repository_url") or ""
            ).strip()
            if category == "topology" and not source_reference:
                source_reference = f"cmdb://{endpoint}/service/{incident.service}"
            if not source_reference:
                rejected.append({"code": "EVIDENCE_SOURCE_REFERENCE_MISSING", "record_index": index})
                continue
            observed_raw = (
                raw.get("observed_at") or raw.get("timestamp") or raw.get("updated_at")
                or raw.get("created_at") or window_end_raw or now
            )
            try:
                observed_at = _parse_timestamp(observed_raw)
            except (TypeError, ValueError, OSError):
                rejected.append({"code": "INVALID_OBSERVATION_TIMESTAMP", "record_index": index})
                continue
            content = {
                key: value for key, value in raw.items()
                if key not in {"source_reference", "url", "uri", "repository_url", "provenance"}
            }
            identity = {
                key: raw.get(key) for key in (
                    "trace_id", "span_id", "change_id", "deployment_id", "commit_sha",
                    "document_id", "version", "issue_key", "comment_id", "timestamp",
                ) if raw.get(key) not in (None, "")
            } or {"source_reference": source_reference, "index": index}
            evidence_id = _stable_evidence_id(
                requirement=requirement, connector=connector, source_reference=source_reference,
                observation_identity=identity, content=content,
            )
            normalized.append(EvidenceRecord(
                evidence_id=evidence_id, requirement_id=str(requirement.requirement_id),
                tenant_id=requirement.tenant_id, incident_id=str(incident.id), category=category,
                source_id=endpoint, connector=connector, source_reference=source_reference,
                service=str(raw.get("service") or incident.service or "") or None,
                resource=str(raw.get("resource") or "") or None,
                project_id=str(raw.get("project_id") or "") or None,
                observed_at=observed_at, collected_at=now,
                observation_window_start=window_start, observation_window_end=window_end,
                freshness="fresh" if abs((now - observed_at).total_seconds()) <= 900 else "stale",
                content=content, provenance={**provenance, **dict(raw.get("provenance") or {}),
                                             "endpoint": endpoint},
                current_observation=bool(raw.get("current_observation", True)),
                contradiction_status=raw.get("contradiction_status"),
            ))
    return ConnectorNormalization(
        records=normalized,
        metadata={"connector": connector, "endpoint": endpoint, "query": query,
                  "observation_window_start": window_start, "observation_window_end": window_end},
        rejected=rejected,
    )
RequirementStatus = Literal[
    "identified",
    "scheduled",
    "collecting",
    "collected",
    "blocked",
    "assignment_blocked",
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
        if not normalized or normalized.lower() in {
            "admin", "operator", "unknown", "incident-owner", "incident_owner", "unassigned",
        }:
            raise ValueError("HITL assignees must be explicit governed identities")
        return normalized


class HitlAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    incident_id: UUID
    assignee: str
    assignment_type: Literal["user", "group"]
    source: Literal[
        "incident_assignment",
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
    allow_manual_claim: bool = False
    responder_role: str | None = Field(default=None, max_length=128)


class HumanEvidenceJiraRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    incident_id: UUID
    request_id: UUID
    requirement_id: UUID
    assignee_id: str = Field(min_length=1, max_length=255)
    due_at: datetime
    requested_evidence: str = Field(min_length=1, max_length=4000)
    reason: str = Field(min_length=1, max_length=4000)
    kaims_deep_link: str = Field(pattern=r"^https?://", max_length=1536)


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
    "dependency": "topology",
    "dependencies": "topology",
    "code": "source_code",
    "tickets": "ticket",
    "jira": "ticket",
    "rag": "runbook",
    "knowledge": "runbook",
    "runbooks": "runbook",
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
        question = " ".join(
            str(gap.get("question") or f"Collect {category} evidence for this incident.").split()
        )
        query_fingerprint = hashlib.sha256(question.casefold().encode()).hexdigest()
        identity = f"{tenant}:{incident}:{version}:{category}:{query_fingerprint}"
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
