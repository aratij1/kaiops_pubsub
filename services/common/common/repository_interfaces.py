from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from common.database import AlertRecord
from common.models import Alert, Approval, Incident, Recommendation, RemediationAction, ResolutionReport
from common.repository import IncidentRepository


class AlertHistoryRepository(Protocol):
    async def list_recent_alerts(self) -> Sequence[Alert]: ...
    async def record_alert(self, alert: Alert) -> None: ...


@dataclass
class InMemoryAlertHistoryRepository:
    max_items: int = 1000
    _items: deque[Alert] = field(init=False)

    def __post_init__(self) -> None:
        self._items = deque(maxlen=self.max_items)

    async def list_recent_alerts(self) -> Sequence[Alert]:
        return tuple(self._items)

    async def record_alert(self, alert: Alert) -> None:
        self._items.append(alert)


@dataclass(slots=True)
class SqlAlertHistoryRepository:
    session_factory: async_sessionmaker[AsyncSession]
    max_items: int = 1000

    async def list_recent_alerts(self) -> Sequence[Alert]:
        safe_limit = max(1, min(int(self.max_items), 5000))
        async with self.session_factory() as session:
            result = await session.execute(
                select(AlertRecord)
                .order_by(AlertRecord.created_at.desc(), AlertRecord.updated_at.desc())
                .limit(safe_limit)
            )
            rows = result.scalars().all()

        alerts: list[Alert] = []
        for row in rows:
            payload = row.payload if isinstance(row.payload, dict) else {}
            try:
                alerts.append(Alert.model_validate(payload))
            except Exception:
                # Skip malformed historical payloads instead of breaking active alert intake.
                continue
        return tuple(alerts)

    async def record_alert(self, alert: Alert) -> None:
        async with self.session_factory() as session:
            await session.merge(
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
            await session.commit()


class AlertRepositoryPort(Protocol):
    async def save_alert(self, alert: Alert) -> None: ...


class IncidentRepositoryPort(Protocol):
    async def save_incident(self, incident: Incident) -> None: ...
    async def get_incident(self, incident_id: str) -> dict | None: ...


class KnowledgeRepositoryPort(Protocol):
    async def save_knowledge_base(self, report: ResolutionReport, service: str = "unknown") -> None: ...


class WorkflowRepositoryPort(Protocol):
    async def list_workflow_definitions(self) -> list[dict]: ...


class PolicyRepositoryPort(Protocol):
    async def list_policies(self) -> list[dict]: ...


@dataclass(slots=True)
class SqlIncidentRepositoryAdapter:
    repository: IncidentRepository

    async def save_alert(self, alert: Alert) -> None:
        await self.repository.save_alert(alert)

    async def save_incident(self, incident: Incident) -> None:
        await self.repository.save_incident(incident)

    async def get_incident(self, incident_id: str) -> dict | None:
        return await self.repository.get_incident(incident_id)

    async def save_approval(self, approval: Approval) -> None:
        await self.repository.save_approval(approval)

    async def save_recommendation_as_audit(self, recommendation: Recommendation) -> None:
        await self.repository.save_recommendation_as_audit(recommendation)

    async def save_action(self, action: RemediationAction) -> None:
        await self.repository.save_action(action)

    async def save_report(self, report: ResolutionReport) -> None:
        await self.repository.save_report(report)

    async def save_knowledge_base(self, report: ResolutionReport, service: str = "unknown") -> None:
        await self.repository.save_knowledge_base(report, service=service)


@dataclass(slots=True)
class StaticWorkflowRepository:
    workflows: list[dict] = field(default_factory=list)

    async def list_workflow_definitions(self) -> list[dict]:
        return list(self.workflows)


@dataclass(slots=True)
class StaticPolicyRepository:
    policies: list[dict] = field(default_factory=list)

    async def list_policies(self) -> list[dict]:
        return list(self.policies)
