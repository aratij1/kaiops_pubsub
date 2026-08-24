from __future__ import annotations

from enum import IntEnum, StrEnum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from common.remediation_plan import AutonomyRecommendation
from common.tenant_identity import require_tenant_id


class OnboardingStep(IntEnum):
    PROJECT = 1
    ENVIRONMENTS = 2
    TECHNOLOGY = 3
    OBSERVABILITY = 4
    INCIDENT_SOURCES = 5
    CHANGE_SOURCES = 6
    RESOLUTION_CONNECTIONS = 7
    KNOWLEDGE = 8
    DISCOVERY = 9
    MONITORING_RECOMMENDATIONS = 10
    AUTOMATION_POLICY = 11
    VALIDATION = 12


class OnboardingStatus(StrEnum):
    DRAFT = "DRAFT"
    VALIDATING = "VALIDATING"
    READY = "READY"
    BLOCKED = "BLOCKED"


class ReadinessDimension(StrEnum):
    MONITORING = "Monitoring Ready"
    TELEMETRY = "Telemetry Ready"
    TOPOLOGY = "Topology Ready"
    CHANGE_INTELLIGENCE = "Change Intelligence Ready"
    KNOWLEDGE = "Knowledge Ready"
    RCA = "RCA Ready"
    REMEDIATION = "Remediation Ready"
    VALIDATION = "Validation Ready"


class ProjectDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    business_owner: str
    technical_owner: str
    description: str = ""
    criticality: Literal["low", "medium", "high", "critical"]
    support_timezone: str

    @field_validator("name", "business_owner", "technical_owner", "support_timezone")
    @classmethod
    def require_text(cls, value: str) -> str:
        value = str(value or "").strip()
        if not value:
            raise ValueError("project identity fields are required")
        return value


class EnvironmentDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    production: bool = False
    regions: list[str] = Field(default_factory=list)
    criticality: Literal["low", "medium", "high", "critical"] = "medium"


class ConnectorSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connector_id: str
    profile_id: str
    secret_ref: str
    status: Literal["Connected", "Connection failed", "Permission insufficient", "Secret unavailable", "Pending"] = "Pending"
    evidence_ids: list[str] = Field(default_factory=list)

    @field_validator("secret_ref")
    @classmethod
    def require_opaque_secret(cls, value: str) -> str:
        value = str(value or "").strip()
        allowed = value.startswith(("env://", "vault://", "managed-identity://", "k8s-secret://", "gcp-secret://", "arn:aws:secretsmanager:"))
        allowed = allowed or (value.startswith("https://") and ".vault.azure.net/secrets/" in value)
        if not allowed:
            raise ValueError("connector selection requires an opaque secret_ref")
        return value


class ReadinessSignal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dimension: ReadinessDimension
    ready: bool
    score: int = Field(ge=0, le=100)
    evidence_ids: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def readiness_requires_evidence(self) -> "ReadinessSignal":
        if self.ready and not self.evidence_ids:
            raise ValueError("ready signals require observed evidence")
        if self.ready != (self.score == 100):
            raise ValueError("ready is reserved for fully satisfied readiness criteria")
        return self


class OperationalReadiness(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["kaims.operational-readiness.v1"] = "kaims.operational-readiness.v1"
    dimensions: list[ReadinessSignal]
    overall_score: int = Field(ge=0, le=100)
    production_autonomy_allowed: bool
    blocking_gaps: list[str] = Field(default_factory=list)


class OnboardingControlPlane(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["kaims.onboarding-control-plane.v1"] = "kaims.onboarding-control-plane.v1"
    onboarding_id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    project: ProjectDefinition
    environments: list[EnvironmentDefinition] = Field(default_factory=list)
    steps: dict[str, dict[str, Any]] = Field(default_factory=dict)
    completed_steps: list[OnboardingStep] = Field(default_factory=list)
    current_step: OnboardingStep = OnboardingStep.PROJECT
    status: OnboardingStatus = OnboardingStatus.DRAFT
    version: int = Field(default=1, ge=1)
    readiness: OperationalReadiness | None = None

    @field_validator("tenant_id")
    @classmethod
    def require_tenant(cls, value: str) -> str:
        return require_tenant_id(value, source="onboarding control plane")

    @model_validator(mode="after")
    def completed_steps_are_sequential(self) -> "OnboardingControlPlane":
        completed = sorted(set(int(step) for step in self.completed_steps))
        if completed and completed != list(range(1, max(completed) + 1)):
            raise ValueError("onboarding steps must be completed sequentially")
        return self


_READINESS_WEIGHTS = {
    ReadinessDimension.MONITORING: 15,
    ReadinessDimension.TELEMETRY: 15,
    ReadinessDimension.TOPOLOGY: 15,
    ReadinessDimension.CHANGE_INTELLIGENCE: 10,
    ReadinessDimension.KNOWLEDGE: 10,
    ReadinessDimension.RCA: 10,
    ReadinessDimension.REMEDIATION: 15,
    ReadinessDimension.VALIDATION: 10,
}


def calculate_operational_readiness(signals: list[ReadinessSignal]) -> OperationalReadiness:
    by_dimension = {signal.dimension: signal for signal in signals}
    normalized = [
        by_dimension.get(dimension) or ReadinessSignal(
            dimension=dimension, ready=False, score=0,
            gaps=["No readiness evidence has been collected."],
        )
        for dimension in _READINESS_WEIGHTS
    ]
    overall = round(sum(signal.score * _READINESS_WEIGHTS[signal.dimension] for signal in normalized) / 100)
    mandatory = {
        ReadinessDimension.MONITORING, ReadinessDimension.TELEMETRY, ReadinessDimension.TOPOLOGY,
        ReadinessDimension.RCA, ReadinessDimension.REMEDIATION, ReadinessDimension.VALIDATION,
    }
    blocking = [gap for signal in normalized if signal.dimension in mandatory and not signal.ready for gap in (signal.gaps or [f"{signal.dimension} is not ready."])]
    return OperationalReadiness(
        dimensions=normalized,
        overall_score=overall,
        production_autonomy_allowed=not blocking,
        blocking_gaps=list(dict.fromkeys(blocking)),
    )


def production_auto_execute_allowed(
    control_plane: OnboardingControlPlane,
    capability_modes: dict[str, AutonomyRecommendation | str],
) -> bool:
    requests_auto = any(AutonomyRecommendation(value) == AutonomyRecommendation.AUTO_EXECUTE for value in capability_modes.values())
    has_production = any(environment.production for environment in control_plane.environments)
    if requests_auto and has_production:
        return bool(control_plane.readiness and control_plane.readiness.production_autonomy_allowed)
    return True
