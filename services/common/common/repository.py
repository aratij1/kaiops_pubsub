from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.database import (
    ActionRecord,
    AgentWorkItemRecord,
    AlertRecord,
    ApprovalRecord,
    AuditLogRecord,
    IncidentRecord,
    KnowledgeBaseRecord,
    RcaReportRecord,
    OnboardingStateRecord,
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

    @staticmethod
    def _require(name: str, value: Any) -> Any:
        if value is None:
            raise ValueError(f"{name} is required")
        if isinstance(value, str) and not value.strip():
            raise ValueError(f"{name} is required")
        return value

    async def save_alert(self, alert: Alert) -> None:
        await self.session.merge(
            AlertRecord(
                id=self._require("alert.id", alert.id),
                source=self._require("alert.source", alert.source),
                name=self._require("alert.name", alert.name),
                service=self._require("alert.service", alert.service),
                environment=self._require("alert.environment", alert.environment),
                severity=self._require("alert.severity", alert.severity.value),
                fingerprint=alert.fingerprint,
                correlation_id=alert.correlation_id,
                payload=alert.model_dump(mode="json"),
            )
        )

    async def save_incident(self, incident: Incident) -> None:
        await self.session.merge(
            IncidentRecord(
                id=self._require("incident.id", incident.id),
                service=self._require("incident.service", incident.service),
                environment=self._require("incident.environment", incident.environment),
                severity=self._require("incident.severity", incident.severity.value),
                status=self._require("incident.status", incident.status.value),
                title=self._require("incident.title", incident.title),
                ticket_id=incident.ticket_id,
                payload=incident.model_dump(mode="json"),
            )
        )

    async def get_incident(self, incident_id: str) -> dict[str, Any] | None:
        result = await self.session.execute(select(IncidentRecord).where(IncidentRecord.id == incident_id))
        record = result.scalar_one_or_none()
        return record.payload if record else None

    async def save_approval(self, approval: Approval) -> None:
        await self.session.merge(
            ApprovalRecord(
                id=self._require("approval.id", approval.id),
                incident_id=self._require("approval.incident_id", approval.incident_id),
                recommendation_id=self._require("approval.recommendation_id", approval.recommendation_id),
                decision=self._require("approval.decision", approval.decision.value),
                approver=approval.approver,
                payload=approval.model_dump(mode="json"),
            )
        )

    async def save_action(self, action: RemediationAction) -> None:
        await self.session.merge(
            ActionRecord(
                id=self._require("action.id", action.id),
                incident_id=self._require("action.incident_id", action.incident_id),
                action_type=self._require("action.action_type", action.action_type),
                target=self._require("action.target", action.target),
                status=self._require("action.status", action.status.value),
                payload=action.model_dump(mode="json"),
            )
        )

    async def save_report(self, report: ResolutionReport) -> None:
        await self.session.merge(
            RcaReportRecord(
                id=self._require("report.id", report.id),
                incident_id=self._require("report.incident_id", report.incident_id),
                root_cause=self._require("report.root_cause", report.root_cause),
                impact=self._require("report.impact", report.impact),
                payload=report.model_dump(mode="json"),
            )
        )

    async def save_recommendation_as_audit(self, recommendation: Recommendation) -> None:
        await self.session.merge(
            AuditLogRecord(
                id=self._require("recommendation.id", recommendation.id),
                actor=self._require("audit.actor", "resolution-agent"),
                action=self._require("audit.action", "recommendation.generated"),
                resource_type="incident",
                resource_id=self._require("audit.resource_id", str(recommendation.incident_id)),
                payload=recommendation.model_dump(mode="json"),
            )
        )

    async def save_knowledge_base(self, report: ResolutionReport, service: str = "unknown") -> None:
        await self.session.merge(
            KnowledgeBaseRecord(
                id=self._require("knowledge_base.id", report.id),
                service=self._require("knowledge_base.service", service),
                title=self._require("knowledge_base.title", f"RCA for incident {report.incident_id}"),
                content=self._require("knowledge_base.content", report.knowledge_base_entry),
                embedding_ref=self._require("knowledge_base.embedding_ref", str(report.id)),
                payload=report.model_dump(mode="json"),
            )
        )

    async def save_onboarding_state(
        self,
        *,
        project_name: str,
        provider_name: str,
        project_payload: dict[str, Any],
        connectivity_payload: dict[str, Any],
        owner_team: str | None = None,
        environment: str | None = None,
        region: str | None = None,
        endpoint_url: str | None = None,
        test_status: str | None = None,
        test_message: str | None = None,
        last_tested_at: datetime | None = None,
    ) -> None:
        await self.session.merge(
            OnboardingStateRecord(
                project_name=self._require("onboarding.project_name", project_name),
                provider_name=self._require("onboarding.provider_name", provider_name),
                owner_team=owner_team,
                environment=environment,
                region=region,
                endpoint_url=endpoint_url,
                test_status=test_status,
                test_message=test_message,
                project_payload=self._require("onboarding.project_payload", project_payload),
                connectivity_payload=self._require("onboarding.connectivity_payload", connectivity_payload),
                last_tested_at=last_tested_at,
            )
        )

    async def list_onboarding_state(self) -> list[dict[str, Any]]:
        result = await self.session.execute(
            select(OnboardingStateRecord).order_by(OnboardingStateRecord.project_name, OnboardingStateRecord.provider_name)
        )
        rows = result.scalars().all()
        return [
            {
                "project_name": row.project_name,
                "provider_name": row.provider_name,
                "owner_team": row.owner_team,
                "environment": row.environment,
                "region": row.region,
                "endpoint_url": row.endpoint_url,
                "test_status": row.test_status,
                "test_message": row.test_message,
                "updated_at": row.updated_at,
                "last_tested_at": row.last_tested_at,
            }
            for row in rows
        ]

    async def save_agent_work_item(
        self,
        *,
        incident_id: Any,
        agent_name: str,
        work_item: str,
        status: str,
        sequence: int | None = None,
        trace_id: str | None = None,
        ticket_id: str | None = None,
        details: dict[str, Any] | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
    ) -> None:
        await self.session.merge(
            AgentWorkItemRecord(
                incident_id=self._require("agent_work.incident_id", incident_id),
                agent_name=self._require("agent_work.agent_name", agent_name),
                trace_id=trace_id,
                ticket_id=ticket_id,
                work_item=self._require("agent_work.work_item", work_item),
                status=self._require("agent_work.status", status),
                sequence=sequence,
                details=details or {},
                started_at=started_at,
                completed_at=completed_at,
            )
        )

    async def list_agent_work_items(self, limit: int = 100) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 500))
        result = await self.session.execute(
            select(AgentWorkItemRecord)
            .order_by(AgentWorkItemRecord.updated_at.desc(), AgentWorkItemRecord.sequence.asc())
            .limit(safe_limit)
        )
        rows = result.scalars().all()
        return [
            {
                "incident_id": str(row.incident_id),
                "agent_name": row.agent_name,
                "trace_id": row.trace_id,
                "ticket_id": row.ticket_id,
                "work_item": row.work_item,
                "status": row.status,
                "sequence": row.sequence,
                "details": row.details,
                "started_at": row.started_at,
                "completed_at": row.completed_at,
                "updated_at": row.updated_at,
            }
            for row in rows
        ]
