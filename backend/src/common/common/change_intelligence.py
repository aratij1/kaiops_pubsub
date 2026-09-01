from __future__ import annotations

import math
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from common.tenant_identity import require_tenant_id


class ChangeSource(StrEnum):
    GIT_COMMIT = "git_commit"
    PR_MERGE = "pr_merge"
    DEPLOYMENT = "deployment"
    JENKINS = "jenkins"
    ARGOCD = "argocd"
    TERRAFORM = "terraform"
    CONFIGURATION = "configuration"
    FEATURE_FLAG = "feature_flag"
    DATABASE = "database"
    SERVICENOW = "servicenow_change"


class ChangeEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["kaims.change-event.v1"] = "kaims.change-event.v1"
    change_id: str
    tenant_id: str
    source: ChangeSource
    source_event_id: str
    occurred_at: datetime
    ingested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    service: str
    environment: str
    resource_ids: list[str] = Field(default_factory=list)
    topology_resource_ids: list[str] = Field(default_factory=list)
    change_reference: str
    actor_reference: str | None = None
    version: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("tenant_id")
    @classmethod
    def require_tenant(cls, value: str) -> str:
        return require_tenant_id(value, source="change event identity")

    @field_validator("change_id", "source_event_id", "service", "environment", "change_reference")
    @classmethod
    def require_identity(cls, value: str) -> str:
        value = str(value or "").strip()
        if not value:
            raise ValueError("change event identity cannot be empty")
        return value

    @model_validator(mode="after")
    def normalize_time(self) -> "ChangeEvent":
        if self.occurred_at.tzinfo is None or self.ingested_at.tzinfo is None:
            raise ValueError("change timestamps must be timezone-aware")
        return self


class ChangeCorrelationContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str
    incident_started_at: datetime
    service: str
    environment: str
    affected_resource_ids: list[str] = Field(default_factory=list)
    topology_resource_ids: list[str] = Field(default_factory=list)
    correlation_window_seconds: int = Field(default=3600, ge=60, le=604800)


class ChangeCorrelation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["kaims.change-correlation.v1"] = "kaims.change-correlation.v1"
    change_id: str
    change_correlation_score: float = Field(ge=0.0, le=1.0)
    time_score: float = Field(ge=0.0, le=1.0)
    resource_score: float = Field(ge=0.0, le=1.0)
    service_score: float = Field(ge=0.0, le=1.0)
    environment_score: float = Field(ge=0.0, le=1.0)
    topology_score: float = Field(ge=0.0, le=1.0)
    evidence_ids: list[str]
    reason_codes: list[str]
    causal_proof: Literal[False] = False


def correlate_change(change: ChangeEvent, context: ChangeCorrelationContext) -> ChangeCorrelation:
    if change.tenant_id != context.tenant_id:
        raise ValueError("change and incident tenant identities do not match")
    incident_time = context.incident_started_at
    if incident_time.tzinfo is None:
        raise ValueError("incident timestamp must be timezone-aware")
    delta = abs((incident_time - change.occurred_at).total_seconds())
    time_score = math.exp(-3.0 * delta / context.correlation_window_seconds) if delta <= context.correlation_window_seconds else 0.0
    change_resources = set(change.resource_ids)
    affected = set(context.affected_resource_ids)
    resource_score = len(change_resources & affected) / max(1, len(change_resources | affected)) if change_resources and affected else 0.0
    service_score = 1.0 if change.service.casefold() == context.service.casefold() else 0.0
    environment_score = 1.0 if change.environment.casefold() == context.environment.casefold() else 0.0
    topology_matches = set(change.topology_resource_ids) & set(context.topology_resource_ids)
    topology_score = min(1.0, len(topology_matches) / max(1, len(set(change.topology_resource_ids))))
    score = (
        0.35 * time_score
        + 0.25 * resource_score
        + 0.15 * service_score
        + 0.10 * environment_score
        + 0.15 * topology_score
    )
    reasons = []
    if time_score >= 0.5:
        reasons.append("change_within_incident_window")
    if resource_score:
        reasons.append("resource_identity_match")
    if service_score:
        reasons.append("service_match")
    if environment_score:
        reasons.append("environment_match")
    if topology_score:
        reasons.append("topology_path_match")
    return ChangeCorrelation(
        change_id=change.change_id,
        change_correlation_score=round(min(score, 1.0), 4),
        time_score=round(time_score, 4), resource_score=round(resource_score, 4),
        service_score=service_score, environment_score=environment_score,
        topology_score=round(topology_score, 4), evidence_ids=change.evidence_ids,
        reason_codes=reasons or ["no_deterministic_correlation"],
    )


def rank_correlated_changes(
    changes: list[ChangeEvent], context: ChangeCorrelationContext,
) -> list[ChangeCorrelation]:
    return sorted(
        (correlate_change(change, context) for change in changes),
        key=lambda item: (-item.change_correlation_score, item.change_id),
    )
