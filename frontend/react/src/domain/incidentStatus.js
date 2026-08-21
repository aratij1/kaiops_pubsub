const TERMINAL_INCIDENT_STATUSES = new Set(["closed", "resolved", "failed", "cancelled", "canceled"]);
const PENDING_APPROVAL_STATUSES = new Set([
  "awaiting_approval",
  "pending_approval",
  "pending",
  "queued",
  "draft",
  "standby",
  "required",
]);

function normalizeStatus(value) {
  return String(value || "").trim().toLowerCase().replaceAll("-", "_").replaceAll(" ", "_");
}

const USER_LIFECYCLE_STAGES = Object.freeze({
  triage: new Set(["received", "normalized", "correlated", "open", "triaging"]),
  investigate: new Set(["context_ready", "evidence_pending", "evidence_ready", "rca_ready", "investigating", "needs_evidence"]),
  decide: new Set(["plan_ready", "policy_checked", "awaiting_approval", "pending_approval", "approved", "denied"]),
  act: new Set(["preflight", "dispatching", "executor_accepted", "executing", "running", "rolling_back"]),
  verify: new Set(["validating", "verifying", "resolved", "closed", "failed", "rolled_back", "manual_recovery_required"]),
});

export function userLifecycleStage(value) {
  const status = normalizeStatus(value);
  for (const [stage, statuses] of Object.entries(USER_LIFECYCLE_STAGES)) {
    if (statuses.has(status)) return stage;
  }
  return "triage";
}

export function decisionReadiness(input = {}) {
  const missing = [];
  if (Number(input.citationCoverage || 0) <= 0) missing.push("supporting citations");
  if (Number(input.evidenceCoverage || 0) < 0.6) missing.push("sufficient evidence coverage");
  if (input.evidenceFresh === false) missing.push("fresh evidence");
  if (Number(input.conflictCount || 0) > 0) missing.push("resolved conflicting evidence");
  if (!input.runbookAvailable) missing.push("an approved runbook");
  if (!input.preflightReady) missing.push("preflight readiness");
  if (!input.rollbackAvailable) missing.push("rollback readiness");
  if (missing.length) return { state: "not_ready", label: "Not ready—collect evidence", eligible: false, missing };
  if (input.dryRunComplete && input.risk !== "high" && input.risk !== "critical") {
    return { state: "execution_eligible", label: "Eligible for execution approval", eligible: true, missing: [] };
  }
  return { state: "dry_run_eligible", label: "Eligible for dry-run approval", eligible: true, missing: [] };
}

export function incidentStatusLabel(value) {
  const status = normalizeStatus(value);
  if (!status) return "Open";
  const labels = {
    awaiting_approval: "Awaiting approval",
    pending_approval: "Awaiting approval",
    policy_blocked: "Waiting for approval",
    dispatching: "Starting remediation",
    executor_accepted: "Queued for execution",
    execution_failed: "Execution failed",
    validation_failed: "Recovery validation failed",
    manual_intervention_required: "Manual intervention required",
  };
  return labels[status] || status.replaceAll("_", " ").replace(/^./, (character) => character.toUpperCase());
}

// Approval is a gate on execution. A stale or optimistic remediation status
// must never make the incident look as though a live action has started while
// the human decision is still pending.
export function effectiveIncidentStatus(incidentStatus, approvalStatus) {
  const incident = normalizeStatus(incidentStatus) || "open";
  const approval = normalizeStatus(approvalStatus);
  if (!TERMINAL_INCIDENT_STATUSES.has(incident) && PENDING_APPROVAL_STATUSES.has(approval)) {
    return "awaiting_approval";
  }
  return incident;
}

// A Jenkins queue URL is positive evidence that the latest submission is still
// active. It must take precedence over a stale incident failure left by an
// earlier attempt, while a confirmed successful outcome remains terminal.
export function effectiveExecutionStatus(incidentStatus, remediationStatus, queueUrl) {
  const incident = normalizeStatus(incidentStatus);
  const remediation = normalizeStatus(remediationStatus);
  // A policy block that routes the incident to a human is a decision gate,
  // not an execution failure. Keep the operator-facing lifecycle aligned with
  // the canonical incident state while retaining the raw action in technical
  // details for auditability.
  if (PENDING_APPROVAL_STATUSES.has(incident) && remediation === "policy_blocked") {
    return "awaiting_approval";
  }
  if (["succeeded", "completed", "closed", "resolved", "diagnostic_completed"].includes(remediation)
      || ["closed", "resolved"].includes(incident)) {
    return "succeeded";
  }
  if (["failed", "skipped", "policy_blocked", "dispatch_failed", "execution_failed", "validation_failed", "rollback_failed", "timed_out", "cancelled", "manual_intervention_required"].includes(remediation)) {
    return remediation;
  }
  if (["rolled_back", "dispatching", "executor_accepted", "running", "verifying", "rolling_back"].includes(remediation)) {
    return remediation;
  }
  if (String(queueUrl || "").trim() && !remediation) {
    return "executor_accepted";
  }
  if (incident === "failed") {
    return "failed";
  }
  return remediation;
}

const SUCCESS_EXECUTION_STATUSES = new Set(["succeeded", "completed", "closed", "resolved", "diagnostic_completed"]);
const FAILED_EXECUTION_STATUSES = new Set([
  "failed", "skipped", "policy_blocked", "dispatch_failed", "execution_failed", "validation_failed",
  "rollback_failed", "timed_out", "cancelled", "canceled", "manual_intervention_required",
]);
const ACTIVE_EXECUTION_STATUSES = new Set(["dispatching", "executor_accepted", "queued", "running", "verifying", "rolling_back"]);

// A single view model for every executor progress surface. Queue and build URLs
// remain useful links after a run finishes, but are not evidence that the run
// is still queued once the action has a terminal status.
export function executionProcessPresentation(executionStatus, dryRun, configured = false) {
  const status = normalizeStatus(executionStatus);
  const succeeded = SUCCESS_EXECUTION_STATUSES.has(status);
  const failed = FAILED_EXECUTION_STATUSES.has(status);
  const active = ACTIVE_EXECUTION_STATUSES.has(status);
  const queued = status === "executor_accepted" || status === "queued" || status === "dispatching";
  const running = active && !queued;
  const submitted = succeeded || failed || active || status === "rolled_back";
  const mode = dryRun == null
    ? submitted ? failed ? "Failed" : succeeded ? "Completed" : "Submitted" : "Not run"
    : String(dryRun).toLowerCase() === "true" ? "Validation" : "Live";
  return {
    status,
    succeeded,
    failed,
    active,
    submitted,
    badgeLabel: succeeded ? "Completed" : failed ? "Failed" : queued ? "Queued" : running ? "Running" : configured ? "Configured" : "Not configured",
    badgeClass: succeeded ? "pill-success" : failed ? "status-failed" : active ? "pill-info" : configured ? "pill-warning" : "status-failed",
    executionMode: mode,
    executionStageLabel: succeeded ? "Completed" : failed ? "Failed" : queued ? "Build queued" : running ? "Build running" : "Waiting",
    validationStageLabel: succeeded ? "Recovery validated" : failed ? "Blocked by execution failure" : "Waiting for result",
  };
}
