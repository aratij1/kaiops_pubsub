from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from common.agentic import AgentContext, BaseAgent
from common.models import Alert, Incident
from common.orchestration.policy_engine import PolicyEngine
from common.orchestration.state_machine import WorkflowState, WorkflowStateMachine
from common.orchestration.workflow_engine import WorkflowEngine, WorkflowSelection


@dataclass(slots=True)
class AgentOrchestrator:
    workflow_engine: WorkflowEngine = field(default_factory=WorkflowEngine)
    policy_engine: PolicyEngine = field(default_factory=PolicyEngine)
    state_machine: WorkflowStateMachine = field(default_factory=WorkflowStateMachine)

    @staticmethod
    def _parse_stream_count(raw: object) -> int | None:
        if raw is None:
            return None
        try:
            return int(str(raw).strip())
        except (TypeError, ValueError):
            return None

    def _extract_stream_count(self, alert: Alert) -> int | None:
        for source in (alert.labels, alert.annotations, alert.metadata):
            for key in ("stream_count", "streams", "streams_count", "event_streams"):
                parsed = self._parse_stream_count(source.get(key))
                if parsed is not None:
                    return parsed
        return None

    def select(self, alert: Alert, incident: Incident, *, confidence: float | None = None) -> WorkflowSelection:
        return self.workflow_engine.select(
            severity=alert.severity,
            confidence=confidence,
            stream_count=self._extract_stream_count(alert),
        )

    async def select_async(self, alert: Alert, incident: Incident, *, confidence: float | None = None) -> WorkflowSelection:
        return await self.workflow_engine.select_with_planner(
            severity=alert.severity,
            confidence=confidence,
            stream_count=self._extract_stream_count(alert),
        )

    async def execute(self, agents: list[BaseAgent], context: AgentContext) -> dict[str, Any]:
        current_state = WorkflowState.NEW
        results: dict[str, Any] = {}
        for agent in agents:
            if not await agent.can_execute(context):
                continue
            if self.state_machine.can_transition(current_state, WorkflowState.ANALYZING):
                current_state = WorkflowState.ANALYZING
                context.workflow_state = current_state.value
            result = await agent.execute(context)
            results[agent.name] = result
            context.set_result(agent.name, result)
            await agent.validate(result)
        return results
