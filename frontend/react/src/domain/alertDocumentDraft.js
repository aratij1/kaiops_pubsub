export function buildAlertDocumentDraft({ alertId, alert, decision, workflow, evidence }) {
  const recommendation = workflow?.recommendation || {};
  const remediation = workflow?.remediation_action || {};
  const diagnostics = [recommendation.diagnostic_actions, recommendation.diagnostic_steps, recommendation.diagnostics]
    .flat()
    .filter(Boolean);
  const validations = [
    recommendation.validation,
    recommendation.validation_checks,
    recommendation.validation_queries,
    remediation?.parameters?.validation_queries,
  ].flat().filter(Boolean);
  const rollback = recommendation.rollback
    || recommendation.rollback_plan
    || remediation.rollback
    || remediation?.parameters?.rollback_plan
    || "Rollback procedure requires operator completion.";
  const bullets = (rows, fallback) => rows.length
    ? rows.map((item) => `- ${typeof item === "string" ? item : JSON.stringify(item)}`)
    : [fallback];
  const incident = workflow?.incident || {};
  const ticketId = alert?.ticket_id
    || alert?.jira_key
    || alert?.labels?.ticket_id
    || alert?.labels?.jira_issue_key
    || incident.ticket_id
    || "Pending";
  const ticketUrl = alert?.jira_url
    || alert?.metadata?.jira?.url
    || incident?.metadata?.jira?.url
    || "Not supplied";

  return [
    `# ${alert?.name || "Alert"}`,
    "",
    "## Incident record",
    `Alert ID: ${alertId}`,
    `Incident ID: ${incident.id || workflow?.incident_id || "Pending"}`,
    `Jira ticket: ${ticketId}`,
    `Jira URL: ${ticketUrl}`,
    `Service: ${alert?.service || "Not supplied"}`,
    `Environment: ${alert?.environment || "Not supplied"}`,
    `Severity: ${alert?.severity || "Not supplied"}`,
    "",
    "## Root cause analysis",
    decision.rootCause,
    "",
    "## Technical and business impact",
    decision.customerImpact,
    `Service impact: ${decision.serviceImpact}`,
    `Dependency impact: ${decision.dependencyImpact}`,
    "",
    "## Diagnostic steps",
    ...bullets(diagnostics, "- Review the cited logs, metrics, traces, dependencies, and recent changes."),
    "",
    "## Resolution procedure",
    decision.action || recommendation.recommended_action || "Resolution procedure requires operator completion.",
    "",
    "## Validation checks",
    ...bullets(validations, "- Confirm alert clearance and recovery of service health, latency, errors, dependencies, and business transactions."),
    "",
    "## Rollback and escalation",
    ...(Array.isArray(rollback) ? rollback.map((item) => `- ${item}`) : [String(rollback)]),
    "",
    "## Evidence",
    ...evidence.slice(0, 40).map((row) => `- [${row.id || row.source}] ${row.citation || row.source}`),
    "",
    `Confidence: ${Math.round(Number(decision.confidence || 0) * 100)}%`,
  ].join("\n");
}
