from __future__ import annotations

from typing import Any
from uuid import uuid4

from api_gateway.modules.users.models import SystemRole
from api_gateway.modules.users.permissions import AuthContext, current_auth_context, require_roles
from common.config import get_settings
from common.database import AuditLogRecord, HumanCorrectionRecord
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select

router = APIRouter(tags=["human-corrections"])
settings = get_settings()


class TriageCorrectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_type: str = Field(default="alert", min_length=1, max_length=64)
    entity_id: str = Field(min_length=1, max_length=255)
    correction_type: str = Field(default="severity", min_length=1, max_length=64)
    original_payload: dict[str, Any] = Field(default_factory=dict)
    corrected_payload: dict[str, Any]
    reason: str = Field(min_length=10, max_length=4000)

    @field_validator("entity_type")
    @classmethod
    def validate_entity_type(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in {"alert", "ticket", "incident", "rca", "impact", "recommendation", "runbook", "evidence_draft"}: raise ValueError("unsupported entity_type")
        return value

    @field_validator("correction_type")
    @classmethod
    def validate_correction_type(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in {"severity", "priority", "category", "ownership", "rca", "impact", "diagnostic", "resolution", "validation", "rollback", "recommendation"}: raise ValueError("unsupported correction_type")
        return value

    @field_validator("entity_id", "reason")
    @classmethod
    def strip_required_text(cls, value: str) -> str: return value.strip()


@router.post("/triage/corrections", status_code=201)
@router.post("/api/v1/triage/corrections", status_code=201, include_in_schema=False)
async def create_correction(request: Request, payload: TriageCorrectionCreate, auth: AuthContext = Depends(require_roles(SystemRole.ADMINISTRATOR.value, SystemRole.L3_ENGINEER.value, SystemRole.L2_ENGINEER.value))) -> dict[str, Any]:
    factory = getattr(request.app.state, "session_factory", None)
    if not settings.database_enabled or factory is None: raise HTTPException(status_code=503, detail="Correction persistence is unavailable")
    actor = str(auth.username or auth.email or auth.user_id).strip()
    async with factory() as session:
        prior = await session.scalar(select(func.max(HumanCorrectionRecord.version)).where(HumanCorrectionRecord.tenant_id == auth.tenant_id, HumanCorrectionRecord.entity_type == payload.entity_type, HumanCorrectionRecord.entity_id == payload.entity_id))
        version = int(prior or 0) + 1
        row = HumanCorrectionRecord(id=uuid4(), tenant_id=auth.tenant_id, entity_type=payload.entity_type, entity_id=payload.entity_id, correction_type=payload.correction_type, original_payload=payload.original_payload, corrected_payload=payload.corrected_payload, reason=payload.reason, actor=actor, actor_role=auth.role, status="recorded", version=version)
        session.add(row)
        session.add(AuditLogRecord(tenant_id=auth.tenant_id, actor=actor, action="triage.correction.recorded", resource_type=payload.entity_type, resource_id=payload.entity_id, payload={"correction_id": str(row.id), "correction_type": payload.correction_type, "reason": payload.reason, "actor_role": auth.role, "version": version}))
        await session.commit()
    return {"correction": {**payload.model_dump(), "id": str(row.id), "tenant_id": auth.tenant_id, "actor": actor, "actor_role": auth.role, "status": "recorded", "version": version}}


@router.get("/triage/corrections")
@router.get("/api/v1/triage/corrections", include_in_schema=False)
async def list_corrections(request: Request, entity_id: str = "", correction_type: str = "", limit: int = 50, auth: AuthContext = Depends(current_auth_context)) -> dict[str, Any]:
    factory = getattr(request.app.state, "session_factory", None)
    if not settings.database_enabled or factory is None: raise HTTPException(status_code=503, detail="Correction persistence is unavailable")
    statement = select(HumanCorrectionRecord).where(HumanCorrectionRecord.tenant_id == auth.tenant_id)
    if entity_id.strip(): statement = statement.where(HumanCorrectionRecord.entity_id == entity_id.strip())
    if correction_type.strip(): statement = statement.where(HumanCorrectionRecord.correction_type == correction_type.strip().lower())
    async with factory() as session: rows = (await session.execute(statement.order_by(HumanCorrectionRecord.created_at.desc()).limit(max(1, min(limit, 200))))).scalars().all()
    return {"rows": [{"id": str(row.id), "entity_type": row.entity_type, "entity_id": row.entity_id, "correction_type": row.correction_type, "original_payload": row.original_payload or {}, "corrected_payload": row.corrected_payload or {}, "reason": row.reason, "actor": row.actor, "actor_role": row.actor_role, "status": row.status, "version": row.version, "created_at": row.created_at.isoformat() if row.created_at else None} for row in rows], "count": len(rows), "tenant_id": auth.tenant_id}
