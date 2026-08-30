export type AnalysisRequestStatus = Record<string, unknown> | null | undefined;

const TERMINAL_FAILURE_STATES = new Set(["failed", "timed_out", "superseded"]);

export function analysisRequestOutcome(status: AnalysisRequestStatus, expectedRecommendationId = "") {
  const state = String(status?.status || "").trim().toLowerCase();
  const recommendationId = String(status?.recommendation_id || "").trim();
  const expected = String(expectedRecommendationId || "").trim();
  const ready = status?.ready === true && (!expected || recommendationId === expected);
  const terminalFailure = !ready && (status?.terminal === true || TERMINAL_FAILURE_STATES.has(state));
  const reason = String(status?.terminal_reason || status?.error || "").trim();

  return {
    state,
    ready,
    terminalFailure,
    retryable: status?.retryable === true,
    reason: reason || (state === "timed_out"
      ? "Analysis timed out before a recommendation was persisted."
      : "Analysis ended before a recommendation was persisted."),
  };
}

export function analysisFailureMessage(status: AnalysisRequestStatus) {
  const outcome = analysisRequestOutcome(status);
  const prefix = outcome.state === "timed_out" ? "Analysis timed out" : "Analysis failed";
  const retry = outcome.retryable
    ? " Run fresh analysis again; active requests are safely coalesced."
    : " Review the incident evidence before running fresh analysis again.";
  return `${prefix}: ${outcome.reason}${retry}`;
}
