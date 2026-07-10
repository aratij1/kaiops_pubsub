from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from common.config import Settings, get_settings
from common.models import AlertSeverity
from common.orchestration.config_loader import load_orchestration_config
from common.orchestration.policy_engine import PolicyEngine

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class WorkflowDefinition:
    name: str
    steps: list[str]
    next_action: str


@dataclass(slots=True)
class WorkflowSelection:
    definition: WorkflowDefinition
    requires_approval: bool
    message_bus_provider: str
    stream_count: int
    stream_threshold: int
    risk_tier: str = "medium"
    execution_mode: str = "human-approval"
    policy_reason: str = "severity gate"
    planner_used: bool = False
    planner_model: str | None = None
    planner_reason: str = "deterministic severity routing"


@dataclass(slots=True)
class WorkflowEngine:
    policy_engine: PolicyEngine = field(default_factory=PolicyEngine)
    settings: Settings = field(default_factory=get_settings)
    stream_threshold: int = 500
    orchestration_config: dict[str, Any] = field(default_factory=dict)
    workflow_definitions: dict[str, WorkflowDefinition] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.orchestration_config = load_orchestration_config(self.settings)
        message_bus = self.orchestration_config.get("message_bus", {})
        self.stream_threshold = int(message_bus.get("stream_threshold", self.stream_threshold) or 500)

        definitions = self.orchestration_config.get("workflow_definitions", {})
        if isinstance(definitions, dict):
            self.workflow_definitions = {
                name: WorkflowDefinition(
                    name=name,
                    steps=list(raw_definition.get("steps", [])),
                    next_action=str(raw_definition.get("next_action") or "collect-context"),
                )
                for name, raw_definition in definitions.items()
                if isinstance(name, str) and isinstance(raw_definition, dict)
            }

    def route_message_bus(self, *, stream_count: int | None) -> tuple[str, int, int]:
        normalized_count = max(0, int(stream_count or 0))
        message_bus = self.orchestration_config.get("message_bus", {})
        dynamic_enabled = bool(message_bus.get("dynamic_routing", True))
        default_provider = str(message_bus.get("default_provider", "rabbitmq")).strip().lower()
        if default_provider not in {"kafka", "rabbitmq", "pubsub"}:
            default_provider = "rabbitmq"
        provider = default_provider
        if dynamic_enabled:
            if default_provider == "pubsub":
                provider = "pubsub"
            else:
                provider = "kafka" if normalized_count > self.stream_threshold else "rabbitmq"
        return provider, normalized_count, self.stream_threshold

    def _definition_for_name(self, workflow_name: str) -> WorkflowDefinition | None:
        return self.workflow_definitions.get(workflow_name)

    def _deterministic_definition(self, severity: AlertSeverity) -> WorkflowDefinition:
        if severity == AlertSeverity.CRITICAL:
            return self._definition_for_name("critical-auto-remediation") or WorkflowDefinition(
                name="critical-auto-remediation",
                steps=["alert-intelligence-agent"],
                next_action="collect-context",
            )
        if severity == AlertSeverity.HIGH:
            return self._definition_for_name("guided-remediation") or WorkflowDefinition(
                name="guided-remediation",
                steps=["alert-intelligence-agent"],
                next_action="collect-context",
            )
        return self._definition_for_name("triage-only") or WorkflowDefinition(
            name="triage-only",
            steps=["alert-intelligence-agent"],
            next_action="collect-context",
        )

    @staticmethod
    def _extract_json_object(raw: str) -> dict[str, str]:
        content = str(raw or "").strip()
        if not content:
            return {}
        if "```" in content:
            parts = [part.strip() for part in content.split("```") if part.strip()]
            for part in parts:
                candidate = part
                if candidate.lower().startswith("json"):
                    candidate = candidate[4:].strip()
                try:
                    parsed = json.loads(candidate)
                    return parsed if isinstance(parsed, dict) else {}
                except Exception:
                    continue
        try:
            parsed = json.loads(content)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _workflow_name_from_text(raw: str) -> str | None:
        text = str(raw or "").strip().lower()
        if not text:
            return None
        if "critical-auto-remediation" in text or "critical" in text:
            return "critical-auto-remediation"
        if "guided-remediation" in text or "guided" in text:
            return "guided-remediation"
        if "triage-only" in text or "triage" in text:
            return "triage-only"
        return None

    async def _plan_workflow_name(
        self,
        *,
        severity: AlertSeverity,
        confidence: float | None,
        stream_count: int,
        stream_threshold: int,
    ) -> tuple[str | None, str | None, str]:
        try:
            from model_router import ModelRouter, ModelTask
        except Exception:
            return None, None, "planner unavailable: model_router import failed"

        prompt = (
            "Select exactly one workflow for incident orchestration. "
            "Allowed workflows: critical-auto-remediation, guided-remediation, triage-only. "
            "Respond as compact JSON with keys workflow and reason."
        )
        payload = {
            "severity": severity.value,
            "confidence": confidence,
            "stream_count": stream_count,
            "stream_threshold": stream_threshold,
            "approval_threshold": float(self.policy_engine.policies.get("confidence_auto_execute_threshold", 0.9)),
        }

        try:
            router = ModelRouter()
            response = await router.route(
                severity=severity,
                task=ModelTask.GENERAL,
                prompt=prompt,
                payload=payload,
            )
        except Exception as exc:
            logger.warning("workflow planner route failed: %s", exc)
            return None, None, "planner failed; deterministic fallback"

        model = str(response.get("model") or "") or None
        content = str(response.get("content") or "")
        parsed = self._extract_json_object(content)
        planned_workflow = str(parsed.get("workflow") or "").strip().lower()
        if not planned_workflow:
            planned_workflow = self._workflow_name_from_text(content) or ""
        if planned_workflow not in {"critical-auto-remediation", "guided-remediation", "triage-only"}:
            return None, model, "planner returned unsupported workflow"

        reason = str(parsed.get("reason") or "").strip() or "llm workflow planner selection"
        return planned_workflow, model, reason

    def select(
        self,
        *,
        severity: AlertSeverity,
        confidence: float | None = None,
        stream_count: int | None = None,
    ) -> WorkflowSelection:
        definition = self._deterministic_definition(severity)
        message_bus_provider, normalized_stream_count, stream_threshold = self.route_message_bus(stream_count=stream_count)
        decision = self.policy_engine.evaluate(severity=severity, confidence=confidence)

        return WorkflowSelection(
            definition=definition,
            requires_approval=decision.requires_approval,
            message_bus_provider=message_bus_provider,
            stream_count=normalized_stream_count,
            stream_threshold=stream_threshold,
            risk_tier=decision.risk_tier,
            execution_mode=decision.execution_mode,
            policy_reason=decision.reason,
        )

    async def select_with_planner(
        self,
        *,
        severity: AlertSeverity,
        confidence: float | None = None,
        stream_count: int | None = None,
    ) -> WorkflowSelection:
        base = self.select(severity=severity, confidence=confidence, stream_count=stream_count)
        if not bool(getattr(self.settings, "orchestration_llm_planner_enabled", False)):
            return base

        planned_workflow_name, planner_model, planner_reason = await self._plan_workflow_name(
            severity=severity,
            confidence=confidence,
            stream_count=base.stream_count,
            stream_threshold=base.stream_threshold,
        )
        if not planned_workflow_name:
            return WorkflowSelection(
                definition=base.definition,
                requires_approval=base.requires_approval,
                message_bus_provider=base.message_bus_provider,
                stream_count=base.stream_count,
                stream_threshold=base.stream_threshold,
                risk_tier=base.risk_tier,
                execution_mode=base.execution_mode,
                policy_reason=base.policy_reason,
                planner_used=False,
                planner_model=planner_model,
                planner_reason=planner_reason,
            )

        definition = self._definition_for_name(planned_workflow_name) or base.definition
        return WorkflowSelection(
            definition=definition,
            requires_approval=base.requires_approval,
            message_bus_provider=base.message_bus_provider,
            stream_count=base.stream_count,
            stream_threshold=base.stream_threshold,
            risk_tier=base.risk_tier,
            execution_mode=base.execution_mode,
            policy_reason=base.policy_reason,
            planner_used=True,
            planner_model=planner_model,
            planner_reason=planner_reason,
        )
