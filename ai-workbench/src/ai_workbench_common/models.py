from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from common.models import Alert, BaseEvent, utc_now
from pydantic import BaseModel, ConfigDict, Field


class Context(BaseEvent):
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


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: str
    source: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    timestamp: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)
    content: dict[str, Any] | str | None = None
