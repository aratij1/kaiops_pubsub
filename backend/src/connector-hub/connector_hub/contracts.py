from __future__ import annotations

from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class ConnectorCategory(StrEnum):
    MONITORING = "monitoring"
    DIAGNOSTIC = "diagnostic"
    REMEDIATION = "remediation"
    CHANGE_INTELLIGENCE = "change_intelligence"
    ITSM = "itsm"
    SOURCE_CICD = "source_code_ci_cd"


class ConnectorMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connector_id: str
    display_name: str
    version: str = "1.0"
    categories: list[ConnectorCategory]
    capabilities: list[str] = Field(default_factory=list)
    secret_provider_schemes: list[str] = Field(default_factory=lambda: ["env", "aws-sm", "azure-kv", "gcp-sm", "vault"])
    implementation_status: str = "metadata_only"


class ConnectionProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str
    project_id: str
    connection_id: str
    connector_id: str
    endpoint: str | None = None
    secret_ref: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class ConnectorResult(BaseModel):
    status: str
    data: dict[str, Any] = Field(default_factory=dict)
    evidence: list[str] = Field(default_factory=list)
    message: str = ""


@runtime_checkable
class ConnectorPlugin(Protocol):
    metadata: ConnectorMetadata

    async def validate_credentials(self, profile: ConnectionProfile) -> ConnectorResult: ...
    async def test_connection(self, profile: ConnectionProfile) -> ConnectorResult: ...
    async def discover_resources(self, profile: ConnectionProfile) -> ConnectorResult: ...
    async def get_health(self, profile: ConnectionProfile, resource_id: str | None = None) -> ConnectorResult: ...
    async def get_metrics(self, profile: ConnectionProfile, query: dict[str, Any]) -> ConnectorResult: ...
    async def get_logs(self, profile: ConnectionProfile, query: dict[str, Any]) -> ConnectorResult: ...
    async def get_traces(self, profile: ConnectionProfile, query: dict[str, Any]) -> ConnectorResult: ...
    async def get_changes(self, profile: ConnectionProfile, query: dict[str, Any]) -> ConnectorResult: ...
    async def execute_capability(self, profile: ConnectionProfile, capability_id: str, parameters: dict[str, Any]) -> ConnectorResult: ...
    async def validate_execution(self, profile: ConnectionProfile, execution: dict[str, Any]) -> ConnectorResult: ...
    async def rollback(self, profile: ConnectionProfile, execution: dict[str, Any]) -> ConnectorResult: ...
    def get_capabilities(self) -> list[str]: ...


class ConnectorOperationUnavailable(NotImplementedError):
    pass


class MetadataOnlyConnector:
    """Fail-closed catalog entry until a certified adapter is registered."""
    def __init__(self, metadata: ConnectorMetadata) -> None:
        self.metadata = metadata

    def get_capabilities(self) -> list[str]:
        return list(self.metadata.capabilities)

    async def _unavailable(self, operation: str) -> ConnectorResult:
        raise ConnectorOperationUnavailable(
            f"{self.metadata.connector_id}.{operation} has no certified runtime adapter"
        )

    async def validate_credentials(self, profile: ConnectionProfile) -> ConnectorResult: return await self._unavailable("validate_credentials")
    async def test_connection(self, profile: ConnectionProfile) -> ConnectorResult: return await self._unavailable("test_connection")
    async def discover_resources(self, profile: ConnectionProfile) -> ConnectorResult: return await self._unavailable("discover_resources")
    async def get_health(self, profile: ConnectionProfile, resource_id: str | None = None) -> ConnectorResult: return await self._unavailable("get_health")
    async def get_metrics(self, profile: ConnectionProfile, query: dict[str, Any]) -> ConnectorResult: return await self._unavailable("get_metrics")
    async def get_logs(self, profile: ConnectionProfile, query: dict[str, Any]) -> ConnectorResult: return await self._unavailable("get_logs")
    async def get_traces(self, profile: ConnectionProfile, query: dict[str, Any]) -> ConnectorResult: return await self._unavailable("get_traces")
    async def get_changes(self, profile: ConnectionProfile, query: dict[str, Any]) -> ConnectorResult: return await self._unavailable("get_changes")
    async def execute_capability(self, profile: ConnectionProfile, capability_id: str, parameters: dict[str, Any]) -> ConnectorResult: return await self._unavailable("execute_capability")
    async def validate_execution(self, profile: ConnectionProfile, execution: dict[str, Any]) -> ConnectorResult: return await self._unavailable("validate_execution")
    async def rollback(self, profile: ConnectionProfile, execution: dict[str, Any]) -> ConnectorResult: return await self._unavailable("rollback")

