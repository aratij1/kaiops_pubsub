from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Protocol

from common.agentic import AgentContext, BaseAgent
from common.execution_safety import ExecutionSafetyDecision, assess_execution_safety
from common.models import Approval, RemediationAction, RemediationStatus, utc_now
from common.resilience import CircuitBreaker, circuit_breaker
from common.tool_registry import ToolRegistry, ToolSpec


class RemediationPlugin(Protocol):
    action_type: str

    async def execute(self, action: RemediationAction) -> RemediationAction: ...


@dataclass
class BasePlugin:
    action_type: str
    breaker: CircuitBreaker = field(default_factory=CircuitBreaker)

    async def _simulate(self, action: RemediationAction, command: str) -> RemediationAction:
        await asyncio.sleep(0)
        action.output = f"executed {command} on {action.target}"
        action.status = RemediationStatus.SUCCEEDED
        return action


class JenkinsRollbackPlugin(BasePlugin):
    def __init__(self) -> None:
        super().__init__("rollback_deployment")

    @circuit_breaker(CircuitBreaker())
    async def execute(self, action: RemediationAction) -> RemediationAction:
        return await self._simulate(action, "jenkins rollback job")


class KubernetesRestartPlugin(BasePlugin):
    def __init__(self) -> None:
        super().__init__("restart_pod")

    @circuit_breaker(CircuitBreaker())
    async def execute(self, action: RemediationAction) -> RemediationAction:
        return await self._simulate(action, "kubectl rollout restart")


class AnsibleRemediationPlugin(BasePlugin):
    def __init__(self) -> None:
        super().__init__("restart_service")

    async def execute(self, action: RemediationAction) -> RemediationAction:
        return await self._simulate(action, "ansible-playbook remediation.yml")


class TerraformRollbackPlugin(BasePlugin):
    def __init__(self) -> None:
        super().__init__("terraform_rollback")

    async def execute(self, action: RemediationAction) -> RemediationAction:
        return await self._simulate(action, "terraform apply previous plan")


class ApiExecutionPlugin(BasePlugin):
    def __init__(self) -> None:
        super().__init__("api_execution")

    async def execute(self, action: RemediationAction) -> RemediationAction:
        return await self._simulate(action, "REST API remediation")


@dataclass
class RemediationEngine(BaseAgent):
    plugins: dict[str, RemediationPlugin] = field(
        default_factory=lambda: {
            "rollback_deployment": JenkinsRollbackPlugin(),
            "restart_pod": KubernetesRestartPlugin(),
            "scale_deployment": KubernetesRestartPlugin(),
            "restart_service": AnsibleRemediationPlugin(),
            "clear_cache": ApiExecutionPlugin(),
            "failover_database": ApiExecutionPlugin(),
            "api_execution": ApiExecutionPlugin(),
            "terraform_rollback": TerraformRollbackPlugin(),
        }
    )
    tool_registry: ToolRegistry = field(default_factory=ToolRegistry)
    name: str = "automation-agent"

    def __post_init__(self) -> None:
        if self.tool_registry.tools:
            return

        async def _build_tool_handler(plugin: RemediationPlugin, payload: dict[str, Any]) -> dict[str, Any]:
            action_payload = payload.get("action")
            if not isinstance(action_payload, dict):
                raise ValueError("tool payload must include 'action'")
            action = RemediationAction.model_validate(action_payload)
            completed = await plugin.execute(action)
            return completed.model_dump(mode="json")

        for action_type, plugin in self.plugins.items():

            async def handler(payload: dict[str, Any], _plugin: RemediationPlugin = plugin) -> dict[str, Any]:
                return await _build_tool_handler(_plugin, payload)

            self.tool_registry.register(
                ToolSpec(
                    name=action_type,
                    handler=handler,
                    timeout_seconds=12.0,
                    permissions={"automation-agent"},
                )
            )

    async def can_execute(self, context: AgentContext) -> bool:
        return "approval" in context.previous_agent_results

    def is_action_allowed(self, action_type: str) -> bool:
        normalized = str(action_type or "").strip().lower()
        if not normalized:
            return False
        return normalized in set(self.plugins.keys())

    def build_action(self, approval: Approval) -> RemediationAction:
        action_text = (approval.modified_action or approval.comment or "rollback deployment").lower()
        if "restart pod" in action_text:
            action_type = "restart_pod"
        elif "scale" in action_text:
            action_type = "scale_deployment"
        elif "restart service" in action_text:
            action_type = "restart_service"
        elif "cache" in action_text:
            action_type = "clear_cache"
        elif "failover" in action_text or "database" in action_text:
            action_type = "failover_database"
        elif "terraform" in action_text:
            action_type = "terraform_rollback"
        else:
            action_type = "rollback_deployment"
        policy_version = str(approval.metadata.get("policy_version", "")).strip()
        policy_reason = str(approval.metadata.get("policy_reason", "")).strip()
        return RemediationAction(
            incident_id=approval.incident_id,
            approval_id=approval.id,
            action_type=action_type,
            target=str(approval.incident_id),
            parameters={
                "approved_by": approval.approver,
                "channel": approval.channel,
                "policy_version": policy_version,
                "policy_reason": policy_reason,
            },
            started_at=utc_now(),
            status=RemediationStatus.RUNNING,
        )

    async def execute(self, action: RemediationAction) -> RemediationAction:
        allowed_actions = set(self.plugins.keys())
        assessment = assess_execution_safety(action, allowlisted_actions=allowed_actions)
        action.parameters["pre_execution_snapshot"] = assessment.snapshot
        action.parameters["pre_execution_snapshot_hash"] = assessment.snapshot_hash
        action.parameters["execution_idempotency_key"] = assessment.idempotency_key

        if assessment.decision == ExecutionSafetyDecision.BLOCK:
            action.status = RemediationStatus.SKIPPED
            action.error = assessment.reason
            action.output = "remediation blocked by execution safety controller"
            action.completed_at = utc_now()
            return action

        action_type = str(action.action_type or "").strip().lower()
        if action_type not in self.tool_registry.tools:
            action.status = RemediationStatus.SKIPPED
            action.error = "ACTION_TYPE_NOT_REGISTERED"
            action.output = "remediation blocked by tool registry"
            action.completed_at = utc_now()
            return action

        try:
            payload = await self.tool_registry.execute(
                action_type,
                {"action": action.model_dump(mode="json")},
                role="automation-agent",
            )
            completed = RemediationAction.model_validate(payload)
            completed.completed_at = utc_now()
            return completed
        except Exception as exc:
            action.status = RemediationStatus.FAILED
            action.error = str(exc)
            action.completed_at = utc_now()
            return action

    async def execute_from_context(self, context: AgentContext) -> RemediationAction:
        approval_payload = context.previous_agent_results.get("approval")
        if not isinstance(approval_payload, dict):
            raise ValueError("AgentContext.previous_agent_results['approval'] is required")
        action = self.build_action(Approval.model_validate(approval_payload))
        result = await self.execute(action)
        context.set_result("remediation-action", result.model_dump(mode="json"))
        return result

    async def validate(self, result: Any) -> bool:
        return isinstance(result, RemediationAction)
