export type WorkflowStageStatus = "done" | "active" | "blocked" | "waiting";

export interface WorkflowStage {
  id: string;
  label: string;
  detail: string;
  status: WorkflowStageStatus;
}

export function buildWorkflowFlowStages(workflow: any, timelineRows: any[] = []): WorkflowStage[] {
  const safeWorkflow = workflow && typeof workflow === "object" ? workflow : {};
  const safeRows = Array.isArray(timelineRows) ? timelineRows : [];
  const findStage = (needle: string) => safeRows.find((row) =>
    String(row?.stage || row?.agent || row?.detail || "").toLowerCase().includes(needle));
  const hasParallelProcessing = safeRows.some((row) => {
    const token = String(row?.agent || row?.service || row?.detail || "").toLowerCase();
    return ["alert intelligence", "orchestrator", "context", "resolution"].some((name) => token.includes(name));
  });
  const remediation = safeWorkflow?.remediation_action && typeof safeWorkflow.remediation_action === "object"
    ? safeWorkflow.remediation_action : {};
  const remediationStatus = String(remediation.status || "").trim().toLowerCase();
  const remediationPolicyBlocked = String(remediation.action_type || "").trim().toLowerCase() === "policy-blocked"
    || remediation?.metadata?.policy_blocked === true;
  const closureComplete = safeWorkflow?.closure_report?.health_restored === true;

  return [
    { id: "landing-pad", label: "Landing Pad", detail: "Raw alerts are accepted, normalized, and added to the incident stream.", status: findStage("landing") ? "done" : "active" },
    {
      id: "parallel-processing", label: "Parallel Processing",
      detail: hasParallelProcessing
        ? "Alert intelligence, orchestration, context, and resolution work the stream in parallel workers."
        : "Backend workers fan out the alert stream through independent services for concurrent processing.",
      status: hasParallelProcessing ? "done" : "active",
    },
    { id: "approval", label: "Approval Gate", detail: String(safeWorkflow?.approval?.status || safeWorkflow?.decision?.status || "pending").trim(), status: safeWorkflow?.approval?.status ? "done" : "active" },
    {
      id: "remediation", label: "Remediation Execution",
      detail: remediationPolicyBlocked
        ? String(remediation.error || remediation.metadata?.policy_reason || "Execution blocked by policy; operator review is required.")
        : `${Array.isArray(remediation?.parameters?.execution_plan?.commands) ? remediation.parameters.execution_plan.commands.length : 0} commands captured for execution or review.`,
      status: remediationPolicyBlocked ? "blocked" : remediationStatus ? "done" : "waiting",
    },
    {
      id: "closure", label: "Closure & Validation",
      detail: closureComplete ? "Service restored and closure completed." : remediationPolicyBlocked
        ? "Waiting for an approved remediation outcome before validation." : "Validation starts after remediation completes.",
      status: closureComplete ? "done" : "waiting",
    },
  ];
}
