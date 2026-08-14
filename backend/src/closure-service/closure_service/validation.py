from __future__ import annotations

import httpx

from ai_workbench_common.agentic import AgentContext, BaseAgent
from common.models import RemediationAction, RemediationStatus, ResolutionReport


class ClosureValidationAgent(BaseAgent):
    name = "validation-agent"

    async def can_execute(self, context: AgentContext) -> bool:
        return "remediation-action" in context.previous_agent_results

    async def execute(self, context: AgentContext) -> ResolutionReport:
        action_payload = context.previous_agent_results.get("remediation-action")
        if not isinstance(action_payload, dict):
            raise ValueError("AgentContext.previous_agent_results['remediation-action'] is required")
        report = await self.validate(RemediationAction.model_validate(action_payload))
        context.set_result(self.name, report.model_dump(mode="json"))
        return report

    async def validate(self, action: RemediationAction) -> ResolutionReport:
        execution_plan = action.parameters.get("execution_plan")
        execution_plan = execution_plan if isinstance(execution_plan, dict) else {}
        queries = execution_plan.get("queries")
        queries = [str(item).strip() for item in queries] if isinstance(queries, list) else []
        health_urls = [item for item in queries if item.startswith(("http://", "https://"))]
        validation: dict[str, bool] = {"remediation_succeeded": action.status == RemediationStatus.SUCCEEDED}
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=3.0)) as client:
            for index, url in enumerate(health_urls, start=1):
                try:
                    response = await client.get(url)
                    validation[f"health_check_{index}"] = 200 <= response.status_code < 300
                except httpx.HTTPError:
                    validation[f"health_check_{index}"] = False
        validation["validation_supplied"] = bool(health_urls)
        validation["alerts_cleared"] = bool(health_urls) and all(
            passed for name, passed in validation.items() if name.startswith("health_check_")
        )
        restored = all(validation.values())
        action_taken = action.output or action.action_type
        return ResolutionReport(
            incident_id=action.incident_id,
            remediation_action_id=action.id,
            root_cause=action.parameters.get("root_cause", "Deployment or runtime change"),
            impact=action.parameters.get("impact", "Service degradation"),
            action_taken=action_taken,
            validation=validation,
            alerts_cleared=validation["alerts_cleared"],
            health_restored=restored,
            knowledge_base_entry=(
                f"Incident {action.incident_id} resolved via {action.action_type}. Validation: {validation}."
            ),
            lessons_learned=[
                "Compare alert onset with deployment/change windows.",
                "Prefer reversible remediation for high-confidence deployment regressions.",
                "Require an explicit health endpoint or governed recovery query before closure.",
            ],
        )
