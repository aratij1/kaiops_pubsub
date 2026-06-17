from __future__ import annotations

from dataclasses import dataclass

from common.models import Alert, AlertSeverity, Incident


@dataclass
class WorkflowDecision:
    workflow: str
    next_action: str
    downstream_agents: list[str]
    requires_approval: bool


class OrchestratorAgent:
    def decide_workflow(self, alert: Alert, incident: Incident) -> WorkflowDecision:
        if alert.severity == AlertSeverity.CRITICAL:
            return WorkflowDecision(
                workflow="critical-auto-remediation",
                next_action="collect-context",
                downstream_agents=["context-agent", "resolution-agent", "approval-service"],
                requires_approval=True,
            )
        if alert.severity == AlertSeverity.HIGH:
            return WorkflowDecision(
                workflow="guided-remediation",
                next_action="collect-context",
                downstream_agents=["context-agent", "resolution-agent"],
                requires_approval=True,
            )
        return WorkflowDecision(
            workflow="triage-only",
            next_action="collect-context",
            downstream_agents=["context-agent", "resolution-agent"],
            requires_approval=False,
        )
