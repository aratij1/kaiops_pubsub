from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ai_workbench_common.agent_runtime import AgentRuntime, ContextFailure, ValidationError
from ai_workbench_common.agentic import AgentContext, BaseAgent
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


class OrchestratorAgent(BaseAgent):
    name = "orchestrator"

    def __init__(self) -> None:
        self.policy_engine = PolicyEngine()
        self.orchestrator = AgentOrchestrator(policy_engine=self.policy_engine)
        self.runtime = AgentRuntime(max_attempts=2)

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

    async def decide_workflow_async_with_runtime(self, alert: Alert, incident: Incident) -> WorkflowDecision:
        context = AgentContext(alert=alert, incident=incident)
        runtime_result = await self.runtime.run(self, context)
        decision = runtime_result.result
        if not isinstance(decision, WorkflowDecision):
            raise ValidationError("orchestrator runtime produced invalid decision output")
        return decision

    async def initialize(self, context: AgentContext, state: Any) -> None:
        state.execution_status = "selecting"

    async def plan(self, context: AgentContext, state: Any) -> dict[str, Any]:
        if context.alert is None or context.incident is None:
            raise ContextFailure("Orchestrator requires alert and incident in context")
        return {
            "workflow": "selection",
            "routing_inputs": {
                "severity": str(context.alert.severity),
                "stream_count": context.alert.labels.get("stream_count") if context.alert else None,
            },
        }

    async def execute(self, context: AgentContext) -> WorkflowDecision:
        if context.alert is None or context.incident is None:
            raise ContextFailure("Orchestrator requires alert and incident in context")
        decision = await self.select_async(context.alert, context.incident)
        context.set_result(self.name, decision.__dict__)
        return decision

    async def validate(self, result: Any) -> bool:
        if not isinstance(result, WorkflowDecision):
            return False
        if not result.workflow:
            raise ValidationError("workflow name is required")
        if not isinstance(result.downstream_agents, list):
            raise ValidationError("downstream_agents must be a list")
        return True

    async def reflect(
        self,
        context: AgentContext,
        state: Any,
        *,
        result: Any | None,
        error: Exception | None,
    ) -> dict[str, Any]:
        if isinstance(result, WorkflowDecision):
            return {
                "agent": self.name,
                "planner_used": result.planner_used,
                "message_bus_provider": result.message_bus_provider,
                "risk_tier": result.risk_tier,
                "execution_mode": result.execution_mode,
                "error": str(error) if error else None,
            }
        return {"agent": self.name, "error": str(error) if error else "unknown"}
