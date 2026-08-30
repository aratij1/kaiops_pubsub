from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from common.tenant_identity import require_tenant_id


class ResolutionSelectionV1(BaseModel):
    """Immutable operator selection; deliberately not an executable plan."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["kaims.resolution-selection.v1"] = "kaims.resolution-selection.v1"
    selection_id: UUID
    tenant_id: str
    incident_id: UUID
    recommendation_id: UUID
    rca_version: int = Field(ge=1)
    context_snapshot_id: UUID
    context_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    catalog_option_id: str
    catalog_option_version: str
    selected_by: str
    selected_at: datetime
    status: Literal["selected", "compilation_blocked", "compiled", "superseded"]
    compiled_execution_plan_id: UUID | None = None
    compilation_blocks: list[str] = Field(default_factory=list)

    @field_validator("tenant_id")
    @classmethod
    def verified_tenant(cls, value: str) -> str:
        return require_tenant_id(value, source="resolution selection")

    @field_validator("catalog_option_id", "catalog_option_version", "selected_by")
    @classmethod
    def required_text(cls, value: str) -> str:
        token = str(value or "").strip()
        if not token:
            raise ValueError("resolution selection identity is incomplete")
        return token
