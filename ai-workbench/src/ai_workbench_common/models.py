from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from common.models import Alert, BaseEvent, utc_now
from pydantic import BaseModel, ConfigDict, Field, model_validator

from common.tenant_identity import require_tenant_id


class Context(BaseEvent):
    tenant_id: str
    incident_id: UUID
    alert: Alert
    deployment: str | None = None
    related_incidents: list[dict[str, Any]] = Field(default_factory=list)
    runbook: str = ""
    dependency_services: list[str] = Field(default_factory=list)
    recent_changes: list[dict[str, Any]] = Field(default_factory=list)
    cmdb: dict[str, Any] = Field(default_factory=dict)
    cloud: dict[str, Any] = Field(default_factory=dict)
    kubernetes: dict[str, Any] = Field(default_factory=dict)
    observability: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def tenant_matches_alert(self) -> "Context":
        tenant_id = require_tenant_id(self.tenant_id, source="resolution context")
        alert_tenant = require_tenant_id(self.alert.tenant_id, source="context alert identity")
        if tenant_id != alert_tenant:
            raise ValueError("context tenant_id does not match alert tenant identity")
        return self


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: str
    source: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    timestamp: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)
    content: dict[str, Any] | str | None = None
