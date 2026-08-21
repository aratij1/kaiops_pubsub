import { looksLikeUuid } from "../onboardingUtils";

export function approvalIncidentId(row) {
  return String(row?.incident_id || row?.id || row?.alert_id || "").trim();
}

export function approvalRecommendationId(row) {
  const candidates = [row?.recommendation_id, row?.recommendation?.id, row?.remediation_recommendation_id, row?.recommended_action_id];
  return candidates.map((candidate) => String(candidate || "").trim()).find(looksLikeUuid) || "";
}

export function approvalFlowId(row) {
  return String(row?.flow_id || row?.workflow_id || row?.flow || "").trim();
}

export function approvalTraceId(row) {
  return String(row?.trace_id || row?.correlation_id || "").trim();
}

export function approvalRecommendationFromPayload(payload) {
  const normalized = payload && typeof payload === "object" ? payload : {};
  const data = normalized.data && typeof normalized.data === "object" ? normalized.data : {};
  const recommendation = normalized.recommendation && typeof normalized.recommendation === "object"
    ? normalized.recommendation : data.recommendation && typeof data.recommendation === "object" ? data.recommendation : {};
  const approval = normalized.approval && typeof normalized.approval === "object"
    ? normalized.approval : data.approval && typeof data.approval === "object" ? data.approval : {};
  const sourcePayload = normalized.source_payload && typeof normalized.source_payload === "object"
    ? normalized.source_payload : data.source_payload && typeof data.source_payload === "object" ? data.source_payload : {};
  const sourceRecommendation = sourcePayload.recommendation && typeof sourcePayload.recommendation === "object"
    ? sourcePayload.recommendation : {};
  const candidates = [
    normalized.recommendation_id, data.recommendation_id, recommendation.id, approval.recommendation_id,
    normalized.remediation_recommendation_id, data.remediation_recommendation_id,
    normalized.recommended_action_id, data.recommended_action_id,
    sourcePayload.recommendation_id, sourceRecommendation.id,
  ];
  return candidates.map((candidate) => String(candidate || "").trim()).find(looksLikeUuid) || "";
}

export function approvalFlowFromPayload(payload) {
  const normalized = payload && typeof payload === "object" ? payload : {};
  const decision = normalized.decision && typeof normalized.decision === "object" ? normalized.decision : {};
  const recommendation = normalized.recommendation && typeof normalized.recommendation === "object" ? normalized.recommendation : {};
  return String(normalized.flow_id || decision.flow_id || recommendation.flow_id || normalized.trace_id
    || recommendation.trace_id || normalized.correlation_id || recommendation.correlation_id || "").trim();
}
