from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from common.context_enrichment_contract import HitlAssignment, HitlRoutingConfiguration
from common.tenant_identity import require_tenant_id

_PLACEHOLDERS = {"", "admin", "operator", "unknown", "incident-owner", "incident_owner", "unassigned"}


async def resolve_hitl_assignee(
    tenant_id: str,
    incident: Any,
    approval_type: str,
    severity: str,
    *,
    routing: HitlRoutingConfiguration,
    incident_assignee: str | None = None,
    environment_support_group: str | None = None,
    application_support_group: str | None = None,
    on_call_identity: str | None = None,
) -> HitlAssignment:
    tenant = require_tenant_id(tenant_id, source="HITL assignment")
    candidates = (
        (incident_assignee, "incident_assignment", "user"),
        (routing.service_owner, "service_owner", "user"),
        (environment_support_group, "environment_support", "group"),
        (application_support_group or routing.l2_group or routing.l3_group, "application_support", "group"),
        (on_call_identity, "on_call", "user"),
        (routing.fallback_assignment_group, "tenant_fallback", "group"),
    )
    selected = next(
        ((str(value).strip(), source, kind) for value, source, kind in candidates
         if str(value or "").strip().lower() not in _PLACEHOLDERS),
        None,
    )
    if selected is None:
        raise ValueError("No governed HITL assignee is configured")
    assignee, source, assignment_type = selected
    severity_key = str(severity or "").strip().lower()
    sla_minutes = max(1, int(routing.severity_sla_minutes.get(severity_key, 60)))
    incident_id = getattr(incident, "id", None) or (
        incident.get("id") if isinstance(incident, dict) else None
    )
    if incident_id is None:
        raise ValueError("incident id is required for HITL assignment")
    return HitlAssignment(
        tenant_id=tenant, incident_id=incident_id, assignee=assignee,
        assignment_type=assignment_type, source=source, approval_type=approval_type,
        due_at=datetime.now(UTC) + timedelta(minutes=sla_minutes),
    )
