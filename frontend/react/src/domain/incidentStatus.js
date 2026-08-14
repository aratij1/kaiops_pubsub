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
  if (["succeeded", "completed", "closed", "resolved"].includes(remediation)
      || ["closed", "resolved"].includes(incident)) {
    return "succeeded";
  }
  if (String(queueUrl || "").trim()) {
    return "queued";
  }
  if (incident === "failed") {
    return "failed";
  }
  return remediation;
}
