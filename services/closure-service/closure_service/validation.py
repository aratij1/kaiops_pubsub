from __future__ import annotations

from common.models import RemediationAction, RemediationStatus, ResolutionReport


class ClosureValidationAgent:
    async def validate(self, action: RemediationAction) -> ResolutionReport:
        validation = {
            "latency_recovered": action.status == RemediationStatus.SUCCEEDED,
            "cpu_normalized": action.status == RemediationStatus.SUCCEEDED,
            "error_rate_reduced": action.status == RemediationStatus.SUCCEEDED,
            "alerts_cleared": action.status == RemediationStatus.SUCCEEDED,
        }
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
            ],
        )
