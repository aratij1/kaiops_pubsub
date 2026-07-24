from __future__ import annotations

import asyncio
import json
import logging
import re
from enum import StrEnum
from typing import Any, TypedDict

import httpx

from ai_workbench_common.agent_runtime import AgentRuntime, ContextFailure, ValidationError
from ai_workbench_common.agentic import AgentContext, BaseAgent
from ai_workbench_common.memory_store import InMemoryStore, MemoryStore
from ai_workbench_common.model_evaluation import AzureAIEvaluationClient, EvaluationResult, build_quality_evaluation
from ai_workbench_common.model_gateway import GenerationRequest, HttpModelGateway, ModelGateway, RouterModelGateway
from ai_workbench_common.models import Context, Evidence
from common.config import get_settings
from common.models import AlertSeverity, Recommendation
from ai_workbench_common.prompts import (
    PROMPT_ASSESS_IMPACT,
    PROMPT_IDENTIFY_ROOT_CAUSE,
    PROMPT_RECOMMEND_REMEDIATION,
)
from langgraph.graph import END, StateGraph

logger = logging.getLogger("kaiops.resolution_agent")


class ModelTask(StrEnum):
    """Mirrors model_router.ModelTask's wire values without importing that service's package."""

    RCA = "rca"
    IMPACT = "impact"
    FIX = "fix"
    SUMMARIZATION = "summarization"
    GENERAL = "general"


class ResolutionState(TypedDict, total=False):
    context: Context
    gathered_context: dict[str, Any]
    root_cause: str
    impact: str
    recommended_action: str
    confidence: float
    rationale: str
    commands: list[str]
    model_usage: list[dict[str, Any]]
    model_calls: list[dict[str, Any]]


class ResolutionIntelligenceAgent(BaseAgent):
    name = "resolution-agent"

    def __init__(
        self,
        model_router: Any | None = None,
        model_gateway: ModelGateway | None = None,
        runtime: AgentRuntime | None = None,
        memory_store: MemoryStore | None = None,
        evaluation_client: AzureAIEvaluationClient | None = None,
    ) -> None:
        settings = get_settings()
        self.model_router = model_router
        if model_gateway is not None:
            self.model_gateway = model_gateway
        elif model_router is not None:
            # Allows tests/tools to inject an in-process ModelRouter-like object directly.
            self.model_gateway = RouterModelGateway(model_router)
        else:
            self.model_gateway = HttpModelGateway(
                settings.model_router_url,
                timeout_seconds=settings.llm_request_timeout_seconds,
            )
        self.runtime = runtime or AgentRuntime(max_attempts=2)
        self.memory_store = memory_store or InMemoryStore()
        self.evaluation_client = evaluation_client or AzureAIEvaluationClient(settings)
        self.evaluation_service_url = settings.evaluation_service_url
        # Bound each model call so a single blocked provider cannot stall event consumption.
        self.model_step_timeout_seconds = 20.0
        # Keeps strong references to fire-and-forget evaluation-publish tasks so they
        # aren't garbage-collected mid-flight; discarded automatically once done.
        self._background_tasks: set[asyncio.Task[None]] = set()
        self.graph = self._build_graph()

    @staticmethod
    def _norm(value: Any) -> str:
        return str(value or "").strip().lower()

    @staticmethod
    def _extract_runbook_commands(runbook: str, *, max_items: int = 4) -> list[str]:
        if not str(runbook or "").strip():
            return []
        commands: list[str] = []
        seen: set[str] = set()
        preferred_section = re.search(
            r"##\s*Remediation Script\s*```(?:bash|sh|shell)?\s*([\s\S]*?)```",
            str(runbook),
            flags=re.IGNORECASE,
        )
        if preferred_section:
            script = " ".join(
                line.strip()
                for line in preferred_section.group(1).splitlines()
                if line.strip() and not line.strip().startswith("#")
            ).strip()
            if script:
                commands.append(script)
                seen.add(script.lower())
                return commands[:max_items]
        for line in str(runbook).splitlines():
            token = line.strip().lstrip("- ").strip().strip("`")
            if not token:
                continue
            token = re.sub(r"^\s*(cmd|command|script|query)\s*:\s*", "", token, flags=re.IGNORECASE).strip()
            if token.startswith("#"):
                continue
            # Capture command-like steps while avoiding prose-heavy runbook lines.
            if (
                token.startswith(("bash ", "sh ", "pwsh ", "powershell ", "python ", "curl "))
                or token.startswith(("kubectl ", "helm ", "terraform ", "ansible-playbook ", "redis-cli ", "mysql "))
                or token.startswith("scripts/")
                or token.startswith("./")
                or token.startswith("Invoke-")
                or token.startswith("Get-")
            ):
                if token.lower() in seen:
                    continue
                commands.append(token)
                seen.add(token.lower())
            if len(commands) >= max_items:
                break
        return commands

    @staticmethod
    def _sanitize_commands(commands: list[str], *, max_items: int = 4) -> list[str]:
        sanitized: list[str] = []
        seen: set[str] = set()
        for raw in commands:
            token = str(raw or "").strip().strip("`")
            if not token:
                continue
            token = re.sub(r"^\s*(cmd|command|script|query)\s*:\s*", "", token, flags=re.IGNORECASE).strip()
            if not token or token.startswith("#"):
                continue
            if token.lower().startswith("preview only"):
                continue
            if token.lower().startswith("recommended_action"):
                continue
            key = token.lower()
            if key in seen:
                continue
            seen.add(key)
            sanitized.append(token)
            if len(sanitized) >= max_items:
                break
        return sanitized

    @staticmethod
    def _model_call_is_fallback(usage: dict[str, Any] | None) -> bool:
        if not isinstance(usage, dict):
            return False
        provider = ResolutionIntelligenceAgent._norm(usage.get("provider"))
        model = ResolutionIntelligenceAgent._norm(usage.get("model"))
        return (
            bool(usage.get("fallback"))
            or "fallback" in provider
            or "fallback" in model
            or "error" in usage
        )

    @staticmethod
    def _extract_model_text(content: Any, *, fallback_text: str) -> str:
        text = str(content or "").strip()
        if not text:
            return fallback_text
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError):
            return text
        if not isinstance(parsed, dict):
            return text
        metadata = parsed.get("metadata") if isinstance(parsed.get("metadata"), dict) else {}
        if metadata.get("fallback"):
            return fallback_text
        for key in ("root_cause", "summary", "recommended_action", "content", "title"):
            value = parsed.get(key)
            if str(value or "").strip():
                return str(value).strip()
        return fallback_text

    def _infer_root_cause(self, context: Context, model_root_cause: str) -> str:
        deployment = str(context.deployment or "").strip()
        description = self._norm(context.alert.description)
        if deployment and any(keyword in description for keyword in ["deploy", "release", "rollout", "version"]):
            return deployment

        for change in context.recent_changes[:5]:
            message = self._norm(change.get("message") or change.get("title"))
            if any(keyword in message for keyword in ["deploy", "release", "rollback", "config", "schema"]):
                return str(change.get("message") or change.get("title") or model_root_cause).strip()

        return str(model_root_cause or f"Likely degradation in {context.alert.service}").strip()

    def _infer_action_and_commands(self, context: Context, root_cause: str, model_action: str) -> tuple[str, list[str], str]:
        description = self._norm(context.alert.description)
        root = self._norm(root_cause)
        runbook = str(context.runbook or "")
        runbook_commands = self._sanitize_commands(self._extract_runbook_commands(runbook), max_items=4)
        if runbook_commands:
            target = str(context.alert.service or "service").strip()
            return (
                "Execute approved runbook remediation script and validation checks",
                runbook_commands,
                target,
            )

        if any(keyword in root for keyword in ["deploy", "release", "rollout", "version"]):
            target = str(context.kubernetes.get("deployment") or context.alert.service or "service").strip()
            return (
                "Rollback deployment",
                runbook_commands or [f"kubectl rollout undo deployment/{target} -n prod"],
                target,
            )

        if "pod" in description or "oom" in description or "crashloop" in description:
            target = str(context.kubernetes.get("deployment") or context.alert.service or "service").strip()
            return (
                "Restart pod",
                runbook_commands or [f"kubectl rollout restart deployment/{target} -n prod"],
                target,
            )

        if "latency" in description or "timeout" in description:
            target = str(context.alert.service or "service").strip()
            return (
                "Scale deployment and validate latency reduction",
                runbook_commands or [f"kubectl scale deployment/{target} --replicas=3 -n prod"],
                target,
            )

        if "database" in description or "replica" in description:
            target = str(context.alert.service or "database").strip()
            return (
                "Fail over database and validate replication health",
                runbook_commands or ["mysql -e \"SHOW REPLICA STATUS;\""],
                target,
            )

        target = str(context.alert.service or "service").strip()
        action = str(model_action or "Investigate service and apply runbook remediation").strip()
        if runbook_commands:
            return action, runbook_commands, target
        fallback_commands = [
            f"kubectl rollout status deployment/{target} -n prod --timeout=180s",
            f"kubectl get pods -n prod | findstr {target}",
        ]
        return action, self._sanitize_commands(fallback_commands, max_items=4), target

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
            response_model = str(response.get("model") or "unknown")
            if "fallback" in response_model.lower() or self._model_call_is_fallback(usage):
                usage["fallback"] = True
            return {
                "model": response_model,
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

    async def _judge_groundedness(self, *, prediction: str, context_text: str) -> EvaluationResult | None:
        """Best-effort LLM-judge groundedness score. Never raises, never blocks resolve()."""
        if not self.evaluation_client.enabled or not context_text.strip():
            return None
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(
                    self.evaluation_client.evaluate,
                    prediction,
                    metric="groundedness",
                    context=context_text,
                ),
                timeout=self.model_step_timeout_seconds,
            )
        except Exception:
            return None

    async def _post_evaluation(self, payload: dict[str, Any]) -> None:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(f"{self.evaluation_service_url.rstrip('/')}/evaluations", json=payload)
            response.raise_for_status()
        except Exception as exc:
            logger.warning("evaluation_service_publish_failed", extra={"error": str(exc)})

    def _publish_evaluation(self, *, recommendation: Recommendation, report: dict[str, Any]) -> None:
        """Fire-and-forget: never awaited, never allowed to affect resolve()'s result."""
        model_calls = recommendation.metadata.get("model_calls")
        last_call = model_calls[-1] if isinstance(model_calls, list) and model_calls else {}
        payload = {
            "report": report,
            "agent": self.name,
            "incident_id": str(recommendation.incident_id),
            "recommendation_id": str(recommendation.id),
            "model_provider": str(last_call.get("provider") or "") or None,
            "model_name": str(last_call.get("model") or "") or None,
        }
        task = asyncio.create_task(self._post_evaluation(payload))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

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
        content = self._extract_model_text(response["content"], fallback_text=f"Likely service degradation in {context.alert.service}")
        state["root_cause"] = self._infer_root_cause(context, content)
        state["rationale"] = f"Model {response['model']} linked symptoms to {state['root_cause']}"
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
        if "latency" in context.alert.description.lower():
            state["impact"] = f"{context.alert.service.title()} latency"
        else:
            state["impact"] = self._extract_model_text(
                response["content"],
                fallback_text=f"{context.alert.service.title()} service impact requires immediate triage",
            )
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
        prompt = PROMPT_RECOMMEND_REMEDIATION
        payload = {"service": context.alert.service, "runbook": context.runbook, "root_cause": state.get("root_cause", "")}
        response = await self._generate_with_fallback(
            context=context,
            task=ModelTask.FIX,
            prompt=prompt,
            payload=payload,
            fallback_content=f"Investigate {context.alert.service} health and apply documented runbook remediation",
        )
        model_action = self._extract_model_text(
            response["content"],
            fallback_text=f"Investigate {context.alert.service} health and apply documented runbook remediation",
        )
        action, commands, remediation_target = self._infer_action_and_commands(
            context,
            str(state.get("root_cause") or ""),
            model_action,
        )
        state["remediation_target"] = remediation_target
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
        score = 0.5
        if context.deployment:
            score += 0.18
        if context.related_incidents:
            score += 0.12
        if context.runbook:
            score += 0.1
        if context.alert.severity in {AlertSeverity.HIGH, AlertSeverity.CRITICAL}:
            score += 0.05
        if state.get("commands"):
            score += 0.05

        fallback_hits = 0
        for usage in state.get("model_usage", []):
            if self._model_call_is_fallback(usage):
                fallback_hits += 1
        if fallback_hits:
            score -= min(0.2, 0.08 * fallback_hits)
            score = min(score, 0.64)
        if fallback_hits >= max(1, len(state.get("model_usage", []))):
            score = min(score, 0.49)

        state["confidence"] = round(max(0.05, min(score, 0.99)), 4)
        return state

    async def resolve(self, context: Context) -> Recommendation:
        state = await self.graph.ainvoke({"context": context})
        runbook_present = bool((context.runbook or "").strip())
        evidence = [
            Evidence(
                id=f"ctx:{context.incident_id}",
                type="context",
                source="context-agent",
                confidence=0.9,
                metadata={"service": context.alert.service},
                content={"related_incidents": len(context.related_incidents)},
            ),
            Evidence(
                id=f"runbook:{context.incident_id}",
                type="runbook",
                source="knowledge-router",
                confidence=0.85 if runbook_present else 0.25,
                metadata={"present": runbook_present},
                content={"preview": (context.runbook or "")[:180]},
            ),
        ]
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
        recommendation.metadata["reasoning"] = state.get("rationale", "")
        recommendation.metadata["service"] = str(context.alert.service or "")
        recommendation.metadata["environment"] = str(context.alert.environment or "prod")
        recommendation.metadata["remediation_target"] = str(state.get("remediation_target") or context.alert.service or "")
        recommendation.metadata["recommended_commands"] = state.get("commands", [])
        fallback_usages = [usage for usage in state.get("model_usage", []) if self._model_call_is_fallback(usage)]
        recommendation.metadata["fallback_used"] = bool(fallback_usages)
        recommendation.metadata["fallback_reason"] = "; ".join(
            str(usage.get("error") or usage.get("fallback_reason") or "model-router fallback")
            for usage in fallback_usages
        )[:800] or None
        recommendation.metadata["quality_gate"] = {
            "trusted_for_auto_execution": not fallback_usages and recommendation.confidence >= 0.9,
            "requires_human_review": bool(fallback_usages) or recommendation.confidence < 0.75,
            "reason": "model fallback used" if fallback_usages else "confidence policy",
        }
        recommendation.metadata["citations"] = [
            f"runbook://{context.alert.service}",
            f"incident://{context.incident_id}",
        ]
        external_judge = await self._judge_groundedness(
            prediction=f"{recommendation.root_cause} {recommendation.recommended_action} {recommendation.rationale}",
            context_text=context.runbook or "",
        )
        recommendation.metadata["evaluation"] = build_quality_evaluation(
            prediction={
                "root_cause": recommendation.root_cause,
                "impact": recommendation.impact,
                "recommended_action": recommendation.recommended_action,
                "rationale": recommendation.rationale,
                "commands": recommendation.commands,
            },
            context={
                "alert": context.alert.model_dump(mode="json"),
                "runbook": context.runbook,
                "related_incidents": context.related_incidents,
                "metadata": context.metadata,
            },
            confidence=recommendation.confidence,
            citations=recommendation.metadata["citations"],
            rag_matches=context.metadata.get("rag_matches", []) if isinstance(context.metadata, dict) else [],
            runbook_found=runbook_present,
            fallback_used=any(
                str((usage or {}).get("provider") or "").lower() == "fallback"
                or str((usage or {}).get("model") or "").lower() == "fallback"
                or "error" in (usage or {})
                for usage in state.get("model_usage", [])
            ),
            external=external_judge,
        )
        self._publish_evaluation(recommendation=recommendation, report=recommendation.metadata["evaluation"])
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
        if result.confidence <= 0:
            raise ValidationError("confidence must be greater than zero")
        evidence_ids = result.metadata.get("evidence_ids", [])
        if not isinstance(evidence_ids, list) or not evidence_ids:
            raise ValidationError("recommendation must include evidence_ids")
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
        quality = "high" if confidence >= 0.85 else "medium" if confidence >= 0.65 else "low"
        return {
            "agent": self.name,
            "quality": quality,
            "lessons_learned": [
                "Preserve runbook and incident evidence links in every recommendation.",
                "Escalate to approval path when confidence is below policy threshold.",
            ],
            "failed_tool_calls": [],
            "missing_evidence": [] if confidence >= 0.5 else ["runbook", "related_incidents"],
            "confidence_adjustment": 0.0,
            "error": str(error) if error else None,
        }
