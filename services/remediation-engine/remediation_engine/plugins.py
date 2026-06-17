from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Protocol

from common.models import Approval, RemediationAction, RemediationStatus, utc_now
from common.resilience import CircuitBreaker, circuit_breaker


class RemediationPlugin(Protocol):
    action_type: str

    async def execute(self, action: RemediationAction) -> RemediationAction:
        ...


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
class RemediationEngine:
    plugins: dict[str, RemediationPlugin] = field(
        default_factory=lambda: {
            "rollback_deployment": JenkinsRollbackPlugin(),
            "restart_pod": KubernetesRestartPlugin(),
            "scale_deployment": KubernetesRestartPlugin(),
            "restart_service": AnsibleRemediationPlugin(),
            "clear_cache": ApiExecutionPlugin(),
            "failover_database": ApiExecutionPlugin(),
            "terraform_rollback": TerraformRollbackPlugin(),
        }
    )

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
        return RemediationAction(
            incident_id=approval.incident_id,
            approval_id=approval.id,
            action_type=action_type,
            target=str(approval.incident_id),
            parameters={"approved_by": approval.approver, "channel": approval.channel},
            started_at=utc_now(),
            status=RemediationStatus.RUNNING,
        )

    async def execute(self, action: RemediationAction) -> RemediationAction:
        plugin = self.plugins.get(action.action_type, self.plugins["api_execution"])
        try:
            completed = await plugin.execute(action)
            completed.completed_at = utc_now()
            return completed
        except Exception as exc:
            action.status = RemediationStatus.FAILED
            action.error = str(exc)
            action.completed_at = utc_now()
            return action
