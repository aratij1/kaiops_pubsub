from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from common.models import Alert, Incident
from common.orchestration import AgentOrchestrator, PolicyEngine
from common.orchestration.execution_plan import resolve_execution_plan
from common.orchestration.workflow_engine import WorkflowSelection


@dataclass
class WorkflowDecision:
    workflow: str
    next_action: str
    downstream_agents: list[str]
    requires_approval: bool
    risk_tier: str
    execution_mode: str
    policy_version: str
    policy_reason: str
    message_bus_provider: str
    stream_count: int
    stream_threshold: int
    planner_used: bool
    planner_model: str | None
    planner_reason: str
    execution_plan: dict[str, Any]


class OrchestratorAgent:
    def __init__(self) -> None:
        self.policy_engine = PolicyEngine()
        self.orchestrator = AgentOrchestrator(policy_engine=self.policy_engine)

    def select(self, alert: Alert, incident: Incident) -> WorkflowDecision:
        selection = self.orchestrator.select(alert, incident)
        return self._to_decision(alert=alert, selection=selection)

    async def select_async(self, alert: Alert, incident: Incident) -> WorkflowDecision:
        selection = await self.orchestrator.select_async(alert, incident)
        return self._to_decision(alert=alert, selection=selection)

    def _to_decision(self, *, alert: Alert, selection: WorkflowSelection) -> WorkflowDecision:
        downstream_agents = [step for step in selection.definition.steps if step.endswith("-agent")]
        policy_version = str(self.policy_engine.policies.get("policy_version", "policy-v1"))
        base_policy_reason = str(getattr(selection, "policy_reason", "confidence and severity policy evaluation"))
        policy_reason = (
            f"{base_policy_reason}; planner={selection.planner_reason}"
            if getattr(selection, "planner_reason", "")
            else base_policy_reason
        )
        execution_plan = resolve_execution_plan(
            alert=alert,
            workflow_name=selection.definition.name,
            requires_approval=selection.requires_approval,
            risk_tier=str(getattr(selection, "risk_tier", "medium")),
            execution_mode=str(getattr(selection, "execution_mode", "human-approval")),
        )
        return WorkflowDecision(
            workflow=selection.definition.name,
            next_action=selection.definition.next_action,
            downstream_agents=downstream_agents,
            requires_approval=selection.requires_approval,
            risk_tier=str(getattr(selection, "risk_tier", "medium")),
            execution_mode=str(getattr(selection, "execution_mode", "human-approval")),
            policy_version=policy_version,
            policy_reason=policy_reason,
            message_bus_provider=selection.message_bus_provider,
            stream_count=selection.stream_count,
            stream_threshold=selection.stream_threshold,
            planner_used=bool(getattr(selection, "planner_used", False)),
            planner_model=getattr(selection, "planner_model", None),
            planner_reason=str(getattr(selection, "planner_reason", "deterministic severity routing")),
            execution_plan=execution_plan,
        )

    def decide_workflow(self, alert: Alert, incident: Incident) -> WorkflowDecision:
        return self.select(alert, incident)

    async def decide_workflow_async(self, alert: Alert, incident: Incident) -> WorkflowDecision:
        return await self.select_async(alert, incident)
