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

    @abstractmethod
    async def execute(self, context: AgentContext) -> Any:
        raise NotImplementedError

    async def validate(self, result: Any) -> bool:
        return result is not None
