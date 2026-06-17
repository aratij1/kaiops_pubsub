from __future__ import annotations

from typing import Any, TypedDict

from common.models import AlertSeverity, Context, Recommendation
from langgraph.graph import END, StateGraph
from model_router import ModelRouter, ModelTask


class ResolutionState(TypedDict, total=False):
    context: Context
    gathered_context: dict[str, Any]
    root_cause: str
    impact: str
    recommended_action: str
    confidence: float
    rationale: str


class ResolutionIntelligenceAgent:
    def __init__(self, model_router: ModelRouter | None = None) -> None:
        self.model_router = model_router or ModelRouter()
        self.graph = self._build_graph()

    def _build_graph(self):
        workflow = StateGraph(ResolutionState)
        workflow.add_node("collect_context", self.collect_context)
        workflow.add_node("generate_rca", self.generate_rca)
        workflow.add_node("impact_analysis", self.impact_analysis)
        workflow.add_node("generate_fix", self.generate_fix)
        workflow.add_node("confidence_scoring", self.confidence_scoring)
        workflow.set_entry_point("collect_context")
        workflow.add_edge("collect_context", "generate_rca")
        workflow.add_edge("generate_rca", "impact_analysis")
        workflow.add_edge("impact_analysis", "generate_fix")
        workflow.add_edge("generate_fix", "confidence_scoring")
        workflow.add_edge("confidence_scoring", END)
        return workflow.compile()

    async def collect_context(self, state: ResolutionState) -> ResolutionState:
        context = state["context"]
        state["gathered_context"] = {
            "deployment": context.deployment,
            "related_incidents": context.related_incidents,
            "runbook": context.runbook,
            "dependency_services": context.dependency_services,
            "recent_changes": context.recent_changes,
        }
        return state

    async def generate_rca(self, state: ResolutionState) -> ResolutionState:
        context = state["context"]
        response = await self.model_router.route(
            severity=context.alert.severity,
            task=ModelTask.RCA,
            prompt="Identify root cause",
            payload={"summary": context.alert.description, **state["gathered_context"]},
        )
        deployment = context.deployment or "unknown change"
        state["root_cause"] = deployment if "Deployment" in deployment else response["content"]
        state["rationale"] = f"Model {response['model']} linked symptoms to {state['root_cause']}"
        return state

    async def impact_analysis(self, state: ResolutionState) -> ResolutionState:
        context = state["context"]
        response = await self.model_router.route(
            severity=context.alert.severity,
            task=ModelTask.IMPACT,
            prompt="Assess customer and dependency impact",
            payload={"service": context.alert.service, "metrics": context.observability},
        )
        if "latency" in context.alert.description.lower():
            state["impact"] = f"{context.alert.service.title()} latency"
        else:
            state["impact"] = response["content"]
        return state

    async def generate_fix(self, state: ResolutionState) -> ResolutionState:
        context = state["context"]
        root_cause = state["root_cause"].lower()
        if "deployment" in root_cause:
            action = "Rollback deployment"
            commands = [f"rollback:{context.kubernetes.get('deployment', context.alert.service)}"]
        elif "pod" in context.alert.description.lower():
            action = "Restart pod"
            commands = [f"restart-pod:{context.alert.service}"]
        else:
            response = await self.model_router.route(
                severity=context.alert.severity,
                task=ModelTask.FIX,
                prompt="Recommend safest remediation",
                payload={"service": context.alert.service, "runbook": context.runbook},
            )
            action = response["content"]
            commands = []
        state["recommended_action"] = action
        state["commands"] = commands
        return state

    async def confidence_scoring(self, state: ResolutionState) -> ResolutionState:
        context = state["context"]
        score = 0.55
        if context.deployment:
            score += 0.2
        if context.related_incidents:
            score += 0.1
        if context.runbook:
            score += 0.06
        if context.alert.severity in {AlertSeverity.HIGH, AlertSeverity.CRITICAL}:
            score += 0.05
        state["confidence"] = min(score, 0.99)
        return state

    async def resolve(self, context: Context) -> Recommendation:
        state = await self.graph.ainvoke({"context": context})
        return Recommendation(
            incident_id=context.incident_id,
            root_cause=state["root_cause"],
            confidence=state["confidence"],
            impact=state["impact"],
            recommended_action=state["recommended_action"],
            severity=context.alert.severity,
            rationale=state["rationale"],
            commands=state.get("commands", []),
            risk="high" if context.alert.severity == AlertSeverity.CRITICAL else "medium",
        )
