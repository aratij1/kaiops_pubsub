from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid4
from hashlib import sha256
import json

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from common.models import utc_now
from common.tenant_identity import require_tenant_id


class ProviderType(StrEnum):
    SIMULATOR = "simulator"
    AWS = "aws"
    AZURE = "azure"
    GCP = "gcp"
    KUBERNETES = "kubernetes"
    VMWARE = "vmware"
    OPENSTACK = "openstack"
    ON_PREM = "on_prem"
    DATABASE = "database"
    MONITORING = "monitoring"
    ITSM = "itsm"


class ConnectionStatus(StrEnum):
    DRAFT = "draft"
    VALIDATED = "validated"
    FAILED = "failed"
    DISABLED = "disabled"


class DiscoveryStatus(StrEnum):
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"


class ServiceOnboardingState(StrEnum):
    DRAFT = "DRAFT"
    DISCOVERED = "DISCOVERED"
    OBSERVABLE = "OBSERVABLE"
    INCIDENT_READY = "INCIDENT_READY"
    OPERABLE = "OPERABLE"


class ResourceStatus(StrEnum):
    ACTIVE = "active"
    CHANGED = "changed"
    REMOVED = "removed"
    UNKNOWN = "unknown"


class CloudConnectionBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    project_id: str = Field(min_length=1, max_length=128)
    provider_type: ProviderType
    connection_name: str = Field(min_length=1, max_length=255)
    credential_ref: str = Field(default="", max_length=512)
    auth_method: str = Field(default="credential_ref", max_length=64)
    allowed_regions: list[str] = Field(default_factory=list)
    resource_filters: dict[str, Any] = Field(default_factory=dict)
    discovery_scope: dict[str, Any] = Field(default_factory=dict)
    read_capability: bool = True
    write_capability: bool = False
    connection_owner: str = Field(min_length=1, max_length=255)

    @field_validator("tenant_id")
    @classmethod
    def tenant_is_verified(cls, value: str) -> str:
        return require_tenant_id(value, source="cloud operations connection")

    @field_validator("project_id", "connection_name", "connection_owner")
    @classmethod
    def required_text(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("value is required")
        return normalized

    @model_validator(mode="after")
    def credential_reference_required_for_real_provider(self) -> CloudConnectionBase:
        if self.provider_type != ProviderType.SIMULATOR and not self.credential_ref.strip():
            raise ValueError("credential_ref is required for non-simulator connections")
        if self.write_capability and not self.read_capability:
            raise ValueError("write-capable connections must also declare read capability")
        return self


class CloudConnectionCreate(CloudConnectionBase):
    pass


class CloudConnection(CloudConnectionBase):
    id: UUID = Field(default_factory=uuid4)
    status: ConnectionStatus = ConnectionStatus.DRAFT
    failure_reason: str | None = None
    last_health_check_at: datetime | None = None
    last_discovery_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    version: int = 1


class CapabilityManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: ProviderType
    connector_version: str
    resource_types: list[str] = Field(default_factory=list)
    supported_read_operations: list[str] = Field(default_factory=list)
    supported_write_operations: list[str] = Field(default_factory=list)
    required_permission_scopes: list[str] = Field(default_factory=list)
    risk_classification: Literal["low", "medium", "high", "critical"] = "low"
    dry_run_support: bool = True
    rollback_support: bool = False
    validation_support: bool = True
    health_status: str = "unknown"


class ConnectionValidationResult(BaseModel):
    status: Literal["validated", "failed"]
    connectivity_ok: bool
    authentication_ok: bool
    requested_permissions: list[str] = Field(default_factory=list)
    granted_permissions: list[str] = Field(default_factory=list)
    missing_permissions: list[str] = Field(default_factory=list)
    read_only: bool = True
    message: str = ""
    checked_at: datetime = Field(default_factory=utc_now)


class DiscoveredResource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    project_id: str
    service_id: str
    environment: str
    provider: ProviderType
    provider_account_id: str
    region: str
    provider_resource_id: str
    resource_type: str
    display_name: str
    status: ResourceStatus = ResourceStatus.ACTIVE
    tags: dict[str, Any] = Field(default_factory=dict)
    owner: str | None = None
    configuration: dict[str, Any] = Field(default_factory=dict)
    health: dict[str, Any] = Field(default_factory=dict)
    cost: dict[str, Any] = Field(default_factory=dict)
    discovered_at: datetime = Field(default_factory=utc_now)

    @field_validator("tenant_id")
    @classmethod
    def resource_tenant_is_verified(cls, value: str) -> str:
        return require_tenant_id(value, source="cloud operations resource")


class ResourceRelationship(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    project_id: str
    source_resource_id: str
    target_resource_id: str
    relationship_type: str
    source: str
    confidence: float = Field(ge=0.0, le=1.0)
    owner_confirmed: bool = False
    discovered_at: datetime = Field(default_factory=utc_now)

    @field_validator("tenant_id")
    @classmethod
    def relationship_tenant_is_verified(cls, value: str) -> str:
        return require_tenant_id(value, source="cloud operations topology")


class DiscoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    project_id: str
    service_id: str = Field(min_length=1, max_length=128)
    environment: str = Field(default="prod", min_length=1, max_length=64)
    actor: str = Field(default="system", max_length=255)

    @field_validator("tenant_id")
    @classmethod
    def discovery_tenant_is_verified(cls, value: str) -> str:
        return require_tenant_id(value, source="cloud operations discovery")


class DiscoveryResult(BaseModel):
    run_id: UUID
    status: DiscoveryStatus
    resources: list[DiscoveredResource] = Field(default_factory=list)
    relationships: list[ResourceRelationship] = Field(default_factory=list)
    message: str = ""


class ServiceResourceMappingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    project_id: str
    service_id: str
    environment: str = "prod"
    resource_ids: list[str]
    owner: str = "system"

    @field_validator("tenant_id")
    @classmethod
    def mapping_tenant_is_verified(cls, value: str) -> str:
        return require_tenant_id(value, source="cloud operations service mapping")


class ServiceOnboardingProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    project_id: str = Field(min_length=1, max_length=128)
    service_id: str = Field(min_length=1, max_length=128)
    environment: str = Field(default="prod", min_length=1, max_length=64)
    template_id: str = Field(default="kubernetes_microservice", max_length=128)
    business_criticality: Literal["low", "medium", "high", "critical"] = "medium"
    owners: list[str] = Field(default_factory=list)
    support_groups: list[str] = Field(default_factory=list)
    connection_ids: list[str] = Field(default_factory=list)
    monitoring_sources: list[str] = Field(default_factory=list)
    log_sources: list[str] = Field(default_factory=list)
    metric_sources: list[str] = Field(default_factory=list)
    trace_sources: list[str] = Field(default_factory=list)
    event_sources: list[str] = Field(default_factory=list)
    slos: list[dict[str, Any]] = Field(default_factory=list)
    business_kpis: list[dict[str, Any]] = Field(default_factory=list)
    change_sources: list[str] = Field(default_factory=list)
    knowledge_refs: list[str] = Field(default_factory=list)
    diagnostic_capabilities: list[str] = Field(default_factory=list)
    remediation_capabilities: list[str] = Field(default_factory=list)
    validation_rules: list[str] = Field(default_factory=list)
    escalation_policies: list[str] = Field(default_factory=list)
    hitl_policy: dict[str, Any] = Field(default_factory=dict)
    dependencies: list[str] = Field(default_factory=list)
    resource_ids: list[str] = Field(default_factory=list)
    topology: list[dict[str, Any]] = Field(default_factory=list)
    approved_capabilities: list[str] = Field(default_factory=list)
    prohibited_operations: list[str] = Field(default_factory=list)
    maintenance_windows: list[dict[str, Any]] = Field(default_factory=list)
    change_freeze_periods: list[dict[str, Any]] = Field(default_factory=list)
    rollback_procedures: list[str] = Field(default_factory=list)
    runbook_owners: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    actor: str = Field(default="system", max_length=255)

    @field_validator("tenant_id")
    @classmethod
    def onboarding_tenant_is_verified(cls, value: str) -> str:
        return require_tenant_id(value, source="cloud operations service onboarding")

    @field_validator("owners", "support_groups", "connection_ids", "monitoring_sources", "log_sources", "metric_sources", "trace_sources", "event_sources", "change_sources", "knowledge_refs", "diagnostic_capabilities", "remediation_capabilities", "validation_rules", "escalation_policies", "dependencies", "resource_ids", "approved_capabilities", "prohibited_operations", "rollback_procedures", "runbook_owners")
    @classmethod
    def compact_string_list(cls, values: list[str]) -> list[str]:
        return [item for item in (str(value).strip() for value in values) if item]


class PlanAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_type: str = Field(min_length=1, max_length=128)
    resource_id: str = Field(min_length=1, max_length=128)
    parameters: dict[str, Any] = Field(default_factory=dict)
    rollback_action: str | None = Field(default=None, max_length=128)


class PlanCompileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    project_id: str = Field(min_length=1, max_length=128)
    service_id: str = Field(min_length=1, max_length=128)
    environment: str = Field(default="prod", min_length=1, max_length=64)
    intent: str = Field(min_length=1, max_length=512)
    actions: list[PlanAction] = Field(min_length=1, max_length=25)
    actor: str = Field(default="system", max_length=255)

    @field_validator("tenant_id")
    @classmethod
    def plan_tenant_is_verified(cls, value: str) -> str:
        return require_tenant_id(value, source="cloud operations plan")


class CompiledPlan(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    project_id: str
    service_id: str
    environment: str
    intent: str
    actions: list[PlanAction]
    risk_level: Literal["low", "medium", "high", "critical"]
    requires_approval: bool
    checksum: str
    status: Literal["compiled"] = "compiled"
    compiled_by: str
    compiled_at: datetime = Field(default_factory=utc_now)

    @classmethod
    def from_request(cls, request: PlanCompileRequest, *, risk_level: Literal["low", "medium", "high", "critical"]) -> "CompiledPlan":
        canonical = {
            "tenant_id": request.tenant_id,
            "project_id": request.project_id,
            "service_id": request.service_id,
            "environment": request.environment,
            "intent": request.intent,
            "actions": [action.model_dump(mode="json") for action in request.actions],
        }
        checksum = sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return cls(**canonical, risk_level=risk_level, requires_approval=request.environment.lower() == "prod" or risk_level in {"high", "critical"}, checksum=checksum, compiled_by=request.actor)


class SimulationGate(BaseModel):
    gate: str
    passed: bool
    message: str


class PlanSimulation(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    plan_id: UUID
    tenant_id: str
    verdict: Literal["passed", "blocked"]
    gates: list[SimulationGate]
    simulated_by: str
    simulated_at: datetime = Field(default_factory=utc_now)


class PlanApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: Literal["approved", "rejected"]
    reason: str = Field(min_length=1, max_length=1000)
    actor: str = Field(min_length=1, max_length=255)

    @field_validator("tenant_id")
    @classmethod
    def approval_tenant_is_verified(cls, value: str) -> str:
        return require_tenant_id(value, source="cloud plan approval")


class PlanExecutionResult(BaseModel):
    execution_id: UUID
    plan_id: UUID
    status: Literal["succeeded", "failed", "rolled_back", "rollback_failed", "validation_failed"]
    provider: ProviderType
    action_results: list[dict[str, Any]] = Field(default_factory=list)
    validation: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class ExecutionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str
    project_id: str
    environment: str = "prod"
    allowed_providers: list[ProviderType] = Field(default_factory=lambda: [ProviderType.SIMULATOR])
    allowed_actions: list[str] = Field(default_factory=list)
    maximum_risk: Literal["low", "medium", "high", "critical"] = "high"
    require_rollback: bool = True
    require_maintenance_window: bool = True
    enabled: bool = True
    actor: str = "system"

    @field_validator("tenant_id")
    @classmethod
    def policy_tenant_is_verified(cls, value: str) -> str:
        return require_tenant_id(value, source="cloud execution policy")


class MaintenanceWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str
    project_id: str
    environment: str = "prod"
    starts_at: datetime
    ends_at: datetime
    reason: str = Field(min_length=1, max_length=512)
    actor: str = "system"

    @model_validator(mode="after")
    def valid_window(self) -> "MaintenanceWindow":
        self.tenant_id = require_tenant_id(self.tenant_id, source="cloud maintenance window")
        if self.ends_at <= self.starts_at:
            raise ValueError("maintenance window must end after it starts")
        return self
