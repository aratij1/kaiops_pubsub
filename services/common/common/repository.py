from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.database import (
    ActionRecord,
    AlertRecord,
    ApprovalRecord,
    AuditLogRecord,
    IncidentRecord,
    KnowledgeBaseRecord,
    RcaReportRecord,
)
from common.models import (
    Alert,
    Approval,
    Incident,
    Recommendation,
    RemediationAction,
    ResolutionReport,
)


class IncidentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save_alert(self, alert: Alert) -> None:
        await self.session.merge(
            AlertRecord(
                id=alert.id,
                source=alert.source,
                name=alert.name,
                service=alert.service,
                environment=alert.environment,
                severity=alert.severity.value,
                fingerprint=alert.fingerprint,
                correlation_id=alert.correlation_id,
                payload=alert.model_dump(mode="json"),
            )
        )

    async def save_incident(self, incident: Incident) -> None:
        await self.session.merge(
            IncidentRecord(
                id=incident.id,
                service=incident.service,
                environment=incident.environment,
                severity=incident.severity.value,
                status=incident.status.value,
                title=incident.title,
                ticket_id=incident.ticket_id,
                payload=incident.model_dump(mode="json"),
            )
        )

    async def get_incident(self, incident_id: str) -> dict[str, Any] | None:
        result = await self.session.execute(
            select(IncidentRecord).where(IncidentRecord.id == incident_id)
        )
        record = result.scalar_one_or_none()
        return record.payload if record else None

    async def save_approval(self, approval: Approval) -> None:
        await self.session.merge(
            ApprovalRecord(
                id=approval.id,
                incident_id=approval.incident_id,
                recommendation_id=approval.recommendation_id,
                decision=approval.decision.value,
                approver=approval.approver,
                payload=approval.model_dump(mode="json"),
            )
        )

    async def save_action(self, action: RemediationAction) -> None:
        await self.session.merge(
            ActionRecord(
                id=action.id,
                incident_id=action.incident_id,
                action_type=action.action_type,
                target=action.target,
                status=action.status.value,
                payload=action.model_dump(mode="json"),
            )
        )

    async def save_report(self, report: ResolutionReport) -> None:
        await self.session.merge(
            RcaReportRecord(
                id=report.id,
                incident_id=report.incident_id,
                root_cause=report.root_cause,
                impact=report.impact,
                payload=report.model_dump(mode="json"),
            )
        )

    async def save_recommendation_as_audit(self, recommendation: Recommendation) -> None:
        await self.session.merge(
            AuditLogRecord(
                id=recommendation.id,
                actor="resolution-agent",
                action="recommendation.generated",
                resource_type="incident",
                resource_id=str(recommendation.incident_id),
                payload=recommendation.model_dump(mode="json"),
            )
        )

    async def save_knowledge_base(self, report: ResolutionReport, service: str = "unknown") -> None:
        await self.session.merge(
            KnowledgeBaseRecord(
                id=report.id,
                service=service,
                title=f"RCA for incident {report.incident_id}",
                content=report.knowledge_base_entry,
                embedding_ref=str(report.id),
                payload=report.model_dump(mode="json"),
            )
        )
