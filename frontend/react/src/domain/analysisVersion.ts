type AnalysisEnvelope = Record<string, unknown>;

function record(value: unknown): AnalysisEnvelope {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as AnalysisEnvelope
    : {};
}

export function recommendationIdFromAnalysis(payload: unknown): string {
  const envelope = record(payload);
  const workflow = record(envelope.workflow);
  const workflowRecommendation = record(workflow.recommendation);
  const directRecommendation = record(envelope.recommendation);
  return String(workflowRecommendation.id || directRecommendation.id || "").trim();
}

export function isExpectedAnalysisVersion(payload: unknown, expectedRecommendationId: unknown): boolean {
  const expected = String(expectedRecommendationId || "").trim();
  return expected.length > 0 && recommendationIdFromAnalysis(payload) === expected;
}
