from __future__ import annotations

import httpx
from uuid import NAMESPACE_URL, uuid5

from ai_workbench_common.agentic import AgentContext, BaseAgent
from common.models import RemediationAction, RemediationStatus, ResolutionReport
from common.resolution_lifecycle import LifecycleActor, ResolutionState, extract_lifecycle, transition_lifecycle


def _validation_urls(plan: dict) -> tuple[list[str], int]:
    supplied: list[str] = []
    for key in ("validation_commands", "validation_queries", "queries"):
        values = plan.get(key)
        if isinstance(values, list):
            supplied.extend(str(item).strip() for item in values if str(item).strip())
    # Plans may expose the same governed check under both `queries` and
    # `validation_commands` for compatibility. Count canonical checks once;
    # otherwise a single valid health URL is incorrectly classified as only
    # half executable and a successful remediation is projected as failed.
    unique_supplied = list(dict.fromkeys(supplied))
    urls: list[str] = []
    non_executable_count = 0
    for check in unique_supplied:
        if check.startswith(("http://", "https://")):
            urls.append(check)
            continue
        found_url = False
        for token in check.replace('"', " ").replace("'", " ").split():
            if token.startswith(("http://", "https://")):
                urls.append(token)
                found_url = True
                break
        if not found_url:
            non_executable_count += 1
    unique_urls = list(dict.fromkeys(urls))
    return unique_urls, len(unique_urls) + non_executable_count


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
        health_urls, supplied_count = _validation_urls(execution_plan)
        diagnostic_closure = bool(action.parameters.get("diagnostic_closure")) and action.status == RemediationStatus.SKIPPED
        if diagnostic_closure:
            details = action.parameters.get("diagnostic_details")
            details = details if isinstance(details, dict) else {}
            validation = {
                "diagnostic_completed": True,
                "corrective_action_executed": False,
                "evidence_recorded": bool(details or execution_plan),
                "execution_not_applicable": True,
            }
            lifecycle = extract_lifecycle(action.parameters, action.metadata)
            if lifecycle:
                lifecycle = transition_lifecycle(
                    lifecycle,
                    ResolutionState.CLOSED,
                    actor=LifecycleActor.CLOSURE,
                    reason_code="diagnostic_completed_no_corrective_action",
                    validation={"checks": validation, "passed": True},
                )
            return ResolutionReport(
                id=uuid5(NAMESPACE_URL, f"kaiops:closure:{action.id}:diagnostic"),
                incident_id=action.incident_id,
                remediation_action_id=action.id,
                root_cause=str(action.parameters.get("root_cause") or "Diagnostic analysis completed"),
                impact=str(action.parameters.get("impact") or "No confirmed recoverable service impact"),
                action_taken=action.output or "Diagnostic-only plan completed; no corrective action executed.",
                validation=validation,
                alerts_cleared=False,
                health_restored=False,
                knowledge_base_entry=f"Incident {action.incident_id} remains open after diagnostic analysis; no corrective operation or recovery validation was performed. Details: {details}",
                lessons_learned=[
                    "Diagnostic completion does not establish alert clearance or service recovery.",
                    "Attach a reviewed corrective playbook if future matching incidents require automated remediation.",
                ],
                metadata={
                    "closure_kind": "diagnostic",
                    "diagnostic_details": details,
                    **({"resolution_lifecycle": lifecycle} if lifecycle else {}),
                },
            )
        validation: dict[str, bool] = {"remediation_succeeded": action.status == RemediationStatus.SUCCEEDED}
        execution_result = action.parameters.get("execution_result")
        execution_result = execution_result if isinstance(execution_result, dict) else {}
        recovery_evidence = execution_result.get("recovery_evidence")
        recovery_evidence = recovery_evidence if isinstance(recovery_evidence, dict) else {}
        executor_recovery_validated = bool(
            execution_result.get("recovery_validated") is True
            and recovery_evidence.get("recovery_validated") is True
            and recovery_evidence.get("executed") is True
            and str(execution_result.get("build_result") or "").upper() == "SUCCESS"
        )
        validation["executor_recovery_validated"] = executor_recovery_validated
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=3.0)) as client:
            for index, url in enumerate(health_urls, start=1):
                try:
                    response = await client.get(url)
                    validation[f"health_check_{index}"] = 200 <= response.status_code < 300
                except httpx.HTTPError:
                    validation[f"health_check_{index}"] = False
        validation["validation_supplied"] = supplied_count > 0
        validation["validation_executable"] = supplied_count > 0 and len(health_urls) == supplied_count
        independent_checks_passed = bool(health_urls) and all(
            passed for name, passed in validation.items() if name.startswith("health_check_")
        )
        validation["independent_checks_passed"] = independent_checks_passed
        # Executor success proves only that the approved command completed. It
        # is never recovery proof. Closure requires independently collected
        # operational and stability evidence.
        recovery_checks = {
            "triggering_alert_cleared": recovery_evidence.get("triggering_alert_cleared") is True,
            "availability_recovered": recovery_evidence.get("availability_recovered") is True or independent_checks_passed,
            "error_rate_recovered": recovery_evidence.get("error_rate_recovered") is True,
            "latency_within_slo": recovery_evidence.get("latency_within_slo") is True,
            "dependency_health_stable": recovery_evidence.get("dependency_health_stable") is True,
            "no_new_critical_alerts": recovery_evidence.get("no_new_critical_alerts") is True,
            "stability_window_completed": recovery_evidence.get("stability_window_completed") is True,
        }
        if recovery_evidence.get("business_check_available") is True:
            recovery_checks["business_check_passed"] = recovery_evidence.get("business_check_passed") is True
        validation.update(recovery_checks)
        validation["alerts_cleared"] = recovery_checks["triggering_alert_cleared"]
        validation["all_recovery_checks_passed"] = all(recovery_checks.values())
        restored = (
            validation["remediation_succeeded"]
            and validation["validation_supplied"]
            and validation["all_recovery_checks_passed"]
        )
        lifecycle = extract_lifecycle(action.parameters, action.metadata)
        # Closure never reclassifies an executor failure. The remediation
        # service owns that attempt outcome and the event handler will not
        # normally invoke closure for it. Keeping the lifecycle unchanged here
        # also makes the public validator safe for diagnostic/API callers.
        if lifecycle and action.status == RemediationStatus.SUCCEEDED:
            if lifecycle.get("state") == ResolutionState.EXECUTING.value:
                lifecycle = transition_lifecycle(
                    lifecycle,
                    ResolutionState.VALIDATING,
                    actor=LifecycleActor.REMEDIATION,
                    execution={"action_id": str(action.id), "status": action.status.value},
                )
            lifecycle = transition_lifecycle(
                lifecycle,
                ResolutionState.RECOVERED if restored else ResolutionState.FAILED_RETRYABLE,
                actor=LifecycleActor.CLOSURE,
                reason_code=None if restored else "recovery_validation_failed",
                validation={"checks": validation, "passed": restored},
            )
        action_taken = action.output or action.action_type
        return ResolutionReport(
            id=uuid5(
                NAMESPACE_URL,
                f"kaiops:closure:{action.id}:{'recovered' if restored else 'validation_failed'}",
            ),
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
            metadata={"resolution_lifecycle": lifecycle} if lifecycle else {},
        )
