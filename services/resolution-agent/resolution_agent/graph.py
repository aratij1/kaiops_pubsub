from __future__ import annotations

import asyncio
from typing import Any, TypedDict

from common.agent_runtime import AgentRuntime, ContextFailure, ValidationError
from common.agentic import AgentContext, BaseAgent
from common.memory_store import InMemoryStore, MemoryStore
from common.model_gateway import GenerationRequest, ModelGateway, RouterModelGateway
from common.models import AlertSeverity, Context, Evidence, Recommendation
from common.prompts import (
    PROMPT_ASSESS_IMPACT,
    PROMPT_IDENTIFY_ROOT_CAUSE,
    PROMPT_RECOMMEND_REMEDIATION,
)
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
    model_usage: list[dict[str, Any]]
    model_calls: list[dict[str, Any]]


class ResolutionIntelligenceAgent(BaseAgent):
    name = "resolution-agent"

    def __init__(
        self,
        model_router: ModelRouter | None = None,
        model_gateway: ModelGateway | None = None,
        runtime: AgentRuntime | None = None,
        memory_store: MemoryStore | None = None,
    ) -> None:
        self.model_router = model_router or ModelRouter()
        self.model_gateway = model_gateway or RouterModelGateway(self.model_router)
        self.runtime = runtime or AgentRuntime(max_attempts=2)
        self.memory_store = memory_store or InMemoryStore()
        # Bound each model call so a single blocked provider cannot stall event consumption.
        self.model_step_timeout_seconds = 20.0
        self.graph = self._build_graph()

    async def _generate_with_fallback(
        self,
        *,
        context: Context,
        task: ModelTask,
        prompt: str,
        payload: dict[str, Any],
        fallback_content: str,
    ) -> dict[str, Any]:
        try:
            response = await asyncio.wait_for(
                self.model_gateway.generate(
                    GenerationRequest(
                        severity=context.alert.severity,
                        task=task.value,
                        prompt=prompt,
                        payload=payload,
                    )
                ),
                timeout=self.model_step_timeout_seconds,
            )
            if not isinstance(response, dict):
                raise ValueError("model gateway returned a non-dict response")
            usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
            usage.setdefault("provider", str(response.get("model") or "unknown"))
            usage.setdefault("model", str(usage.get("provider") or "unknown"))
            usage.setdefault("task", task.value)
            usage.setdefault("input_tokens", 0)
            usage.setdefault("output_tokens", 0)
            usage.setdefault("total_tokens", 0)
            usage.setdefault("total_cost_usd", 0.0)
            usage.setdefault("estimated", True)
            return {
                "model": str(response.get("model") or "unknown"),
                "content": str(response.get("content") or fallback_content),
                "usage": usage,
            }
        except Exception as exc:
            return {
                "model": "fallback",
                "content": fallback_content,
                "usage": {
                    "provider": "fallback",
                    "model": "fallback",
                    "task": task.value,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "total_cost_usd": 0.0,
                    "estimated": True,
                    "error": str(exc),
                },
            }

    async def can_execute(self, context: AgentContext) -> bool:
        return "context-agent" in context.previous_agent_results or "context" in context.previous_agent_results

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

        runbook_preview = (context.runbook or "")[:800]
        related_incident_preview = [
            {
                "title": str(item.get("title", ""))[:120],
                "service": item.get("service"),
                "severity": item.get("severity"),
            }
            for item in context.related_incidents[:3]
        ]
        recent_change_preview = [
            {
                "id": item.get("id"),
                "message": str(item.get("message") or item.get("title") or "")[:160],
            }
            for item in context.recent_changes[:5]
        ]

        state["gathered_context"] = {
            "deployment": context.deployment,
            "related_incidents": related_incident_preview,
            "runbook": runbook_preview,
            "dependency_services": context.dependency_services[:8],
            "recent_changes": recent_change_preview,
        }
        return state

    async def generate_rca(self, state: ResolutionState) -> ResolutionState:
        context = state["context"]
        prompt = PROMPT_IDENTIFY_ROOT_CAUSE
        payload = {"summary": context.alert.description, **state["gathered_context"]}
        response = await self._generate_with_fallback(
            context=context,
            task=ModelTask.RCA,
            prompt=prompt,
            payload=payload,
            fallback_content=f"Likely service degradation in {context.alert.service}",
        )
        deployment = context.deployment or ""
        direct_evidence = bool(
            deployment
            or context.runbook
            or context.related_incidents
            or context.recent_changes
            or context.observability
        )
        state["direct_evidence"] = direct_evidence
        state["root_cause"] = (
            deployment
            if deployment
            else response["content"]
            if direct_evidence
            else "Root cause not established: no direct service telemetry, change record, or service-matched evidence is linked."
        )
        state["rationale"] = (
            "Analysis withheld because no direct, service-matched evidence is linked to this incident."
            if not direct_evidence
            else f"Fallback hypothesis pending direct evidence: {state['root_cause']}"
            if response["model"] == "fallback"
            else f"Model {response['model']} linked symptoms to {state['root_cause']}"
        )
        state.setdefault("model_usage", []).append(response["usage"])
        state.setdefault("model_calls", []).append(
            {
                "task": ModelTask.RCA.value,
                "provider": response["model"],
                "model": response["usage"].get("model"),
                "prompt": prompt,
                "payload": payload,
                "response": {
                    "text": response["content"],
                    "parameters": {
                        "provider": response["model"],
                        "model": response["usage"].get("model"),
                        "task": ModelTask.RCA.value,
                    },
                },
                "usage": response["usage"],
            }
        )
        return state

    async def impact_analysis(self, state: ResolutionState) -> ResolutionState:
        context = state["context"]
        prompt = PROMPT_ASSESS_IMPACT
        payload = {"service": context.alert.service, "metrics": context.observability}
        response = await self._generate_with_fallback(
            context=context,
            task=ModelTask.IMPACT,
            prompt=prompt,
            payload=payload,
            fallback_content=f"{context.alert.service.title()} service impact requires immediate triage",
        )
        if not context.observability:
            state["impact"] = (
                f"Observed alert: {context.alert.description.strip()} "
                "The affected request volume and customer scope are not yet measured."
            )
        elif "latency" in context.alert.description.lower():
            state["impact"] = f"{context.alert.service.title()} latency"
        else:
            state["impact"] = response["content"]
        state.setdefault("model_usage", []).append(response["usage"])
        state.setdefault("model_calls", []).append(
            {
                "task": ModelTask.IMPACT.value,
                "provider": response["model"],
                "model": response["usage"].get("model"),
                "prompt": prompt,
                "payload": payload,
                "response": {
                    "text": response["content"],
                    "parameters": {
                        "provider": response["model"],
                        "model": response["usage"].get("model"),
                        "task": ModelTask.IMPACT.value,
                    },
                },
                "usage": response["usage"],
            }
        )
        return state

    async def generate_fix(self, state: ResolutionState) -> ResolutionState:
        context = state["context"]
        root_cause = state["root_cause"].lower()
        if not state.get("direct_evidence", False):
            action = (
                "Do not execute a remediation yet. Collect the gateway status-code breakdown, "
                "correlated logs/traces, dependency health, and recent changes for kaiops-platform."
            )
            commands = []
        elif "deployment" in root_cause:
            action = "Rollback deployment"
            commands = [f"rollback:{context.kubernetes.get('deployment', context.alert.service)}"]
        elif "pod" in context.alert.description.lower():
            action = "Restart pod"
            commands = [f"restart-pod:{context.alert.service}"]
        else:
            prompt = PROMPT_RECOMMEND_REMEDIATION
            payload = {"service": context.alert.service, "runbook": context.runbook}
            response = await self._generate_with_fallback(
                context=context,
                task=ModelTask.FIX,
                prompt=prompt,
                payload=payload,
                fallback_content=f"Investigate {context.alert.service} health and apply documented runbook remediation",
            )
            action = response["content"]
            commands = []
            state.setdefault("model_usage", []).append(response["usage"])
            state.setdefault("model_calls", []).append(
                {
                    "task": ModelTask.FIX.value,
                    "provider": response["model"],
                    "model": response["usage"].get("model"),
                    "prompt": prompt,
                    "payload": payload,
                    "response": {
                        "text": response["content"],
                        "parameters": {
                            "provider": response["model"],
                            "model": response["usage"].get("model"),
                            "task": ModelTask.FIX.value,
                        },
                    },
                    "usage": response["usage"],
                }
            )
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
        if not state.get("direct_evidence", False):
            score = min(score, 0.35)
        model_usage = state.get("model_usage", [])
        if any(
            str(item.get("provider") or item.get("model") or "").lower() in {"fallback", "heuristic-fallback", "provider-error"}
            or bool(item.get("error"))
            for item in model_usage
            if isinstance(item, dict)
        ):
            score = min(score, 0.35)
        state["confidence"] = min(score, 0.99)
        return state

    async def resolve(self, context: Context) -> Recommendation:
        state = await self.graph.ainvoke({"context": context})
        runbook_present = bool((context.runbook or "").strip())
        evidence: list[Evidence] = []
        if context.observability:
            evidence.append(Evidence(
                id=f"telemetry:{context.incident_id}",
                type="telemetry",
                source="observability",
                confidence=0.9,
                metadata={"service": context.alert.service, "present": True},
                content=context.observability,
            ))
        if context.deployment or context.recent_changes:
            evidence.append(Evidence(
                id=f"changes:{context.incident_id}",
                type="change",
                source="change-intelligence",
                confidence=0.85,
                metadata={"service": context.alert.service, "present": True},
                content={"deployment": context.deployment, "recent_changes": context.recent_changes[:5]},
            ))
        if context.related_incidents:
            evidence.append(Evidence(
                id=f"ctx:{context.incident_id}",
                type="context",
                source="context-agent",
                confidence=0.8,
                metadata={"service": context.alert.service, "present": True},
                content={"related_incidents": len(context.related_incidents)},
            ))
        if runbook_present:
            evidence.append(Evidence(
                id=f"runbook:{context.incident_id}",
                type="runbook",
                source="knowledge-router",
                confidence=0.85,
                metadata={"service": context.alert.service, "present": True},
                content={"preview": (context.runbook or "")[:180]},
            ))
        missing_evidence = []
        if not context.observability:
            missing_evidence.append("service telemetry")
        if not (context.deployment or context.recent_changes):
            missing_evidence.append("recent changes")
        if not (runbook_present or context.related_incidents):
            missing_evidence.append("service-matched knowledge")
        recommendation = Recommendation(
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
        recommendation.metadata["model_usage"] = state.get("model_usage", [])
        recommendation.metadata["model_calls"] = state.get("model_calls", [])
        recommendation.metadata["evidence"] = [item.model_dump(mode="json") for item in evidence]
        recommendation.metadata["evidence_ids"] = [item.id for item in evidence]
        recommendation.metadata["missing_evidence"] = missing_evidence
        recommendation.metadata["evidence_status"] = "grounded" if evidence else "insufficient-evidence"
        recommendation.metadata["reasoning"] = state.get("rationale", "")
        recommendation.metadata["citations"] = [f"incident://{context.incident_id}"]
        if runbook_present:
            recommendation.metadata["citations"].insert(0, f"runbook://{context.alert.service}")
        return recommendation

    async def resolve_with_runtime(self, context: Context) -> Recommendation:
        runtime_context = AgentContext.from_context(context)
        runtime_result = await self.runtime.run(self, runtime_context)
        recommendation = runtime_result.result
        if not isinstance(recommendation, Recommendation):
            raise ValidationError("resolution runtime produced non-recommendation output")
        recommendation.metadata["runtime"] = {
            "status": runtime_result.state.execution_status,
            "retry_count": runtime_result.state.retries,
            "reflection": runtime_result.reflection,
        }
        await self.memory_store.append(
            "incident-memory",
            {
                "incident_id": str(context.incident_id),
                "service": context.alert.service,
                "recommended_action": recommendation.recommended_action,
                "confidence": recommendation.confidence,
                "reflection": runtime_result.reflection,
            },
        )
        return recommendation

    async def initialize(self, context: AgentContext, state: Any) -> None:
        state.execution_status = "analyzing"

    async def plan(self, context: AgentContext, state: Any) -> dict[str, Any]:
        payload = context.previous_agent_results.get("context-agent") or context.previous_agent_results.get("context")
        model_task_count = 3
        if not isinstance(payload, dict):
            raise ContextFailure("resolution agent requires serialized context payload")
        return {
            "phase": "resolution",
            "steps": ["collect_context", "generate_rca", "impact_analysis", "generate_fix", "confidence_scoring"],
            "model_task_count": model_task_count,
        }

    async def execute(self, context: AgentContext) -> Recommendation:
        context_payload = context.previous_agent_results.get("context-agent") or context.previous_agent_results.get("context")
        if not isinstance(context_payload, dict):
            raise ContextFailure("AgentContext.previous_agent_results must include serialized context")
        recommendation = await self.resolve(Context.model_validate(context_payload))
        context.set_result(self.name, recommendation.model_dump(mode="json"))
        return recommendation

    async def validate(self, result: Any) -> bool:
        if not isinstance(result, Recommendation):
            return False
        evidence_ids = result.metadata.get("evidence_ids", [])
        if not isinstance(evidence_ids, list):
            raise ValidationError("recommendation evidence_ids must be a list")
        if not evidence_ids:
            if "root cause not established" not in result.root_cause.lower() or result.confidence > 0.35:
                raise ValidationError("ungrounded recommendations must abstain with low confidence")
            return True
        if result.confidence <= 0:
            raise ValidationError("grounded recommendations must have positive confidence")
        return True

    async def reflect(
        self,
        context: AgentContext,
        state: Any,
        *,
        result: Any | None,
        error: Exception | None,
    ) -> dict[str, Any]:
        confidence = float(result.confidence) if isinstance(result, Recommendation) else 0.0
        evidence_ids = result.metadata.get("evidence_ids", []) if isinstance(result, Recommendation) else []
        missing_evidence = result.metadata.get("missing_evidence", []) if isinstance(result, Recommendation) else ["service telemetry", "recent changes", "service-matched knowledge"]
        quality = "high" if confidence >= 0.85 else "medium" if confidence >= 0.65 else "low"
        return {
            "agent": self.name,
            "quality": quality,
            "lessons_learned": [
                "Preserve runbook and incident evidence links in every recommendation.",
                "Escalate to approval path when confidence is below policy threshold.",
            ],
            "failed_tool_calls": [],
            "missing_evidence": list(missing_evidence) if isinstance(missing_evidence, list) else [str(missing_evidence)],
            "evidence_count": len(evidence_ids) if isinstance(evidence_ids, list) else 0,
            "confidence_adjustment": 0.0,
            "error": str(error) if error else None,
        }
