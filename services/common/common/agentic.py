from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from common.models import Alert, Context, Incident


@dataclass(slots=True)
class AgentContext:
    alert: Alert | None = None
    incident: Incident | None = None
    topology: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    logs: dict[str, Any] = field(default_factory=dict)
    traces: dict[str, Any] = field(default_factory=dict)
    cmdb: dict[str, Any] = field(default_factory=dict)
    knowledge: dict[str, Any] = field(default_factory=dict)
    previous_agent_results: dict[str, Any] = field(default_factory=dict)
    policies: dict[str, Any] = field(default_factory=dict)
    workflow_state: str = "new"
    flow_id: str | None = None
    trace_id: str | None = None
    correlation_id: str | None = None

    @classmethod
    def from_context(cls, context: Context, *, incident: Incident | None = None) -> "AgentContext":
        return cls(
            alert=context.alert,
            incident=incident,
            topology={"dependency_services": list(context.dependency_services)},
            metrics=dict(context.observability),
            cmdb=dict(context.cmdb),
            knowledge={
                "runbook": context.runbook,
                "related_incidents": list(context.related_incidents),
                "recent_changes": list(context.recent_changes),
                "rag_matches": list(context.metadata.get("rag_matches", [])),
            },
            previous_agent_results={"context": context.model_dump(mode="json")},
            workflow_state="analyzing",
        )

    def set_result(self, agent_name: str, result: Any) -> None:
        self.previous_agent_results[agent_name] = result


class BaseAgent(ABC):
    name = "base-agent"

    async def can_execute(self, context: AgentContext) -> bool:
        return context.alert is not None

    async def initialize(self, context: AgentContext, state: "AgentState") -> None:
        return None

    async def plan(self, context: AgentContext, state: "AgentState") -> dict[str, Any]:
        return {"strategy": "default", "agent": self.name}

    @abstractmethod
    async def execute(self, context: AgentContext) -> Any:
        raise NotImplementedError

    async def validate(self, result: Any) -> bool:
        return result is not None

    async def reflect(
        self,
        context: AgentContext,
        state: "AgentState",
        *,
        result: Any | None,
        error: Exception | None,
    ) -> dict[str, Any]:
        observations = [
            {
                "status": state.execution_status,
                "retry_count": state.retries,
                "error": str(error) if error else None,
            }
        ]
        return {
            "agent": self.name,
            "execution_quality": "pass" if error is None else "needs-review",
            "observations": observations,
            "evidence_ids": list(state.evidence_ids),
        }

    async def publish(self, context: AgentContext, state: "AgentState", result: Any) -> None:
        return None

    async def shutdown(self, context: AgentContext, state: "AgentState") -> None:
        return None


@dataclass(slots=True)
class Evidence:
    id: str
    type: str
    source: str
    confidence: float
    timestamp: str
    metadata: dict[str, Any] = field(default_factory=dict)
    content: dict[str, Any] | str | None = None


@dataclass(slots=True)
class AgentState:
    incident_id: str | None = None
    alert_id: str | None = None
    execution_status: str = "pending"
    evidence_ids: list[str] = field(default_factory=list)
    confidence: float | None = None
    retries: int = 0
    observations: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    flow_id: str | None = None
    trace_id: str | None = None
    correlation_id: str | None = None

    @classmethod
    def from_context(cls, context: AgentContext) -> "AgentState":
        incident_id = str(context.incident.id) if context.incident is not None else None
        alert_id = str(context.alert.id) if context.alert is not None else None
        return cls(
            incident_id=incident_id,
            alert_id=alert_id,
            execution_status=context.workflow_state or "new",
            flow_id=context.flow_id,
            trace_id=context.trace_id
            or (str(context.incident.trace_id) if context.incident and context.incident.trace_id else None)
            or (str(context.alert.trace_id) if context.alert and context.alert.trace_id else None),
            correlation_id=context.correlation_id
            or (str(context.alert.correlation_id) if context.alert and context.alert.correlation_id else None),
        )

    def apply(self, context: AgentContext) -> None:
        context.workflow_state = self.execution_status
        context.flow_id = self.flow_id
        context.trace_id = self.trace_id
        context.correlation_id = self.correlation_id
