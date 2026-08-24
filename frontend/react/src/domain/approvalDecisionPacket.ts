export type ApprovalPacketRecord = Record<string, any>;

export const packetObject = (...values: unknown[]): ApprovalPacketRecord =>
  (values.find((value) => value && typeof value === "object") || {}) as ApprovalPacketRecord;

export const packetText = (...values: unknown[]): string => {
  const value = values.find((item) => item !== undefined && item !== null && String(item).trim());
  return value === undefined ? "Not provided" : String(value);
};

export function approvalDecisionFields(row: ApprovalPacketRecord) {
  const projection = packetObject(row.projection_payload);
  const event = packetObject(projection.event_payload);
  const recommendation = packetObject(projection.recommendation, event.recommendation, row.recommendation);
  const metadata = packetObject(recommendation.metadata);
  const plan = packetObject(metadata.execution_plan, projection.execution_plan, event.execution_plan);
  const impact = packetObject(plan.impact, metadata.impact, projection.impact, event.impact);
  const validation = packetObject(plan.validation_plan, plan.validation, metadata.validation_plan);
  const rollback = packetObject(plan.rollback_plan, plan.rollback, metadata.rollback_plan);
  const evidence = Array.isArray(recommendation.evidence) ? recommendation.evidence : Array.isArray(metadata.evidence) ? metadata.evidence : [];
  return {
    whatHappened: packetText(row.summary, row.title, event.description, event.message),
    diagnosis: packetText(recommendation.root_cause, recommendation.summary), confidence: recommendation.confidence, evidence,
    affectedResource: packetText(impact.affected_resource, plan.target_resource_id, plan.remediation_target, row.service),
    capability: packetText(plan.capability_id, plan.playbook_id, plan.runbook_id, plan.connector_id),
    exactTarget: packetText(plan.target_resource_id, plan.remediation_target),
    expectedEffect: packetText(plan.expected_effect, recommendation.expected_effect, recommendation.summary),
    risk: packetText(plan.risk_tier, row.risk_tier, row.severity), blastRadius: packetText(impact.blast_radius, plan.blast_radius),
    preconditions: Array.isArray(plan.preconditions) ? plan.preconditions : Array.isArray(plan.preflight_commands) ? plan.preflight_commands : [],
    validationPlan: packetText(validation.summary, validation.description, plan.validation_command),
    rollbackPlan: packetText(rollback.summary, rollback.description, plan.rollback_mode, Array.isArray(plan.rollback_commands) ? plan.rollback_commands.join("; ") : undefined),
    executionPreview: packetText(plan.execution_preview, plan.command_preview, plan.summary),
  };
}
