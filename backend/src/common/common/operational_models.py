from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from common.tenant_identity import require_tenant_id


def utc_now() -> datetime:
    return datetime.now(UTC)


class StrictOperationalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ResourceKind(StrEnum):
    TENANT = "tenant"
    PROJECT = "project"
    BUSINESS_APPLICATION = "business_application"
    APPLICATION_SERVICE = "application_service"
    ENVIRONMENT = "environment"
    REGION = "region"
    CLOUD_ACCOUNT = "cloud_account"
    CLUSTER = "cluster"
    NAMESPACE = "namespace"
    WORKLOAD = "workload"
    POD = "pod"
    HOST = "host"
    VM = "vm"
    DATABASE = "database"
    QUEUE = "queue"
    TOPIC = "topic"
    ENDPOINT = "endpoint"
    API = "api"
    DEPENDENCY = "dependency"


class RelationshipType(StrEnum):
    DEPENDS_ON = "DEPENDS_ON"
    RUNS_ON = "RUNS_ON"
    CONNECTS_TO = "CONNECTS_TO"
    READS_FROM = "READS_FROM"
    WRITES_TO = "WRITES_TO"
    PRODUCES_TO = "PRODUCES_TO"
    CONSUMES_FROM = "CONSUMES_FROM"
    MONITORED_BY = "MONITORED_BY"
    OWNED_BY = "OWNED_BY"
    DEPLOYED_BY = "DEPLOYED_BY"
    USES_DATABASE = "USES_DATABASE"
    CALLS_SERVICE = "CALLS_SERVICE"


class RelationshipSource(StrEnum):
    DISCOVERED = "discovered"
    DECLARED = "declared"
    IMPORTED = "imported"
    INFERRED = "inferred"


class Provenance(StrictOperationalModel):
    source: str
    observed_at: datetime = Field(default_factory=utc_now)
    last_verified: datetime | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)

    @field_validator("source")
    @classmethod
    def source_is_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("provenance source is required")
        return value


class OperationalResource(StrictOperationalModel):
    resource_id: str
    tenant_id: str
    project_id: str
    kind: ResourceKind
    display_name: str
    application_id: str | None = None
    environment: str | None = None
    region: str | None = None
    provider: str | None = None
    provider_resource_id: str | None = None
    parent_resource_id: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance

    @field_validator("resource_id", "project_id", "display_name")
    @classmethod
    def stable_identity_fields_are_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("stable resource identity fields are required")
        return value

    @field_validator("tenant_id")
    @classmethod
    def tenant_is_verified(cls, value: str) -> str:
        return require_tenant_id(value, source="operational resource")


class ApplicationService(StrictOperationalModel):
    service_id: str
    resource_id: str
    tenant_id: str
    project_id: str
    application_id: str
    name: str
    criticality: str = "medium"
    technology: list[str] = Field(default_factory=list)


class Environment(StrictOperationalModel):
    environment_id: str
    tenant_id: str
    project_id: str
    name: str
    criticality: str = "non_production"
    production: bool = False


class Dependency(StrictOperationalModel):
    relationship_id: str
    tenant_id: str
    project_id: str
    source_resource_id: str
    target_resource_id: str
    relationship_type: RelationshipType
    relationship_source: RelationshipSource
    provenance: Provenance

    @model_validator(mode="after")
    def inferred_relationships_are_explicitly_bounded(self) -> "Dependency":
        if self.source_resource_id == self.target_resource_id:
            raise ValueError("dependency cannot point to the same resource")
        if self.relationship_source == RelationshipSource.INFERRED and not self.provenance.evidence:
            raise ValueError("inferred relationship requires evidence")
        return self


class ConnectionProfile(StrictOperationalModel):
    connection_id: str
    tenant_id: str
    project_id: str
    connector_id: str
    endpoint: str | None = None
    secret_ref: str | None = None
    mode: str = "read_only"
    metadata: dict[str, Any] = Field(default_factory=dict)


class MonitoringSource(StrictOperationalModel):
    source_id: str
    tenant_id: str
    project_id: str
    connector_id: str
    signal_types: list[str] = Field(default_factory=list)
    resource_ids: list[str] = Field(default_factory=list)


class RemediationCapability(StrictOperationalModel):
    capability_id: str
    connector_ids: list[str]
    target_resource_kinds: list[ResourceKind]
    risk_level: str
    input_schema: dict[str, Any] = Field(default_factory=dict)
    dry_run_supported: bool = False
    rollback_capability_id: str | None = None


class OwnershipMetadata(StrictOperationalModel):
    ownership_id: str
    tenant_id: str
    project_id: str
    resource_id: str
    business_owner: str | None = None
    technical_owner: str | None = None
    support_team: str | None = None
    support_timezone: str | None = None


class SLODefinition(StrictOperationalModel):
    slo_id: str
    tenant_id: str
    project_id: str
    resource_id: str
    name: str
    objective: float = Field(ge=0.0, le=100.0)
    indicator: str
    window: str


class ChangeSource(StrictOperationalModel):
    change_source_id: str
    tenant_id: str
    project_id: str
    connector_id: str
    change_types: list[str] = Field(default_factory=list)


class KnowledgeSource(StrictOperationalModel):
    knowledge_source_id: str
    tenant_id: str
    project_id: str
    source_type: str
    connector_id: str | None = None
    uri: str | None = None
    resource_ids: list[str] = Field(default_factory=list)

